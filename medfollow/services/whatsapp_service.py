"""Envoi de messages WhatsApp aux patients (Meta Cloud API).

Deux usages :
- confirmation à la création d'un rendez-vous (`notify_appointment_created`) ;
- rappel 24 h avant le rendez-vous (`send_due_reminder`, appelé par le
  planificateur `reminder_scheduler`).

Règles importantes :
- Un message initié par la clinique DOIT utiliser un *template* pré-approuvé par
  Meta (catégorie « Utility »). On envoie donc des templates, pas du texte libre.
- Si l'envoi n'est pas configuré (`config.whatsapp_configured()` faux), le
  service tourne en **dry-run** : il journalise mais n'appelle jamais l'API, pour
  que l'app fonctionne sans identifiants sans casser la création de rendez-vous.
- Chaque appel de haut niveau ouvre sa PROPRE connexion SQLite : ces fonctions
  tournent hors requête (tâche de fond, planificateur) où le `get_db` de la
  requête n'est plus disponible — même motif que le middleware
  `_inject_active_consultation` de `main.py`.

Convention des templates (à créer côté Meta avec ces variables, dans cet ordre) :
- `rdv_confirmation` : {{1}} prénom, {{2}} Dr Nom, {{3}} date (JJ/MM/AAAA), {{4}} heure (HH:MM)
- `rdv_rappel_24h`   : {{1}} prénom, {{2}} Dr Nom, {{3}} date (JJ/MM/AAAA), {{4}} heure (HH:MM)
"""
import re
import traceback
from datetime import datetime

import aiosqlite

import config


# --------------------------------------------------------------------------- #
# Numéro de téléphone → format E.164 sans « + » (ce qu'attend Meta)
# --------------------------------------------------------------------------- #
def normalize_msisdn(raw, default_cc: str = None):
    """Transforme un numéro saisi librement en E.164 sans « + ».

    Exemples (indicatif Maroc 212) :
        '0612345678'      -> '212612345678'
        '06 12 34 56 78'  -> '212612345678'
        '+212612345678'   -> '212612345678'
        '00212612345678'  -> '212612345678'
    Renvoie None si le numéro paraît inexploitable.
    """
    if not raw:
        return None
    default_cc = (default_cc or config.WHATSAPP_DEFAULT_CC or "212").lstrip("+")
    s = str(raw).strip()
    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if has_plus:
        pass                     # déjà international : on garde les chiffres tels quels
    elif digits.startswith("00"):
        digits = digits[2:]      # préfixe international 00 -> retiré
    elif digits.startswith("0"):
        digits = default_cc + digits[1:]   # numéro local (0X...) -> indicatif + reste
    elif digits.startswith(default_cc):
        pass                     # déjà préfixé par l'indicatif
    else:
        # Numéro sans 0 initial ni indicatif : on préfixe par l'indicatif par défaut.
        digits = default_cc + digits
    # Garde-fou longueur (E.164 : max 15 chiffres, min ~8).
    if not (8 <= len(digits) <= 15):
        return None
    return digits


# --------------------------------------------------------------------------- #
# Formatage date / heure
# --------------------------------------------------------------------------- #
def _parse_dt(value):
    if not value:
        return None
    s = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _fmt_date(dt):
    return dt.strftime("%d/%m/%Y") if dt else ""


def _fmt_time(dt):
    return dt.strftime("%H:%M") if dt else ""


def _doctor_label(first, last):
    name = " ".join(p for p in (first, last) if p).strip()
    return f"Dr {name}".strip() if name else "votre praticien"


