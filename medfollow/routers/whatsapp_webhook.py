"""Webhook entrant WhatsApp (Meta Cloud API) — LOT 2 (flux retour).

Reçoit les réponses des patients (Confirmer / Annuler) et les fait remonter dans
le statut du rendez-vous concerné.

⚠️ Nécessite une URL PUBLIQUE EN HTTPS (Meta refuse un webhook non-HTTPS). Tant
que la VM est en HTTP simple, ce webhook n'est pas joignable par Meta : il reste
inerte. Il s'active en :
  1. exposant l'app en HTTPS (TLS sur la VM, ou Cloudflare) ;
  2. renseignant MEDFOLLOW_WHATSAPP_VERIFY_TOKEN et MEDFOLLOW_WHATSAPP_APP_SECRET ;
  3. déclarant l'URL du webhook dans l'app Meta.

Sécurité : la route est PUBLIQUE (pas de session) mais authentifiée par la
signature HMAC-SHA256 `X-Hub-Signature-256` (secret = App Secret). Sans App Secret
configuré, on ignore les POST (retour 200, aucun traitement) pour ne jamais
traiter un payload non vérifié. La route est exemptée de CSRF dans main.py
(préfixe /webhooks/).

Mapping réponse → rendez-vous : l'inbound Meta porte `context.id` = le wamid du
message auquel le patient répond, c.-à-d. le wamid de NOTRE rappel, stocké dans
whatsapp_messages.wa_message_id. On retrouve ainsi le rendez-vous sans payload
dynamique. Repli : rapprochement par numéro d'expéditeur.
"""
import hashlib
import hmac
import json
import traceback
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, JSONResponse

import config
from services.audit import log_audit

router = APIRouter(prefix="/webhooks")


def _intent(text: str):
    """Déduit l'intention du patient à partir du texte / titre de bouton."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if any(w in t for w in ("confirm", "oui", "yes", "ok", "d'accord", "present", "présent")):
        return "confirme"
    if any(w in t for w in ("annul", "non", "no", "cancel", "empêch", "empech")):
        return "annule"
    return None


def _extract(payload):
    """Extrait (from_msisdn, context_wamid, text) du premier message entrant.

    Renvoie None s'il n'y a pas de message patient (ex. simple accusé de statut).
    """
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    frm = msg.get("from")
                    ctx = (msg.get("context") or {}).get("id")
                    mtype = msg.get("type")
                    text = ""
                    if mtype == "text":
                        text = (msg.get("text") or {}).get("body", "")
                    elif mtype == "button":
                        b = msg.get("button") or {}
                        text = b.get("text") or b.get("payload") or ""
                    elif mtype == "interactive":
                        it = msg.get("interactive") or {}
                        br = it.get("button_reply") or it.get("list_reply") or {}
                        text = br.get("title") or br.get("id") or ""
                    return frm, ctx, text
    except Exception:
        traceback.print_exc()
    return None


@router.get("/whatsapp")
async def verify(request: Request):
    """Handshake de vérification Meta (abonnement du webhook)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    if mode == "subscribe" and token and config.WHATSAPP_VERIFY_TOKEN \
            and hmac.compare_digest(token, config.WHATSAPP_VERIFY_TOKEN):
        return PlainTextResponse(challenge)
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/whatsapp")
async def receive(request: Request):
    body = await request.body()

    # Sans App Secret configuré, on n'a aucun moyen de vérifier l'authenticité :
    # on ignore (200) pour ne jamais traiter un payload non signé.
    if not config.WHATSAPP_APP_SECRET:
        return JSONResponse(content={"ignored": True})

    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(
        config.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return PlainTextResponse("invalid signature", status_code=403)

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse(content={"ok": True})   # 200 : ne pas faire re-tenter Meta

    extracted = _extract(payload)
    if not extracted:
        return JSONResponse(content={"ok": True})
    frm, ctx_wamid, text = extracted
    intent = _intent(text)

    try:
        db = await aiosqlite.connect(config.DATABASE_PATH)
        db.row_factory = aiosqlite.Row
    except Exception:
        traceback.print_exc()
        return JSONResponse(content={"ok": True})

    try:
        appt = None
        # 1) Rapprochement fiable par le message cité (context.id = wamid du rappel).
        if ctx_wamid:
            cur = await db.execute(
                """SELECT appointment_id, patient_id, doctor_id FROM whatsapp_messages
                   WHERE wa_message_id = ? AND direction = 'out'
                   ORDER BY id DESC LIMIT 1""",
                (ctx_wamid,),
            )
            appt = await cur.fetchone()
        # 2) Repli : dernier rappel sortant vers ce numéro.
        if appt is None and frm:
            cur = await db.execute(
                """SELECT appointment_id, patient_id, doctor_id FROM whatsapp_messages
                   WHERE to_msisdn = ? AND direction = 'out' AND kind = 'rappel'
                   ORDER BY id DESC LIMIT 1""",
                (frm,),
            )
            appt = await cur.fetchone()

        appointment_id = appt["appointment_id"] if appt else None
        patient_id = appt["patient_id"] if appt else None
        doctor_id = appt["doctor_id"] if appt else None

        # Journalise l'entrant quoi qu'il arrive.
        await db.execute(
            """INSERT INTO whatsapp_messages
               (appointment_id, patient_id, doctor_id, direction, kind, to_msisdn,
                template, body, wa_message_id, status, error)
               VALUES (?, ?, ?, 'in', 'reponse', ?, NULL, ?, ?, 'received', ?)""",
            (appointment_id, patient_id, doctor_id, frm, text, ctx_wamid,
             None if intent else "intention non reconnue"),
        )
        await db.commit()

        # Applique la réponse au rendez-vous (sans écraser un RDV déjà commencé/terminé).
        if appointment_id and intent:
            new_status = "confirme" if intent == "confirme" else "annule"
            await db.execute(
                """UPDATE appointments
                   SET whatsapp_response = ?, whatsapp_responded_at = ?,
                       status = CASE WHEN status IN ('planifie', 'confirme', 'annule')
                                     THEN ? ELSE status END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (intent, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 new_status, appointment_id),
            )
            await db.commit()
            await log_audit(
                db, None, "rdv_reponse_whatsapp", entity_type="appointment",
                entity_id=appointment_id, patient_id=patient_id,
                details=f"reponse={intent} via WhatsApp",
            )
    except Exception:
        traceback.print_exc()
    finally:
        await db.close()

    return JSONResponse(content={"ok": True})
