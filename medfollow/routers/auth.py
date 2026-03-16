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

    token = create_token(user_id=row[0], email=row[1], role=row[5], specialty=row[6])
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

    token = create_token(user_id=cursor.lastrowid, email=email, role="admin")
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

@router.post("/admin/users/{user_id}/toggle-active")
async def toggle_user_active(request: Request, user_id: int, db: aiosqlite.Connection = Depends(get_db)):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    await db.execute("UPDATE users SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)
