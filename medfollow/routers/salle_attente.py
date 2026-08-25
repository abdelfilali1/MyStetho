"""Module « Salle d'attente ».

Deux interfaces :

- `/salle-attente` : le tableau praticien/secrétaire (RDV attendus, file d'attente,
  patients appelés/en cours). Ouvert au rôle secrétaire, comme l'agenda et les
  rappels — c'est son poste de travail principal.
- `/salle-attente/ecran/{token}` : l'écran diffusé sur la TV de la salle d'attente.
  Volontairement **hors session** : une TV laissée allumée ne doit pas porter un
  JWT donnant accès aux dossiers. Elle lit une URL en lecture seule dont le JSON
  est déjà anonymisé côté serveur.
"""
from datetime import date
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from config import TEMPLATES_DIR, UPLOAD_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api, effective_doctor_id
from services.audit import log_audit, client_ip
from services import waiting_room as wr

router = APIRouter(prefix="/salle-attente")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Logo du cabinet affiché sur l'écran ------------------------------------
# Image seulement, et jamais servie en statique : `uploads/` n'est pas monté,
# l'écran y accède par une route bornée à son jeton.
WR_LOGO_DIR = os.path.join(UPLOAD_DIR, "salle_attente")
MAX_LOGO_BYTES = 2 * 1024 * 1024        # un logo de TV n'a pas besoin des 50 Mo globaux
_LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def _sniff_image(head: bytes) -> Optional[str]:
    """Extension déduite des octets magiques, ou None si ce n'est pas une image
    accepté. Le nom envoyé par le client n'est jamais cru sur parole, et le SVG
    est écarté : c'est un document exécutable, pas une image."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


# CSP élargie posée UNIQUEMENT sur la page de l'écran, et seulement quand la
# musique est active : le lecteur YouTube a besoin de son iframe et de son
# script, mais la politique stricte du reste de l'application ne bouge pas.
# Le middleware de main.py pose la CSP avec setdefault : l'en-tête défini ici
# n'est donc pas écrasé.
_TV_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "frame-src 'self' blob: https://www.youtube.com https://www.youtube-nocookie.com; "
    "img-src 'self' data: blob: https://i.ytimg.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "script-src 'self' 'unsafe-inline' https://www.youtube.com https://s.ytimg.com; "
    "connect-src 'self' https://www.youtube.com; "
    "media-src 'self' blob:; "
    "form-action 'self'"
)


async def _body(request: Request) -> dict:
    """Accepte indifféremment un corps JSON ou un formulaire."""
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        return dict(await request.form())
    except Exception:
        return {}


async def _owned_entry(db, entry_id: int, doctor_id: int):
    cur = await db.execute(
        "SELECT * FROM waiting_room WHERE id = ? AND doctor_id = ?", (entry_id, doctor_id)
    )
    return await cur.fetchone()


# ------------------------------------------------------------ interface staff

@router.get("/", response_class=HTMLResponse)
async def salle_attente(
    request: Request,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    settings = await wr.get_settings(db, uid)
    board = await wr.board(db, uid)
    return templates.TemplateResponse(
        "salle_attente/index.html",
        {
            "request": request,
            "user": user,
            "active": "salle_attente",
            "board": board,
            "settings": settings,
            "screen_url": "/salle-attente/ecran/%s" % settings["display_token"],
        },
    )


@router.get("/api/board")
async def api_board(
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    return JSONResponse(content=await wr.board(db, effective_doctor_id(user)))


@router.get("/api/count")
async def api_count(
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    return JSONResponse(content={"count": await wr.waiting_count(db, effective_doctor_id(user))})


@router.post("/checkin")
async def checkin(
    request: Request,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Pointe l'arrivée d'un patient : depuis un RDV, depuis une fiche patient,
    ou sur simple saisie de nom (patient sans RDV ni dossier)."""
    uid = effective_doctor_id(user)
    data = await _body(request)

    def _int(key):
        try:
            return int(data.get(key)) if data.get(key) not in (None, "") else None
        except (TypeError, ValueError):
            return None

    appointment_id = _int("appointment_id")
    patient_id = _int("patient_id")
    name = (data.get("name") or "").strip()
    reason = (data.get("reason") or "").strip()
    priority = 1 if str(data.get("priority") or "") in ("1", "true", "on") else 0

    if appointment_id:
        cur = await db.execute(
            "SELECT id FROM appointments WHERE id = ? AND doctor_id = ?", (appointment_id, uid)
        )
        if not await cur.fetchone():
            return JSONResponse(status_code=403, content={"error": "Accès refusé"})
    if patient_id:
        cur = await db.execute(
            "SELECT id FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, uid)
        )
        if not await cur.fetchone():
            return JSONResponse(status_code=403, content={"error": "Accès refusé"})
    if not appointment_id and not patient_id and not name:
        return JSONResponse(status_code=400, content={"error": "Indiquez un patient ou un nom"})

    entry_id, created = await wr.check_in(
        db,
        uid,
        appointment_id=appointment_id,
        patient_id=patient_id,
        name=name or None,
        reason=reason or None,
        priority=priority,
        created_by=user["sub"],
    )
    if created:
        await log_audit(
            db, user, "salle_attente_arrivee", entity_type="waiting_room", entity_id=entry_id,
            patient_id=patient_id, ip=client_ip(request),
        )
    return JSONResponse(content={"ok": True, "id": entry_id, "created": created})


