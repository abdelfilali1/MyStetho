"""Module Rappels — recall patients (détartrage 6 mois, contrôle annuel,
suites de plan de traitement). Levier de remplissage du cabinet.

Table `rappels` : description, due_date, status ('a_contacter'|'contacte'),
is_closed, notes. Cloisonné par praticien (effective_doctor_id : une secrétaire
gère les rappels de son médecin lié)."""
from datetime import date

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, effective_doctor_id, set_flash
from services.audit import log_audit, client_ip
from services import whatsapp_service

router = APIRouter(prefix="/rappels")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def _owns_rappel(db, rappel_id: int, doctor_id: int) -> bool:
    cur = await db.execute("SELECT 1 FROM rappels WHERE id = ? AND doctor_id = ?", (rappel_id, doctor_id))
    return await cur.fetchone() is not None


@router.get("/", response_class=HTMLResponse)
async def list_rappels(request: Request, filtre: str = "a_contacter", user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    did = effective_doctor_id(user)
    today = date.today().isoformat()
    month_prefix = today[:7]

    where = "r.doctor_id = ?"
    params = [did]
    if filtre == "a_contacter":
        where += " AND r.is_closed = 0 AND r.status = 'a_contacter'"
    elif filtre == "contacte":
        where += " AND r.is_closed = 0 AND r.status = 'contacte'"
    elif filtre == "clotures":
        where += " AND r.is_closed = 1"
    elif filtre == "ce_mois":
        where += " AND r.is_closed = 0 AND r.due_date IS NOT NULL AND substr(r.due_date, 1, 7) = ?"
        params.append(month_prefix)
    # 'tous' → aucune restriction supplémentaire

    cursor = await db.execute(
        f"""SELECT r.*, p.first_name || ' ' || p.last_name AS patient_name, p.phone AS patient_phone
            FROM rappels r JOIN patients p ON r.patient_id = p.id
            WHERE {where}
            ORDER BY (r.due_date IS NULL), r.due_date ASC, r.created_at DESC""",
        params,
    )
    rappels = [dict(r) for r in await cursor.fetchall()]

    # Statistiques (chips)
    cur = await db.execute(
        "SELECT COUNT(*) FROM rappels WHERE doctor_id = ? AND is_closed = 0 AND status = 'a_contacter'", (did,)
    )
    nb_a_contacter = (await cur.fetchone())[0]
    cur = await db.execute(
        "SELECT COUNT(*) FROM rappels WHERE doctor_id = ? AND is_closed = 0 AND status = 'a_contacter' AND due_date IS NOT NULL AND due_date < ?",
        (did, today),
    )
    nb_en_retard = (await cur.fetchone())[0]
    cur = await db.execute(
        "SELECT COUNT(*) FROM rappels WHERE doctor_id = ? AND is_closed = 0 AND due_date IS NOT NULL AND substr(due_date, 1, 7) = ?",
        (did, month_prefix),
    )
    nb_ce_mois = (await cur.fetchone())[0]

    # Patients pour le formulaire de création
    cur = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name, first_name",
        (did,),
    )
    patients = [dict(r) for r in await cur.fetchall()]

    # Le bouton « Envoyer WhatsApp » n'apparaît que si le praticien a activé le service.
    cur = await db.execute("SELECT COALESCE(whatsapp_enabled, 1) FROM users WHERE id = ?", (did,))
    row = await cur.fetchone()
    wa_enabled = bool(row[0]) if row else True

    return templates.TemplateResponse(
        "rappels/index.html",
        {
            "request": request, "user": user, "active": "rappels",
            "rappels": rappels, "filtre": filtre, "patients": patients,
            "today": today, "whatsapp_enabled": wa_enabled,
            "nb_a_contacter": nb_a_contacter, "nb_en_retard": nb_en_retard, "nb_ce_mois": nb_ce_mois,
        },
    )


@router.post("/new")
async def create_rappel(
    request: Request,
    patient_id: int = Form(...),
    description: str = Form(...),
    due_date: str = Form(""),
    notes: str = Form(""),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    did = effective_doctor_id(user)
    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, did))
    if not await cur.fetchone():
        return RedirectResponse(url="/rappels", status_code=302)
    if not description.strip():
        resp = RedirectResponse(url="/rappels", status_code=302)
        set_flash(resp, "La description est obligatoire", "error")
        return resp

    cur = await db.execute(
        "INSERT INTO rappels (patient_id, doctor_id, description, due_date, notes) VALUES (?, ?, ?, ?, ?)",
        (patient_id, did, description.strip(), due_date or None, notes.strip() or None),
    )
    await db.commit()
    await log_audit(db, user, "rappel_cree", entity_type="rappel", entity_id=cur.lastrowid, patient_id=patient_id, ip=client_ip(request))
    resp = RedirectResponse(url="/rappels", status_code=302)
    set_flash(resp, "Rappel créé")
    return resp


