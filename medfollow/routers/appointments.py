from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import date, datetime
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/appointments")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def agenda(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    uid = user["sub"]

    # Get all patients for the new appointment form
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name", (uid,)
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    # Get all doctors
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
    )
    doctors = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "appointments/index.html",
        {"request": request, "user": user, "active": "appointments", "patients": patients, "doctors": doctors},
    )


@router.get("/api/events")
async def get_events(
    request: Request,
    start: str = "",
    end: str = "",
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return appointments as JSON for the calendar."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    uid = user["sub"]
    query = """ SELECT a.*, p.first_name || ' ' || p.last_name AS patient_name FROM appointments a JOIN patients p ON a.patient_id = p.id WHERE a.doctor_id = ? """
    params = [uid]

    if start and end:
        query += " AND a.start_datetime >= ? AND a.start_datetime <= ? "
        params += [start, end]

    query += " ORDER BY a.start_datetime"
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    colors = {
        "consultation": "#2563eb",
        "suivi": "#059669",
        "intervention": "#d97706",
        "urgence": "#dc2626",
    }

    events = []
    for row in rows:
        r = dict(row)
        events.append({
            "id": r["id"],
            "title": f"{r['patient_name']} — {r['title']}",
            "start": r["start_datetime"],
            "end": r["end_datetime"],
            "color": colors.get(r["appointment_type"], "#2563eb"),
            "extendedProps": {
                "patient_id": r["patient_id"],
                "status": r["status"],
                "type": r["appointment_type"],
                "room": r["room"],
                "notes": r["notes"],
            },
        })

    return JSONResponse(content=events)


@router.post("/new")
async def create_appointment(
    request: Request,
    patient_id: int = Form(...),
    doctor_id: int = Form(...),
    title: str = Form(...),
    appointment_type: str = Form("consultation"),
    status: str = Form("planifie"),
    start_datetime: str = Form(...),
    end_datetime: str = Form(...),
    room: str = Form(""),
    notes: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    await db.execute(
        """INSERT INTO appointments (patient_id, doctor_id, title, appointment_type, status, start_datetime, end_datetime, room, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, title, appointment_type, status, start_datetime, end_datetime, room or None, notes or None),
    )
    await db.commit()
    return RedirectResponse(url="/appointments", status_code=302)


@router.post("/{appointment_id}/status")
async def update_status(
    request: Request,
    appointment_id: int,
    status: str = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    await db.execute(
        "UPDATE appointments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? ",
        (status, appointment_id),
    )
    await db.commit()
    return JSONResponse(content={"ok": True})


@router.post("/{appointment_id}/delete")
async def delete_appointment(
    request: Request,
    appointment_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Keep downstream records valid when an appointment has already been used.
    await db.execute(
        "UPDATE consultations SET appointment_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE appointment_id = ? ",
        (appointment_id,),
    )
    await db.execute(
        "UPDATE questionnaire_responses SET appointment_id = NULL WHERE appointment_id = ? ",
        (appointment_id,),
    )
    await db.execute("DELETE FROM appointments WHERE id = ? ", (appointment_id,))
    await db.commit()
    return RedirectResponse(url="/appointments", status_code=302)
