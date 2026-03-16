from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/patients")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise Exception("Not authenticated")
    return user


@router.get("/", response_class=HTMLResponse)
async def list_patients(
    request: Request,
    q: str = "",
    page: int = 1,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    per_page = 20
    offset = (page - 1) * per_page

    if q:
        like = f"%{q.lower()}%"
        count_cursor = await db.execute(
            """SELECT COUNT(*) FROM patients WHERE doctor_id = ? AND is_active = 1 AND (lower(first_name) LIKE ? OR lower(last_name) LIKE ? OR phone LIKE ? OR social_security_number LIKE ?)""",
            (user["sub"], like, like, f"%{q}%", f"%{q}%"),
        )
        total_count = (await count_cursor.fetchone())[0]

        cursor = await db.execute(
            """SELECT * FROM patients WHERE doctor_id = ? AND is_active = 1 AND (lower(first_name) LIKE ? OR lower(last_name) LIKE ? OR phone LIKE ? OR social_security_number LIKE ?) ORDER BY last_name, first_name LIMIT ? OFFSET ?""",
            (user["sub"], like, like, f"%{q}%", f"%{q}%", per_page, offset),
        )
    else:
        count_cursor = await db.execute(
            "SELECT COUNT(*) FROM patients WHERE doctor_id = ? AND is_active = 1",
            (user["sub"],),
        )
        total_count = (await count_cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT * FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name, first_name LIMIT ? OFFSET ?",
            (user["sub"], per_page, offset),
        )

    rows = await cursor.fetchall()
    patients = [dict(row) for row in rows]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return templates.TemplateResponse(
        "patients/list.html",
        {
            "request": request, "user": user, "active": "patients",
            "patients": patients, "search": q,
            "page": page, "total_pages": total_pages, "total_count": total_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_patient_form(request: Request, next: str = ""):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "patients/form.html",
        {"request": request, "user": user, "active": "patients", "patient": None, "error": None, "next": next},
    )


@router.post("/quick")
async def quick_create_patient(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    cursor = await db.execute(
        "INSERT INTO patients (doctor_id, first_name, last_name, date_of_birth) VALUES (?, ?, ?, ?)",
        (user["sub"], first_name.strip(), last_name.strip(), date_of_birth),
    )
    await db.commit()
    return JSONResponse(content={"id": cursor.lastrowid, "name": f"{last_name.upper()} {first_name}"})


@router.post("/new", response_class=HTMLResponse)
async def create_patient(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(...),
    gender: str = Form(""),
    social_security_number: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    postal_code: str = Form(""),
    blood_type: str = Form(""),
    referring_doctor: str = Form(""),
    insurance_name: str = Form(""),
    insurance_number: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    notes: str = Form(""),
    next_url: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        cur = await db.execute(
            """INSERT INTO patients (doctor_id, first_name, last_name, date_of_birth, gender, social_security_number, email, phone, address, city, postal_code, blood_type, referring_doctor, insurance_name, insurance_number, emergency_contact_name, emergency_contact_phone, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user["sub"],
                first_name, last_name, date_of_birth,
                gender or None, social_security_number or None,
                email or None, phone or None, address or None,
                city or None, postal_code or None, blood_type or None,
                referring_doctor or None, insurance_name or None, insurance_number or None,
                emergency_contact_name or None, emergency_contact_phone or None, notes or None,
            ),
        )
        await db.commit()
        new_id = cur.lastrowid
        if next_url:
            sep = "&" if "?" in next_url else "?"
            return RedirectResponse(url=f"{next_url}{sep}patient_id={new_id}", status_code=302)
        return RedirectResponse(url=f"/patients/{new_id}", status_code=302)
    except Exception as e:
        error = "Ce numéro de sécurité sociale existe déjà." if "UNIQUE" in str(e) else str(e)
        patient_data = {
            "first_name": first_name, "last_name": last_name, "date_of_birth": date_of_birth,
            "gender": gender, "social_security_number": social_security_number,
            "email": email, "phone": phone, "address": address, "city": city,
            "postal_code": postal_code, "blood_type": blood_type,
            "referring_doctor": referring_doctor, "insurance_name": insurance_name,
            "insurance_number": insurance_number, "emergency_contact_name": emergency_contact_name,
            "emergency_contact_phone": emergency_contact_phone, "notes": notes,
        }
        return templates.TemplateResponse(
            "patients/form.html",
            {"request": request, "user": user, "active": "patients", "patient": patient_data, "error": error},
        )


@router.get("/{patient_id}", response_class=HTMLResponse)
async def view_patient(request: Request, patient_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/patients", status_code=302)
    patient = dict(row)

    # Medical history
    cursor = await db.execute(
        "SELECT * FROM medical_history WHERE patient_id = ? ORDER BY date_recorded DESC", (patient_id,)
    )
    history = [dict(r) for r in await cursor.fetchall()]

    # Recent appointments
    cursor = await db.execute(
        "SELECT * FROM appointments WHERE patient_id = ? ORDER BY start_datetime DESC LIMIT 10", (patient_id,)
    )
    appointments = [dict(r) for r in await cursor.fetchall()]

    # Recent consultations
    cursor = await db.execute(
        "SELECT * FROM consultations WHERE patient_id = ? ORDER BY consultation_date DESC LIMIT 10", (patient_id,)
    )
    consultations = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "patients/detail.html",
        {
            "request": request, "user": user, "active": "patients",
            "patient": patient, "history": history,
            "appointments": appointments, "consultations": consultations,
        },
    )


@router.get("/{patient_id}/edit", response_class=HTMLResponse)
async def edit_patient_form(request: Request, patient_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/patients", status_code=302)

    return templates.TemplateResponse(
        "patients/form.html",
        {"request": request, "user": user, "active": "patients", "patient": dict(row), "error": None},
    )


@router.post("/{patient_id}/edit", response_class=HTMLResponse)
async def update_patient(
    request: Request,
    patient_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(...),
    gender: str = Form(""),
    social_security_number: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    postal_code: str = Form(""),
    blood_type: str = Form(""),
    referring_doctor: str = Form(""),
    insurance_name: str = Form(""),
    insurance_number: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    notes: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        await db.execute(
            """UPDATE patients SET first_name= ?, last_name= ?, date_of_birth= ?, gender= ?, social_security_number= ?, email= ?, phone= ?, address= ?, city= ?, postal_code= ?, blood_type= ?, referring_doctor= ?, insurance_name= ?, insurance_number= ?, emergency_contact_name= ?, emergency_contact_phone= ?, notes= ?, updated_at=CURRENT_TIMESTAMP WHERE id= ? AND doctor_id= ?""",
            (
                first_name, last_name, date_of_birth,
                gender or None, social_security_number or None,
                email or None, phone or None, address or None,
                city or None, postal_code or None, blood_type or None,
                referring_doctor or None, insurance_name or None, insurance_number or None,
                emergency_contact_name or None, emergency_contact_phone or None, notes or None,
                patient_id, user["sub"],
            ),
        )
        await db.commit()
        return RedirectResponse(url=f"/patients/{patient_id}", status_code=302)
    except Exception as e:
        error = "Ce numéro de sécurité sociale existe déjà." if "UNIQUE" in str(e) else str(e)
        patient_data = {"id": patient_id, "first_name": first_name, "last_name": last_name,
                        "date_of_birth": date_of_birth, "gender": gender,
                        "social_security_number": social_security_number,
                        "email": email, "phone": phone, "address": address, "city": city,
                        "postal_code": postal_code, "blood_type": blood_type,
                        "referring_doctor": referring_doctor, "insurance_name": insurance_name,
                        "insurance_number": insurance_number,
                        "emergency_contact_name": emergency_contact_name,
                        "emergency_contact_phone": emergency_contact_phone, "notes": notes}
        return templates.TemplateResponse(
            "patients/form.html",
            {"request": request, "user": user, "active": "patients", "patient": patient_data, "error": error},
        )


@router.post("/{patient_id}/delete")
async def delete_patient(request: Request, patient_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Soft delete
    await db.execute("UPDATE patients SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    await db.commit()
    return RedirectResponse(url="/patients", status_code=302)


@router.post("/{patient_id}/history", response_class=HTMLResponse)
async def add_history(
    request: Request,
    patient_id: int,
    type: str = Form(...),
    description: str = Form(...),
    date_recorded: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    await db.execute(
        "INSERT INTO medical_history (patient_id, type, description, date_recorded) VALUES (?, ?, ?, ?)",
        (patient_id, type, description, date_recorded or None),
    )
    await db.commit()
    return RedirectResponse(url=f"/patients/{patient_id}", status_code=302)
