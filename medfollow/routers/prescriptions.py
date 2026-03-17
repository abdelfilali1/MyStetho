from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import json
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/prescriptions")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def list_prescriptions(request: Request, page: int = 1, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

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
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content=[])
    if not q or len(q.strip()) < 2:
        return JSONResponse(content=[])
    user_specialty = user.get("specialty", "") or ""
    med_filter = "dentiste" if "dent" in user_specialty.lower() else "general"
    cursor = await db.execute(
        """SELECT id, name, COALESCE(form,'') as form, COALESCE(lab,'') as lab
           FROM medications
           WHERE specialty = ? AND name LIKE ?
           ORDER BY name LIMIT 20""",
        (med_filter, f"%{q.strip()}%"),
    )
    rows = await cursor.fetchall()
    return JSONResponse(content=[dict(r) for r in rows])


@router.get("/new", response_class=HTMLResponse)
async def new_prescription_form(
    request: Request,
    patient_id: Optional[int] = None,
    consultation_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

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
async def create_prescription(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    patient_id = int(form["patient_id"])
    doctor_id = int(form["doctor_id"])
    consultation_id = form.get("consultation_id")
    consultation_id = int(consultation_id) if consultation_id else None
    notes = form.get("notes", "")
    is_renewable = form.get("is_renewable") == "on"

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
    return RedirectResponse(url=f"/prescriptions/{prescription_id}", status_code=302)


@router.get("/{prescription_id}", response_class=HTMLResponse)
async def view_prescription(request: Request, prescription_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT pr.*, p.first_name || ' ' || p.last_name AS patient_name, p.date_of_birth, p.social_security_number, u.first_name || ' ' || u.last_name AS doctor_name, u.specialty FROM prescriptions pr JOIN patients p ON pr.patient_id = p.id JOIN users u ON pr.doctor_id = u.id WHERE pr.id = ? """,
        (prescription_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/prescriptions", status_code=302)
    prescription = dict(row)

    cursor = await db.execute("SELECT * FROM prescription_items WHERE prescription_id = ? ", (prescription_id,))
    items = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "prescriptions/detail.html",
        {"request": request, "user": user, "active": "prescriptions", "prescription": prescription, "items": items},
    )


@router.get("/{prescription_id}/pdf")
async def prescription_pdf(request: Request, prescription_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from services.pdf_service import generate_prescription_pdf

    cursor = await db.execute(
        """SELECT pr.*, p.first_name AS p_first, p.last_name AS p_last, p.date_of_birth, p.social_security_number, u.first_name AS d_first, u.last_name AS d_last, u.specialty FROM prescriptions pr JOIN patients p ON pr.patient_id = p.id JOIN users u ON pr.doctor_id = u.id WHERE pr.id = ? """,
        (prescription_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/prescriptions", status_code=302)
    prescription = dict(row)

    cursor = await db.execute("SELECT * FROM prescription_items WHERE prescription_id = ? ", (prescription_id,))
    items = [dict(r) for r in await cursor.fetchall()]

    from fastapi.responses import StreamingResponse
    import io
    pdf_bytes = generate_prescription_pdf(prescription, items)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=ordonnance_{prescription_id}.pdf"},
    )


@router.get("/{prescription_id}/edit", response_class=HTMLResponse)
async def edit_prescription_form(request: Request, prescription_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    uid = user["sub"]

    cursor = await db.execute(
        """SELECT pr.* FROM prescriptions pr WHERE pr.id = ?""",
        (prescription_id,),
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
async def update_prescription(request: Request, prescription_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    patient_id = int(form["patient_id"])
    doctor_id = int(form["doctor_id"])
    consultation_id = form.get("consultation_id")
    consultation_id = int(consultation_id) if consultation_id else None
    notes = form.get("notes", "")
    is_renewable = form.get("is_renewable") == "on"

    await db.execute(
        """UPDATE prescriptions SET patient_id = ?, doctor_id = ?, consultation_id = ?, notes = ?, is_renewable = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (patient_id, doctor_id, consultation_id, notes or None, is_renewable, prescription_id),
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
    return RedirectResponse(url=f"/prescriptions/{prescription_id}", status_code=302)
