from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import io
import json
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/consultations")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DENTAL_HISTORY_PRESETS = [
    "Diabète",
    "HTA",
    "Cardiopathie",
    "Trouble de coagulation",
    "Allergie médicamenteuse",
    "Allergie au latex",
    "Hépatite",
    "VIH",
    "Grossesse",
    "Traitement anticoagulant",
    "Bisphosphonates",
    "Radiothérapie cervico-faciale",
    "Prothèse valvulaire",
    "Endocardite",
    "Autre",
]


def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip()


def _decode_vitals_notes(raw_notes: Optional[str]) -> dict:
    if not raw_notes:
        return {}
    try:
        payload = json.loads(raw_notes)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _merge_history_options(patient_history: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in patient_history + DENTAL_HISTORY_PRESETS:
        item = _clean_text(value)
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


async def _fetch_patient_history(
    db: aiosqlite.Connection,
    patient_id: Optional[int],
    doctor_id: int,
) -> list[str]:
    if not patient_id:
        return []

    cursor = await db.execute(
        "SELECT id FROM patients WHERE id = ? AND doctor_id = ? AND is_active = 1",
        (patient_id, doctor_id),
    )
    if not await cursor.fetchone():
        return []

    cursor = await db.execute(
        """SELECT type, description
           FROM medical_history
           WHERE patient_id = ? AND trim(COALESCE(description, '')) != ''
           ORDER BY date_recorded DESC, created_at DESC""",
        (patient_id,),
    )
    rows = await cursor.fetchall()

    history: list[str] = []
    seen: set[str] = set()
    type_labels = {
        "medical": "Médical",
        "surgical": "Chirurgical",
        "family": "Familial",
        "allergy": "Allergie",
    }
    for row in rows:
        desc = _clean_text(row["description"])
        if not desc:
            continue
        history_type = _clean_text(row["type"]).lower()
        if history_type == "medical":
            formatted = desc
        else:
            type_label = type_labels.get(history_type, history_type.title() if history_type else "Médical")
            formatted = f"{type_label}: {desc}"
        key = formatted.casefold()
        if key in seen:
            continue
        seen.add(key)
        history.append(formatted)

    return history


async def _save_history_item_if_new(
    db: aiosqlite.Connection,
    patient_id: Optional[int],
    entry: str,
) -> None:
    value = _clean_text(entry)
    if not patient_id or not value:
        return

    if ":" in value:
        prefix, desc = value.split(":", 1)
        desc = _clean_text(desc)
        prefix_key = _clean_text(prefix).casefold()
        history_type = {
            "médical": "medical",
            "medical": "medical",
            "chirurgical": "surgical",
            "familial": "family",
            "allergie": "allergy",
            "allergy": "allergy",
        }.get(prefix_key, "medical")
        description = desc or value
    else:
        history_type = "medical"
        description = value

    cursor = await db.execute(
        """SELECT 1 FROM medical_history
           WHERE patient_id = ? AND type = ? AND lower(trim(description)) = lower(?)
           LIMIT 1""",
        (patient_id, history_type, description),
    )
    if await cursor.fetchone():
        return

    await db.execute(
        "INSERT INTO medical_history (patient_id, type, description, date_recorded) VALUES (?, ?, ?, DATE('now'))",
        (patient_id, history_type, description),
    )


@router.get("/", response_class=HTMLResponse)
async def list_consultations(
    request: Request,
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    uid = user["sub"]
    per_page = 20
    offset = (page - 1) * per_page

    base_query = """FROM consultations c
        JOIN patients p ON c.patient_id = p.id
        JOIN users u ON c.doctor_id = u.id
        WHERE c.doctor_id = ?"""
    params: list = [uid]

    if q:
        like = f"%{q.strip().lower()}%"
        base_query += """ AND (lower(p.first_name) LIKE ? OR lower(p.last_name) LIKE ?
                          OR lower(c.reason) LIKE ? OR lower(c.diagnosis) LIKE ?)"""
        params.extend([like, like, like, like])

    if date_from:
        base_query += " AND c.consultation_date >= ?"
        params.append(date_from)

    if date_to:
        base_query += " AND c.consultation_date <= ?"
        params.append(date_to)

    count_cursor = await db.execute(f"SELECT COUNT(*) {base_query}", params)
    total_count = (await count_cursor.fetchone())[0]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    cursor = await db.execute(
        f"""SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name,
                   u.first_name || ' ' || u.last_name AS doctor_name
            {base_query} ORDER BY c.consultation_date DESC LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    )
    consultations = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/list.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultations": consultations,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
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

    uid = user["sub"]
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name",
        (uid,),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
    )
    doctors = [dict(r) for r in await cursor.fetchall()]

    patient_history = await _fetch_patient_history(db, patient_id, uid)

    return templates.TemplateResponse(
        "consultations/form.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultation": None,
            "patients": patients,
            "doctors": doctors,
            "selected_patient_id": patient_id,
            "selected_appointment_id": appointment_id,
            "dental_history_options": _merge_history_options(patient_history),
            "selected_dental_history": "",
            "selected_dental_allergies": "",
            "dental_history_presets_json": json.dumps(DENTAL_HISTORY_PRESETS, ensure_ascii=False),
            "error": None,
        },
    )


@router.get("/patient/{patient_id}/history")
async def patient_history_for_consultation(
    request: Request,
    patient_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    history = await _fetch_patient_history(db, patient_id, user["sub"])
    return JSONResponse(content={"items": history})


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
    dental_medical_history = _clean_text(form.get("dental_medical_history"))
    dental_allergies = _clean_text(form.get("dental_allergies"))

    if not patient_id or not doctor_id:
        cursor = await db.execute(
            "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name",
            (user["sub"],),
        )
        patients = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
        )
        doctors = [dict(r) for r in await cursor.fetchall()]
        patient_history = await _fetch_patient_history(db, patient_id, user["sub"])
        return templates.TemplateResponse(
            "consultations/form.html",
            {
                "request": request,
                "user": user,
                "active": "consultations",
                "consultation": None,
                "patients": patients,
                "doctors": doctors,
                "selected_patient_id": patient_id,
                "selected_appointment_id": _int("appointment_id"),
                "dental_history_options": _merge_history_options(patient_history),
                "selected_dental_history": dental_medical_history,
                "selected_dental_allergies": dental_allergies,
                "dental_history_presets_json": json.dumps(DENTAL_HISTORY_PRESETS, ensure_ascii=False),
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

    vitals_notes_payload = {}
    if dental_medical_history:
        vitals_notes_payload["dental_medical_history"] = dental_medical_history
    if dental_allergies:
        vitals_notes_payload["dental_allergies"] = dental_allergies
    vitals_notes = json.dumps(vitals_notes_payload, ensure_ascii=False) if vitals_notes_payload else None

    cursor = await db.execute(
        """INSERT INTO consultations (patient_id, doctor_id, appointment_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, appointment_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes),
    )
    consultation_id = cursor.lastrowid

    has_vitals = any(
        v is not None
        for v in [weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2]
    ) or (vitals_notes is not None)

    if has_vitals:
        await db.execute(
            """INSERT INTO vitals (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, vitals_notes),
        )

    await _save_history_item_if_new(db, patient_id, dental_medical_history)

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

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    vitals = dict(vitals_row) if vitals_row else None

    cursor = await db.execute(
        """SELECT p.*, GROUP_CONCAT(pi.medication_name || ' - ' || pi.dosage, ' | ') AS items_summary FROM prescriptions p LEFT JOIN prescription_items pi ON p.id = pi.prescription_id WHERE p.consultation_id = ? GROUP BY p.id""",
        (consultation_id,),
    )
    prescriptions = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/detail.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultation": consultation,
            "vitals": vitals,
            "prescriptions": prescriptions,
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

    selected_dental_history = ""
    selected_dental_allergies = ""

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    if vitals_row:
        vitals_data = dict(vitals_row)
        consultation.update({f"v_{k}": v for k, v in vitals_data.items()})
        notes_payload = _decode_vitals_notes(vitals_data.get("notes"))
        selected_dental_history = _clean_text(notes_payload.get("dental_medical_history"))
        selected_dental_allergies = _clean_text(notes_payload.get("dental_allergies"))

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name",
        (user["sub"],),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]

    patient_history = await _fetch_patient_history(db, consultation["patient_id"], user["sub"])

    return templates.TemplateResponse(
        "consultations/form.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultation": consultation,
            "patients": patients,
            "doctors": doctors,
            "selected_patient_id": consultation["patient_id"],
            "selected_appointment_id": consultation.get("appointment_id"),
            "dental_history_options": _merge_history_options(patient_history),
            "selected_dental_history": selected_dental_history,
            "selected_dental_allergies": selected_dental_allergies,
            "dental_history_presets_json": json.dumps(DENTAL_HISTORY_PRESETS, ensure_ascii=False),
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
    dental_medical_history = _clean_text(form.get("dental_medical_history"))
    dental_allergies = _clean_text(form.get("dental_allergies"))

    vitals_notes_payload = {}
    if dental_medical_history:
        vitals_notes_payload["dental_medical_history"] = dental_medical_history
    if dental_allergies:
        vitals_notes_payload["dental_allergies"] = dental_allergies
    vitals_notes = json.dumps(vitals_notes_payload, ensure_ascii=False) if vitals_notes_payload else None

    await db.execute(
        """UPDATE consultations SET patient_id= ?, doctor_id= ?, reason= ?, symptoms= ?, clinical_exam= ?, diagnosis= ?, treatment_plan= ?, notes= ?, updated_at=CURRENT_TIMESTAMP WHERE id= ? """,
        (patient_id, doctor_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes, consultation_id),
    )

    cursor = await db.execute("SELECT id FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    existing = await cursor.fetchone()
    if existing:
        await db.execute(
            """UPDATE vitals SET patient_id= ?, weight= ?, height= ?, blood_pressure_sys= ?, blood_pressure_dia= ?, heart_rate= ?, temperature= ?, spo2= ?, notes= ? WHERE consultation_id= ? """,
            (patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, vitals_notes, consultation_id),
        )
    elif any(v is not None for v in [weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2]) or vitals_notes is not None:
        await db.execute(
            """INSERT INTO vitals (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, vitals_notes),
        )

    await _save_history_item_if_new(db, patient_id, dental_medical_history)

    await db.commit()
    return RedirectResponse(url=f"/consultations/{consultation_id}", status_code=302)
