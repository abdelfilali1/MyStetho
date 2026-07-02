"""Messagerie façon SMS/chat : liste de contacts à gauche, conversation à droite,
envoi de messages en fil continu. Le cloisonnement reste strict (dentiste ↔ sa
secrétaire ; les admins joignables). Notifications via le badge global + toasts."""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api
from services.audit import log_audit, client_ip

router = APIRouter(prefix="/messages")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

ROLE_LABELS = {"medecin": "Médecin", "secretaire": "Secrétaire", "admin": "Admin"}


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
        cursor = await db.execute("SELECT linked_doctor_id FROM users WHERE id = ?", (user["sub"],))
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


def _display_name(first: str, last: str, role: str) -> str:
    name = f"{(first or '').strip()} {(last or '').strip()}".strip()
    if role in ("medecin", "admin"):
        return f"Dr {name}" if name else "Praticien"
    return name or "Utilisateur"


def _initials(first: str, last: str) -> str:
    a = (first or " ").strip()[:1]
    b = (last or " ").strip()[:1]
    return (a + b).upper() or "?"


async def _contacts_with_meta(db: aiosqlite.Connection, user: dict) -> list:
    """Liste des contacts autorisés + dernier message et nombre de non-lus."""
    uid = user["sub"]
    contacts = await _allowed_recipients(db, user)
    out = []
    for c in contacts:
        cid = c["id"]
        cur = await db.execute(
            """SELECT body, created_at, sender_id FROM messages
               WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (uid, cid, cid, uid),
        )
        last = await cur.fetchone()
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE sender_id = ? AND recipient_id = ? AND is_read = 0",
            (cid, uid),
        )
        unread = (await cur.fetchone())["n"]
        out.append({
            "id": cid,
            "name": _display_name(c["first_name"], c["last_name"], c["role"]),
            "role": c["role"],
            "role_label": ROLE_LABELS.get(c["role"], c["role"]),
            "initials": _initials(c["first_name"], c["last_name"]),
            "last_body": last["body"] if last else "",
            "last_at": last["created_at"] if last else None,
            "last_mine": bool(last and last["sender_id"] == uid),
            "unread": unread,
        })
    # Conversations les plus récentes en premier ; contacts sans échange à la fin.
    out.sort(key=lambda x: (x["last_at"] or ""), reverse=True)
    return out


@router.get("/", response_class=HTMLResponse)
async def chat_home(
    request: Request,
    to: Optional[int] = None,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    contacts = await _contacts_with_meta(db, user)
    return templates.TemplateResponse(
        "messages/chat.html",
        {"request": request, "user": user, "active": "messages", "contacts": contacts, "open_to": to},
    )


@router.get("/api/contacts")
async def api_contacts(
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    return {"contacts": await _contacts_with_meta(db, user)}


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


@router.get("/api/thread/{contact_id}")
async def api_thread(
    request: Request,
    contact_id: int,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = user["sub"]
    # Accès : contact autorisé, ou historique existant (on est partie prenante).
    allowed = {c["id"] for c in await _allowed_recipients(db, user)}
    if contact_id not in allowed:
        cur = await db.execute(
            "SELECT 1 FROM messages WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?) LIMIT 1",
            (uid, contact_id, contact_id, uid),
        )
        if not await cur.fetchone():
            return JSONResponse(status_code=403, content={"error": "Contact non autorisé"})

    cur = await db.execute("SELECT id, first_name, last_name, role FROM users WHERE id = ?", (contact_id,))
    crow = await cur.fetchone()
    if not crow:
        return JSONResponse(status_code=404, content={"error": "Introuvable"})

    # Marquer comme lus les messages entrants de ce contact.
    await db.execute(
        "UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ? AND is_read = 0",
        (contact_id, uid),
    )
    await db.commit()

    cur = await db.execute(
        """SELECT id, sender_id, body, created_at FROM messages
           WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)
           ORDER BY created_at ASC, id ASC""",
        (uid, contact_id, contact_id, uid),
    )
    messages = [
        {"id": r["id"], "mine": r["sender_id"] == uid, "body": r["body"], "created_at": r["created_at"]}
        for r in await cur.fetchall()
    ]
    await log_audit(db, user, "conversation_consultee", entity_type="message", entity_id=contact_id, ip=client_ip(request))
    return {
        "contact": {
            "id": crow["id"],
            "name": _display_name(crow["first_name"], crow["last_name"], crow["role"]),
            "role": crow["role"],
            "role_label": ROLE_LABELS.get(crow["role"], crow["role"]),
            "initials": _initials(crow["first_name"], crow["last_name"]),
        },
        "messages": messages,
    }


@router.post("/api/send")
async def api_send(
    request: Request,
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    data = await request.json()
    try:
        recipient_id = int(data.get("recipient_id"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Destinataire invalide"})
    body = (data.get("body") or "").strip()
    if not body:
        return JSONResponse(status_code=400, content={"error": "Message vide"})
    if len(body) > 4000:
        body = body[:4000]

    allowed = {c["id"] for c in await _allowed_recipients(db, user)}
    if recipient_id not in allowed:
        return JSONResponse(status_code=403, content={"error": "Destinataire non autorisé"})

    cur = await db.execute(
        "INSERT INTO messages (sender_id, recipient_id, body) VALUES (?, ?, ?)",
        (user["sub"], recipient_id, body),
    )
    mid = cur.lastrowid
    await db.commit()
    await log_audit(db, user, "message_envoye", entity_type="message", entity_id=mid, ip=client_ip(request))

    cur = await db.execute("SELECT created_at FROM messages WHERE id = ?", (mid,))
    created = (await cur.fetchone())["created_at"]
    return {"id": mid, "mine": True, "body": body, "created_at": created}
