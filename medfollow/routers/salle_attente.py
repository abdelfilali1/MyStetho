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
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api, effective_doctor_id
from services.audit import log_audit, client_ip
from services import waiting_room as wr

router = APIRouter(prefix="/salle-attente")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


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
    settings = await wr.save_settings(db, uid, {
        "name_mode": data.get("name_mode"),
        "show_times": data.get("show_times"),
        "sound_enabled": data.get("sound_enabled"),
        "auto_checkin_on_confirm": data.get("auto_checkin_on_confirm"),
        "call_banner_seconds": data.get("call_banner_seconds"),
        "clinic_name": data.get("clinic_name"),
        "ticker": ticker or [],
    })
    await log_audit(db, user, "salle_attente_reglages", entity_type="waiting_room_settings",
                    entity_id=uid, ip=client_ip(request))
    return JSONResponse(content={"ok": True, "screen_url": "/salle-attente/ecran/%s" % settings["display_token"]})


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
    return templates.TemplateResponse(
        "salle_attente/ecran.html",
        {"request": request, "user": None, "token": token, "data": data, "settings": settings},
    )


@router.get("/api/ecran/{token}")
async def screen_data(token: str, db: aiosqlite.Connection = Depends(get_db)):
    settings = await wr.settings_by_token(db, token)
    if not settings:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    return JSONResponse(content=await wr.public_board(db, settings))
