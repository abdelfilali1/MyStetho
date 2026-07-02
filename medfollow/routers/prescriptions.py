from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import json
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api, deny_secretaire
from services.audit import log_audit, client_ip
from services.flash import set_flash

router = APIRouter(prefix="/prescriptions", dependencies=[Depends(deny_secretaire)])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def list_prescriptions(request: Request, page: int = 1, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    uid = user["sub"]
    per_page = 20
    offset = (page - 1) * per_page

    count_cursor = await db.execute(
        "SELECT COUNT(*) FROM prescriptions WHERE doctor_id = ?", (uid,)
    )
    total_count = (await count_cursor.fetchone())[0]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    cursor = await db.execute(
        """SELECT pr.*, p.first_name || ' ' || p.last_name AS patient_name, u.first_name || ' ' || u.last_name AS doctor_name, COUNT(pi.id) AS item_count FROM prescriptions pr JOIN patients p ON pr.patient_id = p.id JOIN users u ON pr.doctor_id = u.id LEFT JOIN prescription_items pi ON pr.id = pi.prescription_id WHERE pr.doctor_id = ? GROUP BY pr.id ORDER BY pr.prescription_date DESC LIMIT ? OFFSET ?""",
        (uid, per_page, offset),
    )
    prescriptions = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "prescriptions/list.html",
        {
            "request": request, "user": user, "active": "prescriptions",
            "prescriptions": prescriptions,
            "page": page, "total_pages": total_pages, "total_count": total_count,
        },
    )