@router.post("/{rappel_id}/status")
async def set_status(
    request: Request, rappel_id: int, status: str = Form(...),
    user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db),
):
    did = effective_doctor_id(user)
    if not await _owns_rappel(db, rappel_id, did):
        return RedirectResponse(url="/rappels", status_code=302)
    new_status = "contacte" if status == "contacte" else "a_contacter"
    await db.execute(
        "UPDATE rappels SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, rappel_id),
    )
    await db.commit()
    await log_audit(db, user, "rappel_contacte", entity_type="rappel", entity_id=rappel_id, ip=client_ip(request), details=f"status={new_status}")
    resp = RedirectResponse(url="/rappels", status_code=302)
    set_flash(resp, "Marqué comme contacté" if new_status == "contacte" else "Marqué à contacter")
    return resp


@router.post("/{rappel_id}/whatsapp")
async def send_whatsapp(
    request: Request, rappel_id: int,
    user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db),
):
    """Envoie un rappel de soin au patient par WhatsApp (via DoctivoAssist) et
    marque le rappel comme contacté."""
    did = effective_doctor_id(user)
    if not await _owns_rappel(db, rappel_id, did):
        return RedirectResponse(url="/rappels", status_code=302)

    status = await whatsapp_service.send_rappel_by_id(rappel_id)
    # (message, est_erreur)
    outcomes = {
        "sent": ("Rappel WhatsApp envoyé au patient", False),
        "unconfigured": ("WhatsApp n'est pas encore configuré sur le serveur — aucun message envoyé", True),
        "skipped": ("Envoi impossible : numéro manquant, patient désinscrit, ou service WhatsApp désactivé", True),
        "failed": ("Échec de l'envoi WhatsApp — réessayez plus tard", True),
    }
    msg, is_error = outcomes.get(status, ("Envoi WhatsApp effectué", False))
    await log_audit(db, user, "rappel_whatsapp", entity_type="rappel", entity_id=rappel_id,
                    ip=client_ip(request), details=f"status={status}")
    resp = RedirectResponse(url="/rappels", status_code=302)
    if is_error:
        set_flash(resp, msg, "error")
    else:
        set_flash(resp, msg)
    return resp


@router.post("/{rappel_id}/close")
async def close_rappel(request: Request, rappel_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    did = effective_doctor_id(user)
    if not await _owns_rappel(db, rappel_id, did):
        return RedirectResponse(url="/rappels", status_code=302)
    await db.execute("UPDATE rappels SET is_closed = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (rappel_id,))
    await db.commit()
    await log_audit(db, user, "rappel_cloture", entity_type="rappel", entity_id=rappel_id, ip=client_ip(request))
    resp = RedirectResponse(url="/rappels", status_code=302)
    set_flash(resp, "Rappel clôturé")
    return resp


@router.post("/{rappel_id}/reopen")
async def reopen_rappel(request: Request, rappel_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    did = effective_doctor_id(user)
    if not await _owns_rappel(db, rappel_id, did):
        return RedirectResponse(url="/rappels", status_code=302)
    await db.execute("UPDATE rappels SET is_closed = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (rappel_id,))
    await db.commit()
    resp = RedirectResponse(url="/rappels?filtre=clotures", status_code=302)
    set_flash(resp, "Rappel rouvert")
    return resp


@router.post("/{rappel_id}/delete")
async def delete_rappel(request: Request, rappel_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    did = effective_doctor_id(user)
    if not await _owns_rappel(db, rappel_id, did):
        return RedirectResponse(url="/rappels", status_code=302)
    await db.execute("DELETE FROM rappels WHERE id = ?", (rappel_id,))
    await db.commit()
    await log_audit(db, user, "rappel_supprime", entity_type="rappel", entity_id=rappel_id, ip=client_ip(request))
    resp = RedirectResponse(url="/rappels", status_code=302)
    set_flash(resp, "Rappel supprimé")
    return resp