# --------------------------------------------------------------------------- #
# Journalisation (connexion propre)
# --------------------------------------------------------------------------- #
async def _log(db, *, appointment_id, patient_id, doctor_id, direction, kind,
               to_msisdn, template, body, wa_message_id, status, error):
    try:
        await db.execute(
            """INSERT INTO whatsapp_messages
               (appointment_id, patient_id, doctor_id, direction, kind, to_msisdn,
                template, body, wa_message_id, status, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (appointment_id, patient_id, doctor_id, direction, kind, to_msisdn,
             template, body, wa_message_id, status, error),
        )
        await db.commit()
    except Exception:
        traceback.print_exc()


# --------------------------------------------------------------------------- #
# Appel API Meta (import httpx paresseux : si le paquet manque dans le venv,
# on n'écroule pas l'app — on renvoie une erreur exploitable)
# --------------------------------------------------------------------------- #
async def _send_template_api(to_msisdn: str, template: str, variables):
    """Renvoie (ok, wa_message_id, error)."""
    try:
        import httpx
    except ImportError:
        return False, None, "httpx non installé dans l'environnement"

    url = (
        f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}"
        f"/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to_msisdn,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": config.WHATSAPP_TEMPLATE_LANG},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(v)} for v in variables],
                }
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code // 100 == 2:
            data = resp.json()
            wamid = (data.get("messages") or [{}])[0].get("id")
            return True, wamid, None
        # Erreur Meta : on remonte le corps pour diagnostic.
        return False, None, f"HTTP {resp.status_code}: {resp.text[:500]}"
    except Exception as e:  # réseau, timeout, JSON…
        return False, None, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# Envoi d'un template + journalisation (brique commune)
# --------------------------------------------------------------------------- #
async def _gate_and_send(db, *, appointment_id, patient_id, doctor_id, kind, template,
                         to, variables, readable, opt_out=False, doctor_enabled=True):
    """Applique les garde-fous, envoie (ou dry-run) et journalise.

    Renvoie un statut : 'sent' | 'dryrun' | 'skipped' | 'failed'.
    ('failed' = échec réseau/API → l'appelant peut re-tenter ; les autres sont
    définitifs.)
    """
    def _log_kw(**over):
        base = dict(appointment_id=appointment_id, patient_id=patient_id,
                    doctor_id=doctor_id, direction="out", kind=kind, to_msisdn=to,
                    template=template, body=readable, wa_message_id=None,
                    status=None, error=None)
        base.update(over)
        return base

    # Interrupteur du praticien : rien n'est envoyé si le service est désactivé pour lui.
    if not doctor_enabled:
        await _log(db, **_log_kw(status="skipped",
                                 error="service WhatsApp désactivé pour ce praticien"))
        return "skipped"
    if opt_out:
        await _log(db, **_log_kw(status="skipped", error="patient opt-out WhatsApp"))
        return "skipped"
    if not to:
        await _log(db, **_log_kw(to_msisdn=None, status="skipped",
                                 error="numéro de téléphone absent/invalide"))
        return "skipped"

    # Dry-run : pas d'identifiants -> on journalise sans appeler l'API.
    if not config.whatsapp_configured():
        await _log(db, **_log_kw(status="dryrun"))
        print(f"[whatsapp:dry-run] -> {to} : {readable}")
        return "dryrun"

    ok, wamid, error = await _send_template_api(to, template, variables)
    await _log(db, **_log_kw(wa_message_id=wamid,
                             status="sent" if ok else "failed", error=error))
    if not ok:
        print(f"[whatsapp:failed] -> {to} : {error}")
    return "sent" if ok else "failed"


async def _dispatch(db, *, appointment_id, patient_id, doctor_id, kind, template,
                    phone_raw, first_name, doctor_first, doctor_last, start_raw,
                    opt_out=False, doctor_enabled=True):
    """Confirmation / rappel de RDV : construit les variables puis délègue."""
    prenom = (first_name or "").strip() or "cher patient"
    doctor = _doctor_label(doctor_first, doctor_last)
    dt = _parse_dt(start_raw)
    variables = [prenom, doctor, _fmt_date(dt), _fmt_time(dt)]
    readable = (
        f"[{template}] {prenom} — RDV avec {doctor} le "
        f"{_fmt_date(dt)} à {_fmt_time(dt)}"
    )
    to = normalize_msisdn(phone_raw)
    return await _gate_and_send(
        db, appointment_id=appointment_id, patient_id=patient_id, doctor_id=doctor_id,
        kind=kind, template=template, to=to, variables=variables, readable=readable,
        opt_out=opt_out, doctor_enabled=doctor_enabled)


# --------------------------------------------------------------------------- #
# Entrées de haut niveau
# --------------------------------------------------------------------------- #
_APPT_SELECT = """
    SELECT a.id, a.patient_id, a.doctor_id, a.start_datetime,
           a.whatsapp_confirmation_sent_at, a.whatsapp_reminder_sent_at,
           p.first_name AS p_first, p.phone AS p_phone,
           COALESCE(p.whatsapp_opt_out, 0) AS opt_out,
           u.first_name AS d_first, u.last_name AS d_last,
           COALESCE(u.whatsapp_enabled, 1) AS wa_enabled
    FROM appointments a
    JOIN patients p ON a.patient_id = p.id
    JOIN users u    ON a.doctor_id  = u.id
    WHERE a.id = ?
"""


async def _open_db():
    db = await aiosqlite.connect(config.DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def notify_appointment_created(appointment_id: int) -> None:
    """Confirmation à la création (appelée en tâche de fond, best-effort)."""
    try:
        db = await _open_db()
    except Exception:
        traceback.print_exc()
        return
    try:
        cur = await db.execute(_APPT_SELECT, (appointment_id,))
        r = await cur.fetchone()
        if not r:
            return
        status = await _dispatch(
            db, appointment_id=r["id"], patient_id=r["patient_id"],
            doctor_id=r["doctor_id"], kind="confirmation",
            template=config.WHATSAPP_TPL_CONFIRMATION, phone_raw=r["p_phone"],
            first_name=r["p_first"], doctor_first=r["d_first"], doctor_last=r["d_last"],
            start_raw=r["start_datetime"], opt_out=bool(r["opt_out"]),
            doctor_enabled=bool(r["wa_enabled"]),
        )
        if status == "sent":
            await db.execute(
                "UPDATE appointments SET whatsapp_confirmation_sent_at = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), appointment_id),
            )
            await db.commit()
    except Exception:
        traceback.print_exc()
    finally:
        await db.close()


async def send_due_reminder(appointment_id: int) -> bool:
    """Rappel 24 h (appelé par le planificateur). Stampe reminder_sent_at si envoyé."""
    try:
        db = await _open_db()
    except Exception:
        traceback.print_exc()
        return False
    try:
        cur = await db.execute(_APPT_SELECT, (appointment_id,))
        r = await cur.fetchone()
        if not r or r["whatsapp_reminder_sent_at"]:
            return False   # déjà rappelé (garde-fou anti-doublon)
        status = await _dispatch(
            db, appointment_id=r["id"], patient_id=r["patient_id"],
            doctor_id=r["doctor_id"], kind="rappel",
            template=config.WHATSAPP_TPL_RAPPEL, phone_raw=r["p_phone"],
            first_name=r["p_first"], doctor_first=r["d_first"], doctor_last=r["d_last"],
            start_raw=r["start_datetime"], opt_out=bool(r["opt_out"]),
            doctor_enabled=bool(r["wa_enabled"]),
        )
        # On stampe pour tout sauf un échec RÉSEAU/API ('failed'), qui doit être
        # re-tenté au prochain tick. 'sent'/'dryrun'/'skipped' sont définitifs.
        if status != "failed":
            await db.execute(
                "UPDATE appointments SET whatsapp_reminder_sent_at = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), appointment_id),
            )
            await db.commit()
        return status == "sent"
    except Exception:
        traceback.print_exc()
        return False
    finally:
        await db.close()


_RAPPEL_SELECT = """
    SELECT r.id, r.patient_id, r.doctor_id, r.description, r.whatsapp_sent_at,
           p.first_name AS p_first, p.phone AS p_phone,
           COALESCE(p.whatsapp_opt_out, 0) AS opt_out,
           u.first_name AS d_first, u.last_name AS d_last,
           COALESCE(u.whatsapp_enabled, 1) AS wa_enabled
    FROM rappels r
    JOIN patients p ON r.patient_id = p.id
    JOIN users u    ON r.doctor_id  = u.id
    WHERE r.id = ?
"""


async def send_rappel_by_id(rappel_id: int) -> str:
    """Envoie un rappel de soin WhatsApp (module Rappels).

    Renvoie le statut ('sent'|'dryrun'|'skipped'|'failed'). Stampe
    rappels.whatsapp_sent_at uniquement quand un message part réellement ('sent')
    ou en simulation ('dryrun') — jamais pour un 'skipped'/'failed', pour que le
    badge « Envoyé par DoctivoAssist » reste fiable.
    """
    try:
        db = await _open_db()
    except Exception:
        traceback.print_exc()
        return "failed"
    try:
        cur = await db.execute(_RAPPEL_SELECT, (rappel_id,))
        r = await cur.fetchone()
        if not r:
            return "skipped"
        prenom = (r["p_first"] or "").strip() or "cher patient"
        doctor = _doctor_label(r["d_first"], r["d_last"])
        motif = (r["description"] or "votre rendez-vous de suivi").strip()
        variables = [prenom, motif, doctor]      # {{1}} prénom, {{2}} motif, {{3}} Dr Nom
        readable = f"[{config.WHATSAPP_TPL_RAPPEL_SOIN}] {prenom} — rappel : {motif} ({doctor})"
        to = normalize_msisdn(r["p_phone"])
        status = await _gate_and_send(
            db, appointment_id=None, patient_id=r["patient_id"], doctor_id=r["doctor_id"],
            kind="rappel_soin", template=config.WHATSAPP_TPL_RAPPEL_SOIN, to=to,
            variables=variables, readable=readable, opt_out=bool(r["opt_out"]),
            doctor_enabled=bool(r["wa_enabled"]),
        )
        if status in ("sent", "dryrun"):
            await db.execute(
                "UPDATE rappels SET whatsapp_sent_at = ?, status = 'contacte', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rappel_id),
            )
            await db.commit()
        return status
    except Exception:
        traceback.print_exc()
        return "failed"
    finally:
        await db.close()
