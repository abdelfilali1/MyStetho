from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import io
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/consultations")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def list_consultations(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name, u.first_name || ' ' || u.last_name AS doctor_name FROM consultations c JOIN patients p ON c.patient_id = p.id JOIN users u ON c.doctor_id = u.id ORDER BY c.consultation_date DESC LIMIT 50"""
    )
    consultations = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/list.html",
        {"request": request, "user": user, "active": "consultations", "consultations": consultations},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_consultation_form(
    request: Request,
    patient_id: Optional[int] = None,
    appointment_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name"
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
    )
    doctors = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/form.html",
        {
            "request": request, "user": user, "active": "consultations",
            "consultation": None, "patients": patients, "doctors": doctors,
            "selected_patient_id": patient_id, "selected_appointment_id": appointment_id,
            "error": None,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def create_consultation(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()

    def _int(key):
        try:
            v = form.get(key, "")
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    def _float(key):
        try:
            v = form.get(key, "")
            return float(v) if v else None
        except (ValueError, TypeError):
            return None

    patient_id = _int("patient_id")
    doctor_id = _int("doctor_id")

    if not patient_id or not doctor_id:
        cursor = await db.execute(
            "SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name"
        )
        patients = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
        )
        doctors = [dict(r) for r in await cursor.fetchall()]
        return templates.TemplateResponse(
            "consultations/form.html",
            {
                "request": request, "user": user, "active": "consultations",
                "consultation": None, "patients": patients, "doctors": doctors,
                "selected_patient_id": None, "selected_appointment_id": None,
                "error": "Veuillez sélectionner un patient et un praticien.",
            },
        )

    appointment_id = _int("appointment_id")
    reason = form.get("reason", "") or None
    symptoms = form.get("symptoms", "") or None
    clinical_exam = form.get("clinical_exam", "") or None
    diagnosis = form.get("diagnosis", "") or None
    treatment_plan = form.get("treatment_plan", "") or None
    notes = form.get("notes", "") or None
    weight = _float("weight")
    height = _float("height")
    blood_pressure_sys = _int("blood_pressure_sys")
    blood_pressure_dia = _int("blood_pressure_dia")
    heart_rate = _int("heart_rate")
    temperature = _float("temperature")
    spo2 = _float("spo2")

    cursor = await db.execute(
        """INSERT INTO consultations (patient_id, doctor_id, appointment_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, appointment_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes),
    )
    consultation_id = cursor.lastrowid

    has_vitals = any(
        v is not None
        for v in [weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2]
    )
    if has_vitals:
        await db.execute(
            """INSERT INTO vitals (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2),
        )

    if appointment_id:
        await db.execute(
            "UPDATE appointments SET status = 'termine', updated_at = CURRENT_TIMESTAMP WHERE id = ? ",
            (appointment_id,),
        )

    await db.commit()
    return RedirectResponse(url=f"/consultations/{consultation_id}", status_code=302)


@router.get("/{consultation_id}", response_class=HTMLResponse)
async def view_consultation(request: Request, consultation_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name, p.date_of_birth, p.gender, p.id AS pid, u.first_name || ' ' || u.last_name AS doctor_name FROM consultations c JOIN patients p ON c.patient_id = p.id JOIN users u ON c.doctor_id = u.id WHERE c.id = ? """,
        (consultation_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/consultations", status_code=302)
    consultation = dict(row)

    # Vitals
    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    vitals = dict(vitals_row) if vitals_row else None

    # Prescriptions for this consultation
    cursor = await db.execute(
        """SELECT p.*, GROUP_CONCAT(pi.medication_name || ' - ' || pi.dosage, ' | ') AS items_summary FROM prescriptions p LEFT JOIN prescription_items pi ON p.id = pi.prescription_id WHERE p.consultation_id = ? GROUP BY p.id""",
        (consultation_id,),
    )
    prescriptions = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/detail.html",
        {
            "request": request, "user": user, "active": "consultations",
            "consultation": consultation, "vitals": vitals, "prescriptions": prescriptions,
        },
    )


@router.get("/{consultation_id}/pdf")
async def consultation_pdf(request: Request, consultation_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name, p.date_of_birth, p.gender, u.first_name || ' ' || u.last_name AS doctor_name FROM consultations c JOIN patients p ON c.patient_id = p.id JOIN users u ON c.doctor_id = u.id WHERE c.id = ? """,
        (consultation_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/consultations", status_code=302)
    consultation = dict(row)

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    vitals = dict(vitals_row) if vitals_row else None

    from services.pdf_service import generate_consultation_pdf

    pdf_bytes = generate_consultation_pdf(consultation, vitals)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=consultation_{consultation_id}.pdf"},
    )


@router.get("/{consultation_id}/edit", response_class=HTMLResponse)
async def edit_consultation_form(request: Request, consultation_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT * FROM consultations WHERE id = ? ", (consultation_id,))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/consultations", status_code=302)
    consultation = dict(row)

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    if vitals_row:
        consultation.update({f"v_{k}": v for k, v in dict(vitals_row).items()})

    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name")
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/form.html",
        {
            "request": request, "user": user, "active": "consultations",
            "consultation": consultation, "patients": patients, "doctors": doctors,
            "selected_patient_id": consultation["patient_id"],
            "selected_appointment_id": consultation.get("appointment_id"),
            "error": None,
        },
    )


@router.post("/{consultation_id}/edit")
async def update_consultation(
    request: Request,
    consultation_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()

    def _int(key):
        try:
            v = form.get(key, "")
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    def _float(key):
        try:
            v = form.get(key, "")
            return float(v) if v else None
        except (ValueError, TypeError):
            return None

    patient_id = _int("patient_id")
    doctor_id = _int("doctor_id")
    reason = form.get("reason", "") or None
    symptoms = form.get("symptoms", "") or None
    clinical_exam = form.get("clinical_exam", "") or None
    diagnosis = form.get("diagnosis", "") or None
    treatment_plan = form.get("treatment_plan", "") or None
    notes = form.get("notes", "") or None
    weight = _float("weight")
    height = _float("height")
    blood_pressure_sys = _int("blood_pressure_sys")
    blood_pressure_dia = _int("blood_pressure_dia")
    heart_rate = _int("heart_rate")
    temperature = _float("temperature")
    spo2 = _float("spo2")

    await db.execute(
        """UPDATE consultations SET patient_id= ?, doctor_id= ?, reason= ?, symptoms= ?, clinical_exam= ?, diagnosis= ?, treatment_plan= ?, notes= ?, updated_at=CURRENT_TIMESTAMP WHERE id= ? """,
        (patient_id, doctor_id, reason, symptoms, clinical_exam,
         diagnosis, treatment_plan, notes, consultation_id),
    )

    cursor = await db.execute("SELECT id FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    existing = await cursor.fetchone()
    if existing:
        await db.execute(
            """UPDATE vitals SET weight= ?, height= ?, blood_pressure_sys= ?, blood_pressure_dia= ?, heart_rate= ?, temperature= ?, spo2= ? WHERE consultation_id= ? """,
            (weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, consultation_id),
        )
    elif any(v is not None for v in [weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2]):
        await db.execute(
            """INSERT INTO vitals (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2),
        )

    await db.commit()
    return RedirectResponse(url=f"/consultations/{consultation_id}", status_code=302)