@router.get("/medications/search")
async def search_medications(
    request: Request,
    q: str = "",
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    if not q or len(q.strip()) < 1:
        return JSONResponse(content=[])
    term = q.strip().lower()
    cursor = await db.execute(
        """SELECT id, name, COALESCE(form,'') as form, COALESCE(lab,'') as lab,
                  CASE WHEN LOWER(name) LIKE ? THEN 0 ELSE 1 END as starts_rank
           FROM medications
           WHERE LOWER(name) LIKE ?
           ORDER BY starts_rank, name
           LIMIT 100""",
        (f"{term}%", f"%{term}%"),
    )
    rows = await cursor.fetchall()
    return JSONResponse(
        content=[dict(r) for r in rows],
        headers={"Cache-Control": "no-store"},
    )


# NB : déclarée AVANT GET /{prescription_id} pour éviter tout conflit de routage.
@router.get("/patient/{patient_id}/alerts")
async def patient_prescription_alerts(
    request: Request,
    patient_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Alertes de sécurité (allergies, grossesse, allaitement) affichées au moment de prescrire."""
    cursor = await db.execute(
        "SELECT gender, pregnant, breastfeeding FROM patients WHERE id = ? AND doctor_id = ?",
        (patient_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})
    patient = dict(row)

    cursor = await db.execute(
        "SELECT description FROM medical_history WHERE patient_id = ? AND type = 'allergy' ORDER BY date_recorded DESC, created_at DESC",
        (patient_id,),
    )
    seen, allergies = set(), []
    for r in await cursor.fetchall():
        desc = (r["description"] or "").strip()
        low = desc.lower()
        for pref in ("allergie:", "allergie :", "allergy:", "allergy :"):
            if low.startswith(pref):
                desc = desc[len(pref):].strip()
                break
        if desc and desc.lower() not in seen:
            seen.add(desc.lower())
            allergies.append(desc)

    return JSONResponse(
        content={
            "allergies": allergies,
            "pregnant": bool(patient.get("pregnant")),
            "breastfeeding": bool(patient.get("breastfeeding")),
            "gender": patient.get("gender"),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_prescription_form(
    request: Request,
    patient_id: Optional[int] = None,
    consultation_id: Optional[int] = None,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = user["sub"]
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name", (uid,)
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]

    # Filter medications by specialty: dentists get dental meds, others get general
    user_specialty = user.get("specialty", "") or ""
    if "dent" in user_specialty.lower():
        med_filter = "dentiste"
    else:
        med_filter = "general"
    cursor = await db.execute(
        "SELECT id, name, common_dosages FROM medications WHERE specialty = ? ORDER BY name", (med_filter,)
    )
    medications = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "prescriptions/form.html",
        {
            "request": request, "user": user, "active": "prescriptions",
            "patients": patients, "doctors": doctors, "medications": medications,
            "selected_patient_id": patient_id, "selected_consultation_id": consultation_id,
            "error": None,
        },
    )


@router.post("/new")
async def create_prescription(request: Request, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    form = await request.form()
    patient_id = int(form["patient_id"])
    doctor_id = int(form["doctor_id"])
    consultation_id = form.get("consultation_id")
    consultation_id = int(consultation_id) if consultation_id else None
    notes = form.get("notes", "")
    is_renewable = form.get("is_renewable") == "on"

    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cur.fetchone():
        return RedirectResponse(url="/prescriptions", status_code=302)
    doctor_id = user["sub"]

    cursor = await db.execute(
        """INSERT INTO prescriptions (patient_id, doctor_id, consultation_id, notes, is_renewable) VALUES (?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, consultation_id, notes or None, is_renewable),
    )
    prescription_id = cursor.lastrowid

    # Parse medication items from form
    idx = 0
    while f"med_name_{idx}" in form:
        med_name = form[f"med_name_{idx}"]
        if med_name.strip():
            dosage = form.get(f"med_dosage_{idx}", "")
            frequency = form.get(f"med_frequency_{idx}", "")
            duration = form.get(f"med_duration_{idx}", "")
            instructions = form.get(f"med_instructions_{idx}", "")
            quantity = form.get(f"med_quantity_{idx}", "")

            await db.execute(
                """INSERT INTO prescription_items (prescription_id, medication_name, dosage, frequency, duration, instructions, quantity) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (prescription_id, med_name, dosage or "À définir", frequency or "À définir",
                 duration or None, instructions or None, int(quantity) if quantity else None),
            )
        idx += 1

    await db.commit()
    await log_audit(db, user, "ordonnance_creee", entity_type="prescription", entity_id=prescription_id, patient_id=patient_id, ip=client_ip(request))
    response = RedirectResponse(url=f"/prescriptions/{prescription_id}", status_code=302)
    set_flash(response, "Ordonnance créée")
    return response


@router.get("/{prescription_id}", response_class=HTMLResponse)
async def view_prescription(request: Request, prescription_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        """SELECT pr.*, p.first_name || ' ' || p.last_name AS patient_name, p.date_of_birth, p.social_security_number, u.first_name || ' ' || u.last_name AS doctor_name, u.specialty FROM prescriptions pr JOIN patients p ON pr.patient_id = p.id JOIN users u ON pr.doctor_id = u.id WHERE pr.id = ? AND pr.doctor_id = ? """,
        (prescription_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/prescriptions", status_code=302)
    prescription = dict(row)

    cursor = await db.execute("SELECT * FROM prescription_items WHERE prescription_id = ? ", (prescription_id,))
    items = [dict(r) for r in await cursor.fetchall()]

    await log_audit(db, user, "ordonnance_consultee", entity_type="prescription", entity_id=prescription_id, patient_id=prescription["patient_id"], ip=client_ip(request))

    return templates.TemplateResponse(
        "prescriptions/detail.html",
        {"request": request, "user": user, "active": "prescriptions", "prescription": prescription, "items": items},
    )


@router.get("/{prescription_id}/pdf")
async def prescription_pdf(request: Request, prescription_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    from services.pdf_service import generate_prescription_pdf

    cursor = await db.execute(
        """SELECT pr.*, p.first_name AS p_first, p.last_name AS p_last, p.date_of_birth, p.social_security_number, u.first_name AS d_first, u.last_name AS d_last, u.specialty, u.pdf_template_path FROM prescriptions pr JOIN patients p ON pr.patient_id = p.id JOIN users u ON pr.doctor_id = u.id WHERE pr.id = ? AND pr.doctor_id = ? """,
        (prescription_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/prescriptions", status_code=302)
    prescription = dict(row)

    cursor = await db.execute("SELECT * FROM prescription_items WHERE prescription_id = ? ", (prescription_id,))
    items = [dict(r) for r in await cursor.fetchall()]

    # Allergies du patient (sécurité) — affichées sur l'ordonnance.
    cursor = await db.execute(
        "SELECT description FROM medical_history WHERE patient_id = ? AND type = 'allergy' ORDER BY date_recorded DESC, created_at DESC",
        (prescription["patient_id"],),
    )
    seen, allergy_list = set(), []
    for r in await cursor.fetchall():
        desc = (r["description"] or "").strip()
        low = desc.lower()
        for pref in ("allergie:", "allergie :", "allergy:", "allergy :"):
            if low.startswith(pref):
                desc = desc[len(pref):].strip()
                break
        if desc and desc.lower() not in seen:
            seen.add(desc.lower())
            allergy_list.append(desc)
    allergies = ", ".join(allergy_list)

    from fastapi.responses import StreamingResponse
    import io
    pdf_bytes = generate_prescription_pdf(prescription, items, prescription.get("pdf_template_path"), allergies)
    await log_audit(db, user, "ordonnance_pdf_exportee", entity_type="prescription", entity_id=prescription_id, patient_id=prescription["patient_id"], ip=client_ip(request))
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=ordonnance_{prescription_id}.pdf"},
    )


@router.get("/{prescription_id}/edit", response_class=HTMLResponse)
async def edit_prescription_form(request: Request, prescription_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    uid = user["sub"]

    cursor = await db.execute(
        """SELECT pr.* FROM prescriptions pr WHERE pr.id = ? AND pr.doctor_id = ?""",
        (prescription_id, uid),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/prescriptions", status_code=302)
    prescription = dict(row)

    cursor = await db.execute("SELECT * FROM prescription_items WHERE prescription_id = ?", (prescription_id,))
    items = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name", (uid,)
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]

    user_specialty = user.get("specialty", "") or ""
    if "dent" in user_specialty.lower():
        med_filter = "dentiste"
    else:
        med_filter = "general"
    cursor = await db.execute(
        "SELECT id, name, common_dosages FROM medications WHERE specialty = ? ORDER BY name", (med_filter,)
    )
    medications = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "prescriptions/form.html",
        {
            "request": request, "user": user, "active": "prescriptions",
            "patients": patients, "doctors": doctors, "medications": medications,
            "prescription": prescription, "items": items,
            "selected_patient_id": prescription["patient_id"],
            "selected_consultation_id": prescription.get("consultation_id"),
            "error": None,
        },
    )


@router.post("/{prescription_id}/edit")
async def update_prescription(request: Request, prescription_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    uid = user["sub"]
    cursor = await db.execute("SELECT 1 FROM prescriptions WHERE id = ? AND doctor_id = ?", (prescription_id, uid))
    if not await cursor.fetchone():
        return RedirectResponse(url="/prescriptions", status_code=302)

    form = await request.form()
    patient_id = int(form["patient_id"])
    doctor_id = int(form["doctor_id"])
    consultation_id = form.get("consultation_id")
    consultation_id = int(consultation_id) if consultation_id else None
    notes = form.get("notes", "")
    is_renewable = form.get("is_renewable") == "on"

    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, uid))
    if not await cur.fetchone():
        return RedirectResponse(url="/prescriptions", status_code=302)
    doctor_id = uid

    await db.execute(
        """UPDATE prescriptions SET patient_id = ?, doctor_id = ?, consultation_id = ?, notes = ?, is_renewable = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND doctor_id = ?""",
        (patient_id, doctor_id, consultation_id, notes or None, is_renewable, prescription_id, uid),
    )

    # Delete old items and insert new ones
    await db.execute("DELETE FROM prescription_items WHERE prescription_id = ?", (prescription_id,))

    idx = 0
    while f"med_name_{idx}" in form:
        med_name = form[f"med_name_{idx}"]
        if med_name.strip():
            dosage = form.get(f"med_dosage_{idx}", "")
            frequency = form.get(f"med_frequency_{idx}", "")
            duration = form.get(f"med_duration_{idx}", "")
            instructions = form.get(f"med_instructions_{idx}", "")
            quantity = form.get(f"med_quantity_{idx}", "")

            await db.execute(
                """INSERT INTO prescription_items (prescription_id, medication_name, dosage, frequency, duration, instructions, quantity) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (prescription_id, med_name, dosage or "À définir", frequency or "À définir",
                 duration or None, instructions or None, int(quantity) if quantity else None),
            )
        idx += 1

    await db.commit()
    await log_audit(db, user, "ordonnance_modifiee", entity_type="prescription", entity_id=prescription_id, patient_id=patient_id, ip=client_ip(request))
    response = RedirectResponse(url=f"/prescriptions/{prescription_id}", status_code=302)
    set_flash(response, "Ordonnance modifiée")
    return response
