import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from database.connection import get_db
from config import TEMPLATES_DIR
from services.auth_service import hash_password, verify_password, create_token, decode_token

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_current_user(request: Request) -> dict | None:
    """Extract user from JWT cookie."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_token(token)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    count = (await cursor.fetchone())[0]
    if count == 0:
        return RedirectResponse(url="/setup", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    count = (await cursor.fetchone())[0]
    if count == 0:
        return RedirectResponse(url="/setup", status_code=302)

    cursor = await db.execute(
        "SELECT id, email, password_hash, first_name, last_name, role, specialty FROM users WHERE email = ? AND is_active = 1",
        (email,),
    )
    row = await cursor.fetchone()

    if not row or not verify_password(password, row[2]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email ou mot de passe incorrect"},
        )

    token = create_token(user_id=row[0], email=row[1], role=row[5], specialty=row[6], first_name=row[3], last_name=row[4])
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=8 * 3600,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/admin/users", response_class=HTMLResponse)
async def list_users(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    cursor = await db.execute("SELECT id, email, first_name, last_name, role, specialty, is_active FROM users ORDER BY created_at")
    rows = await cursor.fetchall()
    users = [{"id": r[0], "email": r[1], "first_name": r[2], "last_name": r[3], "role": r[4], "specialty": r[5], "is_active": r[6]} for r in rows]
    return templates.TemplateResponse("admin/users.html", {"request": request, "user": user, "users": users, "active": "admin_users"})


@router.get("/admin/users/new", response_class=HTMLResponse)
async def new_user_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("admin/user_form.html", {"request": request, "user": user, "active": "admin_users", "error": None})


@router.post("/admin/users/new", response_class=HTMLResponse)
async def create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    role: str = Form(...),
    specialty: str = Form(""),
    phone: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    def error(msg):
        return templates.TemplateResponse("admin/user_form.html", {
            "request": request, "user": current_user, "active": "admin_users", "error": msg,
            "form": {"email": email, "first_name": first_name, "last_name": last_name, "role": role, "specialty": specialty, "phone": phone}
        })

    if role == "admin" and email != "abdelfilaliansary@gmail.com":
        return error("Le rôle admin est réservé à l'administrateur principal")
    if not specialty:
        return error("Veuillez choisir une spécialité")
    if password != password_confirm:
        return error("Les mots de passe ne correspondent pas")
    if len(password) < 10:
        return error("Le mot de passe doit contenir au moins 10 caractères")

    cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
    if await cursor.fetchone():
        return error("Cet email est déjà utilisé")

    pw_hash = hash_password(password)
    await db.execute(
        "INSERT INTO users (email, password_hash, first_name, last_name, role, specialty, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (email, pw_hash, first_name, last_name, role, specialty or None, phone or None),
    )
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    count = (await cursor.fetchone())[0]
    if count > 0:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("setup.html", {"request": request, "error": None})


@router.post("/setup", response_class=HTMLResponse)
async def setup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    specialty: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    count = (await cursor.fetchone())[0]
    if count > 0:
        return RedirectResponse(url="/login", status_code=302)

    if email != "abdelfilaliansary@gmail.com":
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Seul l'administrateur principal peut créer le premier compte"},
        )

    if not specialty:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Veuillez choisir une spécialité"},
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Les mots de passe ne correspondent pas"},
        )

    if len(password) < 10:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Le mot de passe doit contenir au moins 10 caractères"},
        )

    pw_hash = hash_password(password)
    cursor = await db.execute(
        """INSERT INTO users (email, password_hash, first_name, last_name, role, specialty) VALUES (?, ?, ?, ?, 'admin', ?)""",
        (email, pw_hash, first_name, last_name, specialty or None),
    )
    await db.commit()

    token = create_token(user_id=cursor.lastrowid, email=email, role="admin", first_name=first_name, last_name=last_name)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=8 * 3600)
    return response


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(request: Request, user_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    cursor = await db.execute("SELECT id, email, first_name, last_name, role, specialty, phone, is_active FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/admin/users", status_code=302)
    edit_user = {"id": row[0], "email": row[1], "first_name": row[2], "last_name": row[3], "role": row[4], "specialty": row[5], "phone": row[6], "is_active": row[7]}
    return templates.TemplateResponse("admin/user_form.html", {"request": request, "user": user, "active": "admin_users", "error": None, "form": edit_user, "editing": True})

@router.post("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def update_user(
    request: Request, user_id: int,
    email: str = Form(...), first_name: str = Form(...), last_name: str = Form(...),
    role: str = Form(...), specialty: str = Form(""), phone: str = Form(""),
    password: str = Form(""), password_confirm: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    form_data = {"id": user_id, "email": email, "first_name": first_name, "last_name": last_name, "role": role, "specialty": specialty, "phone": phone}
    def error(msg):
        return templates.TemplateResponse("admin/user_form.html", {
            "request": request, "user": current_user, "active": "admin_users", "error": msg, "form": form_data, "editing": True
        })

    if role == "admin" and email != "abdelfilaliansary@gmail.com":
        return error("Le rôle admin est réservé à l'administrateur principal")

    if password:
        if password != password_confirm:
            return error("Les mots de passe ne correspondent pas")
        if len(password) < 10:
            return error("Le mot de passe doit contenir au moins 10 caractères")
        pw_hash = hash_password(password)
        await db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))

    await db.execute(
        "UPDATE users SET email=?, first_name=?, last_name=?, role=?, specialty=?, phone=? WHERE id=?",
        (email, first_name, last_name, role, specialty or None, phone or None, user_id)
    )
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)

@router.post("/admin/users/{user_id}/reset-password-link", response_class=HTMLResponse)
async def generate_reset_link(request: Request, user_id: int, db: aiosqlite.Connection = Depends(get_db)):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    cursor = await db.execute("SELECT id, email, first_name, last_name FROM users WHERE id=?", (user_id,))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/admin/users", status_code=302)
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    await db.execute(
        "INSERT INTO password_resets (token, user_id, expires_at) VALUES (?,?,?)",
        (token, user_id, expires_at),
    )
    await db.commit()
    base_url = str(request.base_url).rstrip("/")
    reset_link = f"{base_url}/reset-password/{token}"
    cursor = await db.execute("SELECT id, email, first_name, last_name, role, specialty, is_active FROM users ORDER BY created_at")
    rows = await cursor.fetchall()
    users = [{"id": r[0], "email": r[1], "first_name": r[2], "last_name": r[3], "role": r[4], "specialty": r[5], "is_active": r[6]} for r in rows]
    return templates.TemplateResponse("admin/users.html", {
        "request": request, "user": current_user, "users": users, "active": "admin_users",
        "reset_link": reset_link, "reset_user": f"{row[2]} {row[3]}"
    })


@router.get("/reset-password/{token}", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT r.user_id, r.expires_at, r.used_at, u.email FROM password_resets r JOIN users u ON r.user_id=u.id WHERE r.token=?",
        (token,),
    )
    row = await cursor.fetchone()
    if not row:
        return templates.TemplateResponse("reset_password.html", {"request": request, "error": "Lien invalide ou inexistant.", "valid": False, "token": token})
    if row[2]:
        return templates.TemplateResponse("reset_password.html", {"request": request, "error": "Ce lien a déjà été utilisé.", "valid": False, "token": token})
    if datetime.utcnow().isoformat() > row[1]:
        return templates.TemplateResponse("reset_password.html", {"request": request, "error": "Ce lien a expiré (validité 1 heure).", "valid": False, "token": token})
    return templates.TemplateResponse("reset_password.html", {"request": request, "error": None, "valid": True, "token": token, "email": row[3]})


@router.post("/reset-password/{token}", response_class=HTMLResponse)
async def reset_password(
    request: Request, token: str,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT r.user_id, r.expires_at, r.used_at, u.email FROM password_resets r JOIN users u ON r.user_id=u.id WHERE r.token=?",
        (token,),
    )
    row = await cursor.fetchone()
    def err(msg, valid=False):
        return templates.TemplateResponse("reset_password.html", {
            "request": request, "error": msg, "valid": valid, "token": token,
            "email": row[3] if row else ""
        })
    if not row:
        return err("Lien invalide.")
    if row[2]:
        return err("Ce lien a déjà été utilisé.")
    if datetime.utcnow().isoformat() > row[1]:
        return err("Ce lien a expiré.")
    if password != password_confirm:
        return err("Les mots de passe ne correspondent pas.", valid=True)
    if len(password) < 10:
        return err("Le mot de passe doit contenir au moins 10 caractères.", valid=True)
    pw_hash = hash_password(password)
    await db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, row[0]))
    await db.execute("UPDATE password_resets SET used_at=? WHERE token=?", (datetime.utcnow().isoformat(), token))
    await db.commit()
    return RedirectResponse(url="/login", status_code=302)


@router.post("/admin/users/{user_id}/toggle-active")
async def toggle_user_active(request: Request, user_id: int, db: aiosqlite.Connection = Depends(get_db)):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    await db.execute("UPDATE users SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


async def _get_invitations(db):
    cursor = await db.execute("""
        SELECT i.id, i.token, i.email, i.role, i.specialty, i.expires_at, i.used_at,
               u.first_name || ' ' || u.last_name
        FROM invitations i
        LEFT JOIN users u ON i.used_by = u.id
        ORDER BY i.created_at DESC LIMIT 30
    """)
    rows = await cursor.fetchall()
    now = datetime.utcnow().isoformat()
    result = []
    for r in rows:
        status = "utilisé" if r[6] else ("expiré" if r[5] < now else "en attente")
        result.append({"id": r[0], "token": r[1], "email": r[2] or "—", "role": r[3],
                        "specialty": r[4] or "—", "expires_at": r[5][:10], "status": status, "used_by": r[7]})
    return result


@router.get("/admin/invite", response_class=HTMLResponse)
async def invite_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    invitations = await _get_invitations(db)
    return templates.TemplateResponse("admin/invite.html", {
        "request": request, "user": user, "active": "admin_users",
        "invitations": invitations, "new_link": None
    })


@router.post("/admin/invite", response_class=HTMLResponse)
async def create_invite(
    request: Request,
    role: str = Form("medecin"),
    specialty: str = Form(""),
    email: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat()
    await db.execute(
        "INSERT INTO invitations (token, email, role, specialty, created_by, expires_at) VALUES (?,?,?,?,?,?)",
        (token, email.strip() or None, role, specialty or None, user["sub"], expires_at),
    )
    await db.commit()
    base_url = str(request.base_url).rstrip("/")
    new_link = f"{base_url}/register/{token}"
    invitations = await _get_invitations(db)
    return templates.TemplateResponse("admin/invite.html", {
        "request": request, "user": user, "active": "admin_users",
        "invitations": invitations, "new_link": new_link
    })


@router.post("/admin/invite/{inv_id}/delete")
async def delete_invite(request: Request, inv_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    await db.execute("DELETE FROM invitations WHERE id = ? AND used_at IS NULL", (inv_id,))
    await db.commit()
    return RedirectResponse(url="/admin/invite", status_code=302)


@router.get("/register/{token}", response_class=HTMLResponse)
async def register_page(request: Request, token: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT id, email, role, specialty, expires_at, used_at FROM invitations WHERE token = ?", (token,)
    )
    row = await cursor.fetchone()
    if not row:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Lien invalide ou inexistant.", "inv": None, "token": token})
    inv = {"id": row[0], "email": row[1], "role": row[2], "specialty": row[3], "expires_at": row[4], "used_at": row[5]}
    if inv["used_at"]:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Ce lien d'invitation a déjà été utilisé.", "inv": None, "token": token})
    if datetime.utcnow().isoformat() > inv["expires_at"]:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Ce lien d'invitation a expiré (validité 7 jours).", "inv": None, "token": token})
    return templates.TemplateResponse("register.html", {"request": request, "error": None, "inv": inv, "token": token, "form": {}})


@router.post("/register/{token}", response_class=HTMLResponse)
async def register(
    request: Request,
    token: str,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    specialty: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "SELECT id, email, role, specialty, expires_at, used_at FROM invitations WHERE token = ?", (token,)
    )
    row = await cursor.fetchone()
    if not row:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Lien invalide.", "inv": None, "token": token, "form": {}})
    inv = {"id": row[0], "email": row[1], "role": row[2], "specialty": row[3], "expires_at": row[4], "used_at": row[5]}

    def err(msg):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": msg, "inv": inv, "token": token,
            "form": {"email": email, "first_name": first_name, "last_name": last_name, "specialty": specialty}
        })

    if inv["used_at"]:
        return err("Ce lien a déjà été utilisé.")
    if datetime.utcnow().isoformat() > inv["expires_at"]:
        return err("Ce lien a expiré.")
    if password != password_confirm:
        return err("Les mots de passe ne correspondent pas.")
    if len(password) < 10:
        return err("Le mot de passe doit contenir au moins 10 caractères.")
    cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
    if await cursor.fetchone():
        return err("Cet email est déjà utilisé.")

    final_specialty = specialty or inv["specialty"] or None
    pw_hash = hash_password(password)
    cursor = await db.execute(
        "INSERT INTO users (email, password_hash, first_name, last_name, role, specialty) VALUES (?,?,?,?,?,?)",
        (email, pw_hash, first_name, last_name, inv["role"], final_specialty),
    )
    await db.commit()
    new_id = cursor.lastrowid
    await db.execute(
        "UPDATE invitations SET used_at=?, used_by=? WHERE token=?",
        (datetime.utcnow().isoformat(), new_id, token),
    )
    await db.commit()
    jwt = create_token(user_id=new_id, email=email, role=inv["role"], specialty=final_specialty, first_name=first_name, last_name=last_name)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="access_token", value=jwt, httponly=True, samesite="lax", max_age=8 * 3600)
    return response
