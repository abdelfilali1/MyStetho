from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/messages")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def inbox(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Received messages
    cursor = await db.execute(
        """SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name, p.first_name || ' ' || p.last_name AS patient_name FROM messages m JOIN users u ON m.sender_id = u.id LEFT JOIN patients p ON m.patient_id = p.id WHERE m.recipient_id = ? AND m.parent_message_id IS NULL ORDER BY m.created_at DESC""",
        (user["sub"],),
    )
    received = [dict(r) for r in await cursor.fetchall()]

    # Sent messages
    cursor = await db.execute(
        """SELECT m.*, u.first_name || ' ' || u.last_name AS recipient_name, p.first_name || ' ' || p.last_name AS patient_name FROM messages m JOIN users u ON m.recipient_id = u.id LEFT JOIN patients p ON m.patient_id = p.id WHERE m.sender_id = ? AND m.parent_message_id IS NULL ORDER BY m.created_at DESC""",
        (user["sub"],),
    )
    sent = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "messages/inbox.html",
        {"request": request, "user": user, "active": "messages", "received": received, "sent": sent},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_message_form(
    request: Request,
    reply_to: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT id, first_name, last_name, role FROM users WHERE is_active = 1 AND id != ? ORDER BY last_name",
        (user["sub"],),
    )
    users_list = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name")
    patients = [dict(r) for r in await cursor.fetchall()]

    original = None
    if reply_to:
        cursor = await db.execute(
            """SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name FROM messages m JOIN users u ON m.sender_id = u.id WHERE m.id = ? """,
            (reply_to,),
        )
        row = await cursor.fetchone()
        if row:
            original = dict(row)

    return templates.TemplateResponse(
        "messages/compose.html",
        {
            "request": request, "user": user, "active": "messages",
            "users_list": users_list, "patients": patients, "original": original,
        },
    )


@router.post("/new")
async def send_message(
    request: Request,
    recipient_id: int = Form(...),
    subject: str = Form(""),
    body: str = Form(...),
    patient_id: Optional[int] = Form(None),
    parent_message_id: Optional[int] = Form(None),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    await db.execute(
        """INSERT INTO messages (sender_id, recipient_id, patient_id, subject, body, parent_message_id) VALUES (?, ?, ?, ?, ?, ?)""",
        (user["sub"], recipient_id, patient_id if patient_id else None,
         subject or None, body, parent_message_id),
    )
    await db.commit()
    return RedirectResponse(url="/messages", status_code=302)


@router.get("/{message_id}", response_class=HTMLResponse)
async def view_message(request: Request, message_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name, r.first_name || ' ' || r.last_name AS recipient_name, p.first_name || ' ' || p.last_name AS patient_name FROM messages m JOIN users u ON m.sender_id = u.id JOIN users r ON m.recipient_id = r.id LEFT JOIN patients p ON m.patient_id = p.id WHERE m.id = ? """,
        (message_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/messages", status_code=302)
    message = dict(row)

    # Mark as read if I'm the recipient
    if message["recipient_id"] == user["sub"] and not message["is_read"]:
        await db.execute("UPDATE messages SET is_read = 1 WHERE id = ? ", (message_id,))
        await db.commit()

    # Get replies
    cursor = await db.execute(
        """SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name FROM messages m JOIN users u ON m.sender_id = u.id WHERE m.parent_message_id = ? ORDER BY m.created_at""",
        (message_id,),
    )
    replies = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "messages/view.html",
        {"request": request, "user": user, "active": "messages", "message": message, "replies": replies},
    )
