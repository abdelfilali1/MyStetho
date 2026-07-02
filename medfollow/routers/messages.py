from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api, effective_doctor_id, set_flash
from services.audit import log_audit, client_ip

router = APIRouter(prefix="/messages")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def _allowed_recipients(db: aiosqlite.Connection, user: dict) -> list:
    """Cloisonnement de la messagerie : la seule communication possible est
    entre le dentiste et sa secrétaire (les admins restent joignables).

    - secretaire → uniquement son médecin lié (users.linked_doctor_id)
    - medecin    → ses secrétaires + les admins
    - admin      → tous les utilisateurs actifs
    """
    role = user.get("role")

    if role == "admin":
        cursor = await db.execute(
            "SELECT id, first_name, last_name, role FROM users WHERE is_active = 1 AND id != ? ORDER BY last_name",
            (user["sub"],),
        )
        return [dict(r) for r in await cursor.fetchall()]

    if role == "secretaire":
        # Relire linked_doctor_id en base : le JWT peut être obsolète.
        cursor = await db.execute(
            "SELECT linked_doctor_id FROM users WHERE id = ?", (user["sub"],)
        )
        row = await cursor.fetchone()
        linked_id = row["linked_doctor_id"] if row else None
        if not linked_id:
            return []
        cursor = await db.execute(
            "SELECT id, first_name, last_name, role FROM users WHERE id = ? AND is_active = 1",
            (linked_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # medecin : ses secrétaires liées + les admins
    cursor = await db.execute(
        """SELECT id, first_name, last_name, role FROM users
           WHERE is_active = 1 AND id != ?
             AND ((role = 'secretaire' AND linked_doctor_id = ?) OR role = 'admin')
           ORDER BY last_name""",
        (user["sub"], user["sub"]),
    )
    return [dict(r) for r in await cursor.fetchall()]


@router.get("/", response_class=HTMLResponse)
async def inbox(
    request: Request,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
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


@router.get("/api/unread-count")
async def unread_count(
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE recipient_id = ? AND is_read = 0",
        (user["sub"],),
    )
    row = await cursor.fetchone()
    return {"count": row["c"] if row else 0}


@router.get("/new", response_class=HTMLResponse)
async def new_message_form(
    request: Request,
    reply_to: Optional[int] = None,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    users_list = await _allowed_recipients(db, user)

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE is_active = 1 AND doctor_id = ? ORDER BY last_name",
        (effective_doctor_id(user),),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    original = None
    if reply_to:
        cursor = await db.execute(
            """SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name FROM messages m JOIN users u ON m.sender_id = u.id WHERE m.id = ? AND (m.sender_id = ? OR m.recipient_id = ?) """,
            (reply_to, user["sub"], user["sub"]),
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
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Cloisonnement : vérifier côté serveur que le destinataire est autorisé.
    if parent_message_id:
        # Réponse : autorisée tant que l'utilisateur est expéditeur ou
        # destinataire du message original, et que le destinataire de la
        # réponse est l'autre partie de cet échange.
        cur = await db.execute(
            "SELECT sender_id, recipient_id FROM messages WHERE id = ? AND (sender_id = ? OR recipient_id = ?)",
            (parent_message_id, user["sub"], user["sub"]),
        )
        orig = await cur.fetchone()
        if not orig or recipient_id not in (orig["sender_id"], orig["recipient_id"]):
            response = RedirectResponse(url="/messages/new", status_code=302)
            set_flash(response, "Destinataire non autorisé", "error")
            return response
    else:
        allowed_ids = {u["id"] for u in await _allowed_recipients(db, user)}
        if recipient_id not in allowed_ids:
            response = RedirectResponse(url="/messages/new", status_code=302)
            set_flash(
                response,
                "Destinataire non autorisé : la messagerie est réservée aux échanges entre le médecin et sa secrétaire.",
                "error",
            )
            return response

    # Only allow attaching a patient the sender actually owns.
    if patient_id:
        cur = await db.execute(
            "SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?",
            (patient_id, effective_doctor_id(user)),
        )
        if not await cur.fetchone():
            patient_id = None

    cursor = await db.execute(
        """INSERT INTO messages (sender_id, recipient_id, patient_id, subject, body, parent_message_id) VALUES (?, ?, ?, ?, ?, ?)""",
        (user["sub"], recipient_id, patient_id if patient_id else None,
         subject or None, body, parent_message_id),
    )
    message_id = cursor.lastrowid
    await db.commit()

    await log_audit(
        db, user, "message_envoye",
        entity_type="message", entity_id=message_id,
        patient_id=patient_id if patient_id else None,
        ip=client_ip(request),
    )

    response = RedirectResponse(url="/messages", status_code=302)
    set_flash(response, "Message envoyé")
    return response


@router.get("/{message_id}", response_class=HTMLResponse)
async def view_message(
    request: Request,
    message_id: int,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        """SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name, r.first_name || ' ' || r.last_name AS recipient_name, p.first_name || ' ' || p.last_name AS patient_name FROM messages m JOIN users u ON m.sender_id = u.id JOIN users r ON m.recipient_id = r.id LEFT JOIN patients p ON m.patient_id = p.id WHERE m.id = ? AND (m.sender_id = ? OR m.recipient_id = ?) """,
        (message_id, user["sub"], user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/messages", status_code=302)
    message = dict(row)

    # Mark as read if I'm the recipient
    if message["recipient_id"] == user["sub"] and not message["is_read"]:
        await db.execute("UPDATE messages SET is_read = 1 WHERE id = ? ", (message_id,))
        await db.commit()

    await log_audit(
        db, user, "message_consulte",
        entity_type="message", entity_id=message_id,
        patient_id=message.get("patient_id"),
        ip=client_ip(request),
    )

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
