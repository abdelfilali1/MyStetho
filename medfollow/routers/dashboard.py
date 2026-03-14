from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import date
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        # Check if any users exist; if not, redirect to setup
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        count = (await cursor.fetchone())[0]
        if count == 0:
            return RedirectResponse(url="/setup", status_code=302)
        return RedirectResponse(url="/login", status_code=302)

    today = date.today().isoformat()

    # Stats
    cursor = await db.execute("SELECT COUNT(*) FROM patients WHERE is_active = 1")
    total_patients = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COUNT(*) FROM appointments WHERE date(start_datetime) = ?", (today,)
    )
    today_appointments_count = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COUNT(*) FROM consultations WHERE strftime('%Y-%m', consultation_date) = strftime('%Y-%m', 'now')"
    )
    month_consultations = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COUNT(*) FROM messages WHERE recipient_id = ? AND is_read = 0",
        (user["sub"],),
    )
    unread_messages = (await cursor.fetchone())[0]

    stats = {
        "total_patients": total_patients,
        "today_appointments": today_appointments_count,
        "month_consultations": month_consultations,
        "unread_messages": unread_messages,
    }

    # Today's appointments with patient names
    cursor = await db.execute(
        """SELECT a.*, p.first_name || ' ' || p.last_name AS patient_name FROM appointments a JOIN patients p ON a.patient_id = p.id WHERE date(a.start_datetime) = ? ORDER BY a.start_datetime""",
        (today,),
    )
    today_apt_rows = await cursor.fetchall()
    today_appointments = [dict(row) for row in today_apt_rows]

    # Recent patients
    cursor = await db.execute(
        "SELECT * FROM patients WHERE is_active = 1 ORDER BY created_at DESC LIMIT 5"
    )
    recent_rows = await cursor.fetchall()
    recent_patients = [dict(row) for row in recent_rows]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "active": "dashboard",
            "stats": stats,
            "today_appointments": today_appointments,
            "recent_patients": recent_patients,
        },
    )
