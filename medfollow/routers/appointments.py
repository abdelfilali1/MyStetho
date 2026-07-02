from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import date, datetime, timedelta
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api, effective_doctor_id, set_flash
from services.audit import log_audit, client_ip

router = APIRouter(prefix="/appointments")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def agenda(
    request: Request,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = effective_doctor_id(user)

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
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return appointments as JSON for the calendar."""
    uid = effective_doctor_id(user)
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
                "motif": r["title"],
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
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return up to 5 available slots for a given doctor and date."""
    doctor_id = effective_doctor_id(user)  # ignore any client-supplied doctor_id; only your own slots
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
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Create appointment via JSON. Returns conflict info if slot is taken."""
    data = await request.json()
    patient_id = data.get("patient_id")
    doctor_id = effective_doctor_id(user)  # always the logged-in doctor; never trust the client body
    title = data.get("title", "")
    appointment_type = data.get("appointment_type", "consultation")
    status = data.get("status", "planifie")
    start_datetime = data.get("start_datetime", "")
    end_datetime = data.get("end_datetime", "")
    room = data.get("room", "") or None
    notes = data.get("notes", "") or None
    exclude_id = data.get("exclude_id", 0)

    # The patient must belong to the current doctor.
    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, doctor_id))
    if not await cur.fetchone():
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})

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

    cur = await db.execute(
        """INSERT INTO appointments (patient_id, doctor_id, title, appointment_type, status,
           start_datetime, end_datetime, room, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, title, appointment_type, status,
         start_datetime, end_datetime, room, notes),
    )
    await db.commit()
    await log_audit(db, user, "rdv_cree", entity_type="appointment", entity_id=cur.lastrowid,
                    patient_id=patient_id, ip=client_ip(request))
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
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Fallback form POST (no conflict check — kept for compatibility)."""
    cursor = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cursor.fetchone():
        return RedirectResponse(url="/appointments", status_code=302)
    doctor_id = user["sub"]

    cur = await db.execute(
        """INSERT INTO appointments (patient_id, doctor_id, title, appointment_type, status, start_datetime, end_datetime, room, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, title, appointment_type, status, start_datetime, end_datetime, room or None, notes or None),
    )
    await db.commit()
    await log_audit(db, user, "rdv_cree", entity_type="appointment", entity_id=cur.lastrowid, patient_id=patient_id, ip=client_ip(request))
    resp = RedirectResponse(url="/appointments", status_code=302)
    set_flash(resp, "Rendez-vous créé")
    return resp


@router.post("/{appointment_id}/reschedule")
async def reschedule_appointment(
    request: Request,
    appointment_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Reschedule an appointment to a new start/end datetime. Checks for conflicts."""
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
    await log_audit(db, user, "rdv_deplace", entity_type="appointment", entity_id=appointment_id, ip=client_ip(request))
    return JSONResponse(content={"ok": True})


@router.post("/{appointment_id}/status")
async def update_status(
    request: Request,
    appointment_id: int,
    status: str = Form(...),
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT id, patient_id FROM appointments WHERE id = ? AND doctor_id = ?",
        (appointment_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return JSONResponse(status_code=403, content={"error": "Accès refusé"})

    await db.execute(
        "UPDATE appointments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? ",
        (status, appointment_id),
    )
    await db.commit()
    await log_audit(db, user, "rdv_statut", entity_type="appointment", entity_id=appointment_id, patient_id=row[1], ip=client_ip(request), details=f"status={status}")
    return JSONResponse(content={"ok": True})


@router.post("/{appointment_id}/update")
async def update_appointment(
    request: Request,
    appointment_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Modifier le motif / type / salle / notes d'un RDV existant (item 30)."""
    data = await request.json()
    title = (data.get("title") or "").strip()
    appointment_type = (data.get("appointment_type") or "").strip()
    room = (data.get("room") or "").strip()
    notes = (data.get("notes") or "").strip()

    if not title:
        return JSONResponse(status_code=400, content={"error": "Le motif est obligatoire"})
    if appointment_type not in ("consultation", "suivi", "intervention", "urgence"):
        return JSONResponse(status_code=400, content={"error": "Type de rendez-vous invalide"})

    cursor = await db.execute(
        "SELECT id, patient_id FROM appointments WHERE id = ? AND doctor_id = ?",
        (appointment_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return JSONResponse(status_code=403, content={"error": "Accès refusé"})

    await db.execute(
        "UPDATE appointments SET title = ?, appointment_type = ?, room = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? ",
        (title, appointment_type, room or None, notes or None, appointment_id),
    )
    await db.commit()
    await log_audit(db, user, "rdv_modifie", entity_type="appointment", entity_id=appointment_id, patient_id=row[1], ip=client_ip(request))
    return JSONResponse(content={"ok": True})


@router.post("/{appointment_id}/delete")
async def delete_appointment(
    request: Request,
    appointment_id: int,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT id, patient_id FROM appointments WHERE id = ? AND doctor_id = ?",
        (appointment_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
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
    await log_audit(db, user, "rdv_supprime", entity_type="appointment", entity_id=appointment_id, patient_id=row[1], ip=client_ip(request))
    resp = RedirectResponse(url="/appointments", status_code=302)
    set_flash(resp, "Rendez-vous supprimé")
    return resp
