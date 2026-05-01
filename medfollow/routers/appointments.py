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


@router.get("/api/free-slots")
async def get_free_slots(
    request: Request,
    doctor_id: int,
    date: str,
    duration: int = 30,
    exclude_id: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return up to 5 available slots for a given doctor and date."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    # Fetch all non-cancelled appointments for that doctor on that date
    cursor = await db.execute(
        """SELECT start_datetime, end_datetime FROM appointments
           WHERE doctor_id = ? AND date(start_datetime) = ? AND id != ?
           AND status NOT IN ('annule', 'absent')
           ORDER BY start_datetime""",
        (doctor_id, date, exclude_id),
    )
    booked = [(row[0], row[1]) for row in await cursor.fetchall()]

    # Generate candidate slots 08:00 – 19:30
    from datetime import timedelta
    base = datetime.strptime(f"{date} 08:00", "%Y-%m-%d %H:%M")
    end_of_day = datetime.strptime(f"{date} 19:30", "%Y-%m-%d %H:%M")
    slots = []
    cursor_dt = base
    while cursor_dt + timedelta(minutes=duration) <= end_of_day and len(slots) < 8:
        slot_end = cursor_dt + timedelta(minutes=duration)
        s_str = cursor_dt.strftime("%Y-%m-%dT%H:%M")
        e_str = slot_end.strftime("%Y-%m-%dT%H:%M")
        # Check overlap against booked appointments
        overlap = any(
            s_str < b_end and e_str > b_start
            for b_start, b_end in booked
        )
        if not overlap:
            slots.append({"start": s_str, "end": e_str,
                          "label": cursor_dt.strftime("%H:%M") + " – " + slot_end.strftime("%H:%M")})
        cursor_dt += timedelta(minutes=30)

    return JSONResponse(content={"slots": slots})


@router.post("/api/new")
async def create_appointment_api(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Create appointment via JSON. Returns conflict info if slot is taken."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    data = await request.json()
    patient_id = data.get("patient_id")
    doctor_id = data.get("doctor_id")
    title = data.get("title", "")
    appointment_type = data.get("appointment_type", "consultation")
    status = data.get("status", "planifie")
    start_datetime = data.get("start_datetime", "")
    end_datetime = data.get("end_datetime", "")
    room = data.get("room", "") or None
    notes = data.get("notes", "") or None
    exclude_id = data.get("exclude_id", 0)

    # Conflict check: any non-cancelled appointment for same doctor that overlaps
    cursor = await db.execute(
        """SELECT id FROM appointments
           WHERE doctor_id = ? AND id != ?
           AND status NOT IN ('annule', 'absent')
           AND start_datetime < ? AND end_datetime > ?""",
        (doctor_id, exclude_id, end_datetime, start_datetime),
    )
    conflict_row = await cursor.fetchone()
    if conflict_row:
        # Return next available slots for same date
        date_str = start_datetime[:10]
        from datetime import timedelta
        base = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M")
        end_of_day = datetime.strptime(f"{date_str} 19:30", "%Y-%m-%d %H:%M")

        cursor2 = await db.execute(
            """SELECT start_datetime, end_datetime FROM appointments
               WHERE doctor_id = ? AND date(start_datetime) = ?
               AND status NOT IN ('annule', 'absent')
               ORDER BY start_datetime""",
            (doctor_id, date_str),
        )
        booked = [(r[0], r[1]) for r in await cursor2.fetchall()]

        duration = int((datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M") -
                        datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M")).total_seconds() // 60)
        duration = max(15, duration)

        suggestions = []
        cursor_dt = base
        while cursor_dt + timedelta(minutes=duration) <= end_of_day and len(suggestions) < 4:
            slot_end = cursor_dt + timedelta(minutes=duration)
            s_str = cursor_dt.strftime("%Y-%m-%dT%H:%M")
            e_str = slot_end.strftime("%Y-%m-%dT%H:%M")
            overlap = any(s_str < b_end and e_str > b_start for b_start, b_end in booked)
            if not overlap:
                suggestions.append({"start": s_str, "end": e_str,
                                    "label": cursor_dt.strftime("%H:%M") + " – " + slot_end.strftime("%H:%M")})
            cursor_dt += timedelta(minutes=30)

        return JSONResponse(status_code=409, content={"conflict": True, "suggestions": suggestions})

    await db.execute(
        """INSERT INTO appointments (patient_id, doctor_id, title, appointment_type, status,
           start_datetime, end_datetime, room, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, title, appointment_type, status,
         start_datetime, end_datetime, room, notes),
    )
    await db.commit()
    return JSONResponse(content={"ok": True})


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
    """Fallback form POST (no conflict check — kept for compatibility)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    await db.execute(
        """INSERT INTO appointments (patient_id, doctor_id, title, appointment_type, status, start_datetime, end_datetime, room, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, title, appointment_type, status, start_datetime, end_datetime, room or None, notes or None),
    )
    await db.commit()
    return RedirectResponse(url="/appointments", status_code=302)


@router.post("/{appointment_id}/reschedule")
async def reschedule_appointment(
    request: Request,
    appointment_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Reschedule an appointment to a new start/end datetime. Checks for conflicts."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    data = await request.json()
    start_datetime = data.get("start_datetime", "")
    end_datetime = data.get("end_datetime", "")

    # Fetch doctor_id from the appointment
    cursor = await db.execute(
        "SELECT doctor_id FROM appointments WHERE id = ? AND doctor_id = ?",
        (appointment_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "RDV introuvable"})
    doctor_id = row["doctor_id"]

    # Conflict check (exclude self)
    cursor = await db.execute(
        """SELECT id FROM appointments
           WHERE doctor_id = ? AND id != ?
           AND status NOT IN ('annule', 'absent')
           AND start_datetime < ? AND end_datetime > ?""",
        (doctor_id, appointment_id, end_datetime, start_datetime),
    )
    if await cursor.fetchone():
        # Return suggestions
        date_str = start_datetime[:10]
        cursor2 = await db.execute(
            """SELECT start_datetime, end_datetime FROM appointments
               WHERE doctor_id = ? AND date(start_datetime) = ? AND id != ?
               AND status NOT IN ('annule', 'absent')
               ORDER BY start_datetime""",
            (doctor_id, date_str, appointment_id),
        )
        booked = [(r[0], r[1]) for r in await cursor2.fetchall()]
        duration = int((datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M") -
                        datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M")).total_seconds() // 60)
        duration = max(15, duration)
        end_of_day = datetime.strptime(f"{date_str} 19:30", "%Y-%m-%d %H:%M")
        suggestions = []
        cursor_dt = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M")
        while cursor_dt + timedelta(minutes=duration) <= end_of_day and len(suggestions) < 4:
            slot_end = cursor_dt + timedelta(minutes=duration)
            s_str = cursor_dt.strftime("%Y-%m-%dT%H:%M")
            e_str = slot_end.strftime("%Y-%m-%dT%H:%M")
            overlap = any(s_str < b_end and e_str > b_start for b_start, b_end in booked)
            if not overlap:
                suggestions.append({"start": s_str, "end": e_str,
                                    "label": cursor_dt.strftime("%H:%M") + " – " + slot_end.strftime("%H:%M")})
            cursor_dt += timedelta(minutes=30)
        return JSONResponse(status_code=409, content={"conflict": True, "suggestions": suggestions})

    await db.execute(
        "UPDATE appointments SET start_datetime = ?, end_datetime = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (start_datetime, end_datetime, appointment_id),
    )
    await db.commit()
    return JSONResponse(content={"ok": True})


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

    cursor = await db.execute(
        "SELECT id FROM appointments WHERE id = ? AND doctor_id = ?",
        (appointment_id, user["sub"]),
    )
    if not await cursor.fetchone():
        return JSONResponse(status_code=403, content={"error": "Accès refusé"})

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

    cursor = await db.execute(
        "SELECT id FROM appointments WHERE id = ? AND doctor_id = ?",
        (appointment_id, user["sub"]),
    )
    if not await cursor.fetchone():
        return RedirectResponse(url="/appointments", status_code=302)

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
