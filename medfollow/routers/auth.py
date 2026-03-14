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
        "SELECT id, email, password_hash, first_name, last_name, role FROM users WHERE email = ? AND is_active = 1",
        (email,),
    )
    row = await cursor.fetchone()

    if not row or not verify_password(password, row[2]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email ou mot de passe incorrect"},
        )

    token = create_token(user_id=row[0], email=row[1], role=row[5])
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

    if password != password_confirm:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Les mots de passe ne correspondent pas"},
        )

    if len(password) < 6:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Le mot de passe doit contenir au moins 6 caractères"},
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