@router.post("/{entry_id}/call")
async def call_entry(
    request: Request,
    entry_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Appelle le patient : bandeau + carillon sur l'écran de la salle d'attente."""
    uid = effective_doctor_id(user)
    entry = await _owned_entry(db, entry_id, uid)
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Entrée introuvable"})

    data = await _body(request)
    room = data.get("room")
    await wr.set_status(db, entry_id, "appele", room=room if room is not None else None)

    # Le RDV lié suit : l'agenda montre le patient comme pris en charge.
    if entry["appointment_id"]:
        await db.execute(
            "UPDATE appointments SET status = 'en_cours', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (entry["appointment_id"],),
        )
        await db.commit()

    await log_audit(
        db, user, "salle_attente_appel", entity_type="waiting_room", entity_id=entry_id,
        patient_id=entry["patient_id"], ip=client_ip(request),
    )
    return JSONResponse(content={"ok": True})


@router.post("/{entry_id}/status")
async def update_entry_status(
    request: Request,
    entry_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    entry = await _owned_entry(db, entry_id, uid)
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Entrée introuvable"})

    data = await _body(request)
    status = (data.get("status") or "").strip()
    if status not in wr.QUEUE_STATUSES:
        return JSONResponse(status_code=400, content={"error": "Statut invalide"})

    await wr.set_status(db, entry_id, status, room=data.get("room"))

    # Répercussion sur l'agenda (mêmes libellés de statut des deux côtés).
    apt_status = {"en_cours": "en_cours", "termine": "termine", "absent": "absent"}.get(status)
    if entry["appointment_id"] and apt_status:
        await db.execute(
            "UPDATE appointments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (apt_status, entry["appointment_id"]),
        )
        await db.commit()

    await log_audit(
        db, user, "salle_attente_statut", entity_type="waiting_room", entity_id=entry_id,
        patient_id=entry["patient_id"], ip=client_ip(request), details="status=%s" % status,
    )
    return JSONResponse(content={"ok": True})


@router.post("/{entry_id}/move")
async def move_entry(
    request: Request,
    entry_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    if not await _owned_entry(db, entry_id, uid):
        return JSONResponse(status_code=404, content={"error": "Entrée introuvable"})
    data = await _body(request)
    direction = (data.get("direction") or "").strip()
    if direction not in ("up", "down"):
        return JSONResponse(status_code=400, content={"error": "Direction invalide"})
    moved = await wr.move(db, uid, entry_id, direction)
    return JSONResponse(content={"ok": True, "moved": moved})


@router.post("/{entry_id}/priority")
async def toggle_priority(
    request: Request,
    entry_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    entry = await _owned_entry(db, entry_id, uid)
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Entrée introuvable"})
    data = await _body(request)
    raw = data.get("priority")
    priority = (0 if entry["priority"] else 1) if raw is None else (1 if str(raw) in ("1", "true", "on") else 0)
    await wr.set_priority(db, uid, entry_id, priority)
    await log_audit(
        db, user, "salle_attente_urgence", entity_type="waiting_room", entity_id=entry_id,
        patient_id=entry["patient_id"], ip=client_ip(request), details="priority=%d" % priority,
    )
    return JSONResponse(content={"ok": True, "priority": priority})


@router.post("/{entry_id}/delete")
async def delete_entry(
    request: Request,
    entry_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    entry = await _owned_entry(db, entry_id, uid)
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Entrée introuvable"})
    await db.execute("DELETE FROM waiting_room WHERE id = ?", (entry_id,))
    await db.commit()
    await log_audit(
        db, user, "salle_attente_retrait", entity_type="waiting_room", entity_id=entry_id,
        patient_id=entry["patient_id"], ip=client_ip(request),
    )
    return JSONResponse(content={"ok": True})


@router.post("/patients")
async def create_patient_entry(
    request: Request,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Crée une fiche patient depuis la salle d'attente.

    Deux usages, un seul aller-retour pour éviter qu'une fiche existe sans être
    reliée à la file si le second appel échouait :
    - sans `entry_id` : la fiche est créée et le patient mis en attente ;
    - avec `entry_id` : la fiche est rattachée à une entrée existante (patient
      arrivé sous un simple nom), ce qui débloque le démarrage d'une consultation.
    """
    uid = effective_doctor_id(user)
    data = await _body(request)

    first = (data.get("first_name") or "").strip()[:80]
    last = (data.get("last_name") or "").strip()[:80]
    dob = (data.get("date_of_birth") or "").strip()
    gender = (data.get("gender") or "").strip()
    phone = (data.get("phone") or "").strip()[:40]
    reason = (data.get("reason") or "").strip()[:200]
    priority = 1 if str(data.get("priority") or "") in ("1", "true", "on") else 0

    if not first or not last:
        return JSONResponse(status_code=400, content={"error": "Nom et prénom obligatoires"})
    # patients.date_of_birth est NOT NULL : la date est exigée dès le comptoir.
    try:
        born = date.fromisoformat(dob)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Date de naissance invalide (AAAA-MM-JJ)"})
    if born > date.today():
        return JSONResponse(status_code=400, content={"error": "Date de naissance dans le futur"})
    if gender not in ("", "M", "F"):
        return JSONResponse(status_code=400, content={"error": "Sexe invalide"})

    try:
        entry_id = int(data.get("entry_id")) if data.get("entry_id") not in (None, "") else None
    except (TypeError, ValueError):
        entry_id = None

    entry = None
    if entry_id:
        entry = await _owned_entry(db, entry_id, uid)
        if not entry:
            return JSONResponse(status_code=404, content={"error": "Entrée introuvable"})
        if entry["patient_id"]:
            # Ne jamais écraser un dossier déjà rattaché.
            return JSONResponse(status_code=409, content={"error": "Ce patient a déjà un dossier"})
        if entry["status"] in ("termine", "absent", "parti"):
            return JSONResponse(status_code=409, content={"error": "Ce passage est terminé"})

    cur = await db.execute(
        """INSERT INTO patients (doctor_id, first_name, last_name, date_of_birth, gender, phone)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uid, first, last, dob, gender or None, phone or None),
    )
    await db.commit()
    patient_id = cur.lastrowid
    await log_audit(
        db, user, "patient_cree", entity_type="patient", entity_id=patient_id,
        patient_id=patient_id, ip=client_ip(request), details="créé depuis la salle d'attente",
    )

    if entry:
        # Rattachement direct : passer par check_in() serait refusé par sa
        # déduplication et laisserait l'entrée d'origine sans dossier.
        # display_name devient inutile (le nom vient désormais de la jointure).
        await db.execute(
            """UPDATE waiting_room
               SET patient_id = ?, display_name = NULL,
                   reason = COALESCE(NULLIF(?, ''), reason), updated_at = ?
               WHERE id = ? AND doctor_id = ?""",
            (patient_id, reason, wr.now_ts(), entry_id, uid),
        )
        await db.commit()
        await log_audit(
            db, user, "salle_attente_fiche_creee", entity_type="waiting_room", entity_id=entry_id,
            patient_id=patient_id, ip=client_ip(request),
        )
    else:
        entry_id, _created = await wr.check_in(
            db, uid, patient_id=patient_id, reason=reason or None,
            priority=priority, created_by=user["sub"],
        )
        await log_audit(
            db, user, "salle_attente_arrivee", entity_type="waiting_room", entity_id=entry_id,
            patient_id=patient_id, ip=client_ip(request),
        )

    return JSONResponse(content={"ok": True, "patient_id": patient_id, "entry_id": entry_id})


# ----------------------------------------------------------------- réglages

@router.post("/reglages")
async def save_reglages(
    request: Request,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    data = await _body(request)
    ticker = data.get("ticker")
    if isinstance(ticker, str):
        ticker = [line for line in ticker.splitlines()]
    # Un lien illisible est refusé tout de suite plutôt que d'être silencieusement
    # ignoré : le praticien croirait sa musique configurée.
    music_url = (data.get("music_url") or "").strip()
    if music_url and not wr.parse_youtube(music_url)[1]:
        return JSONResponse(status_code=400, content={"error": "Lien YouTube non reconnu"})

    settings = await wr.save_settings(db, uid, {
        "name_mode": data.get("name_mode"),
        "show_times": data.get("show_times"),
        "sound_enabled": data.get("sound_enabled"),
        "auto_checkin_on_confirm": data.get("auto_checkin_on_confirm"),
        "call_banner_seconds": data.get("call_banner_seconds"),
        "clinic_name": data.get("clinic_name"),
        "ticker": ticker or [],
        "music_enabled": data.get("music_enabled"),
        "music_url": music_url,
        "music_volume": data.get("music_volume"),
    })
    await log_audit(db, user, "salle_attente_reglages", entity_type="waiting_room_settings",
                    entity_id=uid, ip=client_ip(request))
    return JSONResponse(content={"ok": True, "screen_url": "/salle-attente/ecran/%s" % settings["display_token"]})


@router.post("/reglages/logo")
async def upload_logo(
    request: Request,
    logo: UploadFile = File(...),
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Remplace le logo du cabinet affiché à côté du logo Doctivo sur l'écran."""
    uid = effective_doctor_id(user)
    content = await logo.read(MAX_LOGO_BYTES + 1)
    if not content:
        return JSONResponse(status_code=400, content={"error": "Fichier vide"})
    if len(content) > MAX_LOGO_BYTES:
        return JSONResponse(status_code=400, content={"error": "Logo trop volumineux (2 Mo maximum)"})

    ext = _sniff_image(content[:16])
    if not ext:
        return JSONResponse(status_code=400, content={"error": "Format non pris en charge (PNG, JPEG ou WEBP)"})

    os.makedirs(WR_LOGO_DIR, exist_ok=True)
    path = os.path.join(WR_LOGO_DIR, "logo_%d%s" % (uid, ext))
    with open(path, "wb") as fh:
        fh.write(content)
    # Un changement de format laisserait sinon l'ancien fichier derrière lui.
    for other in _LOGO_TYPES:
        if other != ext:
            try:
                os.remove(os.path.join(WR_LOGO_DIR, "logo_%d%s" % (uid, other)))
            except OSError:
                pass

    settings = await wr.get_settings(db, uid)      # garantit l'existence de la ligne
    version = int(time.time())
    await db.execute(
        "UPDATE waiting_room_settings SET logo_path = ?, logo_version = ?, updated_at = ? WHERE doctor_id = ?",
        (path, version, wr.now_ts(), uid),
    )
    await db.commit()
    await log_audit(db, user, "salle_attente_logo", entity_type="waiting_room_settings",
                    entity_id=uid, ip=client_ip(request))
    return JSONResponse(content={
        "ok": True, "version": version,
        "url": "/salle-attente/ecran/%s/logo?v=%d" % (settings["display_token"], version),
    })


@router.post("/reglages/logo/delete")
async def delete_logo(
    request: Request,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)
    settings = await wr.get_settings(db, uid)
    if settings.get("logo_path"):
        try:
            os.remove(settings["logo_path"])
        except OSError:
            pass
    await db.execute(
        "UPDATE waiting_room_settings SET logo_path = NULL, logo_version = 0, updated_at = ? WHERE doctor_id = ?",
        (wr.now_ts(), uid),
    )
    await db.commit()
    await log_audit(db, user, "salle_attente_logo_retire", entity_type="waiting_room_settings",
                    entity_id=uid, ip=client_ip(request))
    return JSONResponse(content={"ok": True})


@router.post("/reglages/token")
async def rotate_token(
    request: Request,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Révoque le lien de l'écran (TV changée, lien partagé par erreur)."""
    uid = effective_doctor_id(user)
    token = await wr.regenerate_token(db, uid)
    await log_audit(db, user, "salle_attente_token", entity_type="waiting_room_settings",
                    entity_id=uid, ip=client_ip(request))
    return JSONResponse(content={"ok": True, "screen_url": "/salle-attente/ecran/%s" % token})


# ---------------------------------------------------------------- écran TV

@router.get("/ecran")
async def screen_redirect(
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Raccourci authentifié vers l'URL tokenisée de l'écran."""
    settings = await wr.get_settings(db, effective_doctor_id(user))
    return RedirectResponse(url="/salle-attente/ecran/%s" % settings["display_token"], status_code=302)


@router.get("/ecran/{token}", response_class=HTMLResponse)
async def screen(request: Request, token: str, db: aiosqlite.Connection = Depends(get_db)):
    settings = await wr.settings_by_token(db, token)
    if not settings:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    data = await wr.public_board(db, settings)
    resp = templates.TemplateResponse(
        "salle_attente/ecran.html",
        {"request": request, "user": None, "token": token, "data": data, "settings": settings},
    )
    if data["music"]["enabled"]:
        resp.headers["Content-Security-Policy"] = _TV_CSP
    return resp


@router.get("/ecran/{token}/logo")
async def screen_logo(token: str, db: aiosqlite.Connection = Depends(get_db)):
    """Logo du cabinet, servi au seul porteur du jeton de l'écran.

    Le cache est agressif parce que l'URL porte toujours `?v={logo_version}` :
    remplacer le logo change l'URL, donc casse le cache de la TV."""
    settings = await wr.settings_by_token(db, token)
    path = (settings or {}).get("logo_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Aucun logo")
    ext = os.path.splitext(path)[1].lower()
    return FileResponse(
        path,
        media_type=_LOGO_TYPES.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/api/ecran/{token}")
async def screen_data(token: str, db: aiosqlite.Connection = Depends(get_db)):
    settings = await wr.settings_by_token(db, token)
    if not settings:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    return JSONResponse(content=await wr.public_board(db, settings))
