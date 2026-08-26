import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
import aiosqlite

from database.connection import get_db
from config import TEMPLATES_DIR, UPLOAD_DIR, HTTPS_ENABLED, ADMIN_EMAIL, PUBLIC_BASE_URL
from services.auth_service import hash_password, verify_password, create_token, decode_token
from services.rate_limit import retry_after, record_failure, reset as rate_limit_reset
from services.audit import log_audit, client_ip
from services.flash import set_flash

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

LETTERHEAD_DIR = os.path.join(UPLOAD_DIR, "letterheads")


def get_current_user(request: Request) -> dict | None:
    """Extract user from JWT cookie."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_token(token)


def require_admin(request: Request) -> dict:
    """Dependency enforcing that the request comes from an authenticated admin.

    Authorization must NOT rely on the nav link being hidden in the templates —
    every /admin/* route (and the reset-link / toggle-active / invite endpoints)
    is reachable by direct URL, so each one depends on this guard.

    - Not authenticated  -> redirect to /login (matches the rest of the app).
    - Authenticated, not admin -> 403 Forbidden.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé à l'administrateur")
    return user


async def _save_letterhead(upload: Optional[UploadFile], user_id: int) -> Optional[str]:
    """Validate + persist a per-user PDF letterhead. Returns the stored path, or
    None if no (valid) file was provided."""
    if not upload or not upload.filename:
        return None
    if not upload.filename.lower().endswith(".pdf"):
        return None
    content = await upload.read()
    if not content or not content[:5].startswith(b"%PDF"):
        return None
    os.makedirs(LETTERHEAD_DIR, exist_ok=True)
    path = os.path.join(LETTERHEAD_DIR, f"user_{user_id}.pdf")
    with open(path, "wb") as f:
        f.write(content)
    return path


def _delete_letterhead_file(path: Optional[str]) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


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

    # Anti force-brute : fenêtre glissante par IP et par compte
    ip = client_ip(request)
    wait = retry_after(f"login:ip:{ip}", max_attempts=20, window_seconds=900) or \
        retry_after(f"login:email:{email.lower()}", max_attempts=5, window_seconds=900)
    if wait:
        minutes = max(1, (wait + 59) // 60)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": f"Trop de tentatives. Réessayez dans {minutes} minute(s)."},
            status_code=429,
        )

    cursor = await db.execute(
        "SELECT id, email, password_hash, first_name, last_name, role, specialty, linked_doctor_id FROM users WHERE email = ? AND is_active = 1",
        (email,),
    )
    row = await cursor.fetchone()

    if not row or not verify_password(password, row[2]):
        record_failure(f"login:ip:{ip}")
        record_failure(f"login:email:{email.lower()}")
        await log_audit(db, None, "login_echec", ip=ip, details=f"email={email}")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email ou mot de passe incorrect"},
        )

    rate_limit_reset(f"login:email:{email.lower()}")
    await log_audit(db, {"sub": row[0], "email": row[1]}, "login", ip=ip)
    token = create_token(user_id=row[0], email=row[1], role=row[5], specialty=row[6], first_name=row[3], last_name=row[4], linked_doctor_id=row[7])
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=HTTPS_ENABLED,
        max_age=8 * 3600,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token", path="/", samesite="lax", secure=HTTPS_ENABLED)
    return response


@router.get("/admin/users", response_class=HTMLResponse)
async def list_users(request: Request, user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        """SELECT u.id, u.email, u.first_name, u.last_name, u.role, u.specialty, u.is_active, u.pdf_template_path,
                  d.first_name || ' ' || d.last_name
           FROM users u LEFT JOIN users d ON u.linked_doctor_id = d.id
           ORDER BY u.created_at"""
    )
    rows = await cursor.fetchall()
    users = [{"id": r[0], "email": r[1], "first_name": r[2], "last_name": r[3], "role": r[4], "specialty": r[5], "is_active": r[6], "has_template": bool(r[7]), "linked_doctor_name": r[8]} for r in rows]
    return templates.TemplateResponse("admin/users.html", {"request": request, "user": user, "users": users, "active": "admin_users"})


async def _get_doctors(db) -> list:
    """Praticiens auxquels une secrétaire peut être liée (médecins + admin praticien)."""
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') AND is_active = 1 ORDER BY last_name, first_name"
    )
    return [{"id": r[0], "first_name": r[1], "last_name": r[2]} for r in await cursor.fetchall()]


@router.get("/admin/users/new", response_class=HTMLResponse)
async def new_user_page(request: Request, user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
    doctors = await _get_doctors(db)
    return templates.TemplateResponse("admin/user_form.html", {"request": request, "user": user, "active": "admin_users", "error": None, "doctors": doctors})


@router.post("/admin/users/new", response_class=HTMLResponse)
async def create_user(
    request: Request,
    current_user: dict = Depends(require_admin),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    role: str = Form(...),
    specialty: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    whatsapp_enabled: str = Form(""),
    linked_doctor_id: str = Form(""),
    pdf_template: UploadFile = File(None),
    db: aiosqlite.Connection = Depends(get_db),
):
    async def error(msg):
        return templates.TemplateResponse("admin/user_form.html", {
            "request": request, "user": current_user, "active": "admin_users", "error": msg,
            "form": {"email": email, "first_name": first_name, "last_name": last_name, "role": role, "specialty": specialty, "phone": phone, "address": address, "whatsapp_enabled": whatsapp_enabled, "linked_doctor_id": linked_doctor_id},
            "doctors": await _get_doctors(db),
        })

    if role == "admin" and email != ADMIN_EMAIL:
        return await error("Le rôle admin est réservé à l'administrateur principal")
    if role != "secretaire" and not specialty:
        return await error("Veuillez choisir une spécialité")
    if password != password_confirm:
        return await error("Les mots de passe ne correspondent pas")
    if len(password) < 10:
        return await error("Le mot de passe doit contenir au moins 10 caractères")
    if pdf_template and pdf_template.filename and not pdf_template.filename.lower().endswith(".pdf"):
        return await error("Le modèle de document doit être un fichier PDF")

    # Secrétaire : liaison obligatoire à un praticien (cloisonnement des données)
    ldi = None
    if role == "secretaire":
        if not linked_doctor_id.strip().isdigit():
            return await error("Veuillez choisir le médecin lié à cette secrétaire")
        ldi = int(linked_doctor_id)
        cursor = await db.execute("SELECT 1 FROM users WHERE id = ? AND role IN ('medecin', 'admin') AND is_active = 1", (ldi,))
        if not await cursor.fetchone():
            return await error("Médecin lié invalide")

    cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
    if await cursor.fetchone():
        return await error("Cet email est déjà utilisé")

    wa_enabled_i = 1 if whatsapp_enabled in ("1", "on", "true", "yes") else 0
    pw_hash = hash_password(password)
    cursor = await db.execute(
        "INSERT INTO users (email, password_hash, first_name, last_name, role, specialty, phone, address, whatsapp_enabled, linked_doctor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (email, pw_hash, first_name, last_name, role, specialty or None, phone or None, address or None, wa_enabled_i, ldi),
    )
    new_user_id = cursor.lastrowid

    template_path = await _save_letterhead(pdf_template, new_user_id)
    if template_path:
        await db.execute("UPDATE users SET pdf_template_path = ? WHERE id = ?", (template_path, new_user_id))

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

    if email != ADMIN_EMAIL:
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
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", secure=HTTPS_ENABLED, max_age=8 * 3600)
    return response


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(request: Request, user_id: int, user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id, email, first_name, last_name, role, specialty, phone, is_active, pdf_template_path, linked_doctor_id, address, whatsapp_enabled FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/admin/users", status_code=302)
    edit_user = {"id": row[0], "email": row[1], "first_name": row[2], "last_name": row[3], "role": row[4], "specialty": row[5], "phone": row[6], "is_active": row[7], "has_template": bool(row[8]), "linked_doctor_id": row[9], "address": row[10], "whatsapp_enabled": row[11]}
    return templates.TemplateResponse("admin/user_form.html", {"request": request, "user": user, "active": "admin_users", "error": None, "form": edit_user, "editing": True, "doctors": await _get_doctors(db)})

@router.post("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def update_user(
    request: Request, user_id: int,
    current_user: dict = Depends(require_admin),
    email: str = Form(...), first_name: str = Form(...), last_name: str = Form(...),
    role: str = Form(...), specialty: str = Form(""), phone: str = Form(""),
    address: str = Form(""),
    whatsapp_enabled: str = Form(""),
    linked_doctor_id: str = Form(""),
    password: str = Form(""), password_confirm: str = Form(""),
    pdf_template: UploadFile = File(None), remove_pdf_template: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    form_data = {"id": user_id, "email": email, "first_name": first_name, "last_name": last_name, "role": role, "specialty": specialty, "phone": phone, "address": address, "whatsapp_enabled": whatsapp_enabled, "has_template": True, "linked_doctor_id": linked_doctor_id}
    async def error(msg):
        return templates.TemplateResponse("admin/user_form.html", {
            "request": request, "user": current_user, "active": "admin_users", "error": msg, "form": form_data, "editing": True,
            "doctors": await _get_doctors(db),
        })

    if role == "admin" and email != ADMIN_EMAIL:
        return await error("Le rôle admin est réservé à l'administrateur principal")
    if pdf_template and pdf_template.filename and not pdf_template.filename.lower().endswith(".pdf"):
        return await error("Le modèle de document doit être un fichier PDF")

    # Secrétaire : liaison obligatoire à un praticien ; effacée pour les autres rôles.
    # NB : la secrétaire devra se reconnecter pour que le changement prenne effet (JWT).
    ldi = None
    if role == "secretaire":
        if not linked_doctor_id.strip().isdigit():
            return await error("Veuillez choisir le médecin lié à cette secrétaire")
        ldi = int(linked_doctor_id)
        if ldi == user_id:
            return await error("Une secrétaire ne peut pas être liée à elle-même")
        cursor = await db.execute("SELECT 1 FROM users WHERE id = ? AND role IN ('medecin', 'admin') AND is_active = 1", (ldi,))
        if not await cursor.fetchone():
            return await error("Médecin lié invalide")

    if password:
        if password != password_confirm:
            return await error("Les mots de passe ne correspondent pas")
        if len(password) < 10:
            return await error("Le mot de passe doit contenir au moins 10 caractères")
        pw_hash = hash_password(password)
        await db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))

    # Letterhead / modèle PDF : suppression ou remplacement
    cur = await db.execute("SELECT pdf_template_path FROM users WHERE id = ?", (user_id,))
    trow = await cur.fetchone()
    current_tpl = trow[0] if trow else None
    if remove_pdf_template:
        _delete_letterhead_file(current_tpl)
        await db.execute("UPDATE users SET pdf_template_path = NULL WHERE id = ?", (user_id,))
    else:
        new_tpl = await _save_letterhead(pdf_template, user_id)
        if new_tpl:
            await db.execute("UPDATE users SET pdf_template_path = ? WHERE id = ?", (new_tpl, user_id))

    wa_enabled_i = 1 if whatsapp_enabled in ("1", "on", "true", "yes") else 0
    await db.execute(
        "UPDATE users SET email=?, first_name=?, last_name=?, role=?, specialty=?, phone=?, address=?, whatsapp_enabled=?, linked_doctor_id=? WHERE id=?",
        (email, first_name, last_name, role, specialty or None, phone or None, address or None, wa_enabled_i, ldi, user_id)
    )
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/admin/users/{user_id}/pdf-template")
async def view_user_pdf_template(request: Request, user_id: int, user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT pdf_template_path FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    path = row[0] if row else None
    if not path or not os.path.exists(path):
        return Response("Aucun modèle PDF pour cet utilisateur.", status_code=404)
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="modele_user_{user_id}.pdf"'})


@router.post("/admin/users/{user_id}/reset-password-link", response_class=HTMLResponse)
async def generate_reset_link(request: Request, user_id: int, current_user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
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
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    reset_link = f"{base_url}/reset-password/{token}"
    cursor = await db.execute("SELECT id, email, first_name, last_name, role, specialty, is_active, pdf_template_path FROM users ORDER BY created_at")
    rows = await cursor.fetchall()
    users = [{"id": r[0], "email": r[1], "first_name": r[2], "last_name": r[3], "role": r[4], "specialty": r[5], "is_active": r[6], "has_template": bool(r[7])} for r in rows]
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
    ip = client_ip(request)
    wait = retry_after(f"reset:ip:{ip}", max_attempts=10, window_seconds=900)
    if wait:
        return err(f"Trop de tentatives. Réessayez dans {max(1, (wait + 59) // 60)} minute(s).")
    if not row:
        record_failure(f"reset:ip:{ip}")
        return err("Lien invalide.")
    if row[2]:
        record_failure(f"reset:ip:{ip}")
        return err("Ce lien a déjà été utilisé.")
    if datetime.utcnow().isoformat() > row[1]:
        record_failure(f"reset:ip:{ip}")
        return err("Ce lien a expiré.")
    if password != password_confirm:
        return err("Les mots de passe ne correspondent pas.", valid=True)
    if len(password) < 10:
        return err("Le mot de passe doit contenir au moins 10 caractères.", valid=True)
    pw_hash = hash_password(password)
    await db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, row[0]))
    await db.execute("UPDATE password_resets SET used_at=? WHERE token=?", (datetime.utcnow().isoformat(), token))
    await db.commit()
    await log_audit(db, {"sub": row[0], "email": row[3]}, "reset_mot_de_passe", ip=ip)

    # Cette page s'ouvre dans une fenêtre à côté de Doctivo (bouton « Modifier le
    # mot de passe » de Mon compte). Elle partage donc les cookies de l'onglet
    # resté ouvert derrière : supprimer la session déconnecterait aussi cet
    # onglet, alors que la personne vient précisément de prouver qu'elle
    # contrôle le compte. On ne ferme la session que si elle n'était PAS déjà
    # connectée sur ce compte — cas du lien remis par l'administrateur.
    current = get_current_user(request)
    still_signed_in = bool(current and current.get("sub") == row[0])
    response = templates.TemplateResponse("reset_password.html", {
        "request": request, "error": None, "valid": False, "done": True,
        "token": token, "email": row[3], "still_signed_in": still_signed_in,
    })
    if not still_signed_in:
        response.delete_cookie("access_token", path="/", samesite="lax", secure=HTTPS_ENABLED)
    return response


@router.post("/admin/users/{user_id}/toggle-active")
async def toggle_user_active(request: Request, user_id: int, current_user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
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
async def invite_page(request: Request, user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
    invitations = await _get_invitations(db)
    return templates.TemplateResponse("admin/invite.html", {
        "request": request, "user": user, "active": "admin_users",
        "invitations": invitations, "new_link": None
    })


@router.post("/admin/invite", response_class=HTMLResponse)
async def create_invite(
    request: Request,
    user: dict = Depends(require_admin),
    role: str = Form("medecin"),
    specialty: str = Form(""),
    email: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat()
    await db.execute(
        "INSERT INTO invitations (token, email, role, specialty, created_by, expires_at) VALUES (?,?,?,?,?,?)",
        (token, email.strip() or None, role, specialty or None, user["sub"], expires_at),
    )
    await db.commit()
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    new_link = f"{base_url}/register/{token}"
    invitations = await _get_invitations(db)
    return templates.TemplateResponse("admin/invite.html", {
        "request": request, "user": user, "active": "admin_users",
        "invitations": invitations, "new_link": new_link
    })


@router.post("/admin/invite/{inv_id}/delete")
async def delete_invite(request: Request, inv_id: int, user: dict = Depends(require_admin), db: aiosqlite.Connection = Depends(get_db)):
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
    ip = client_ip(request)
    wait = retry_after(f"register:ip:{ip}", max_attempts=10, window_seconds=900)
    if wait:
        return templates.TemplateResponse("register.html", {"request": request, "error": f"Trop de tentatives. Réessayez dans {max(1, (wait + 59) // 60)} minute(s).", "inv": None, "token": token, "form": {}})
    cursor = await db.execute(
        "SELECT id, email, role, specialty, expires_at, used_at FROM invitations WHERE token = ?", (token,)
    )
    row = await cursor.fetchone()
    if not row:
        record_failure(f"register:ip:{ip}")
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
    response.set_cookie(key="access_token", value=jwt, httponly=True, samesite="lax", secure=HTTPS_ENABLED, max_age=8 * 3600)
    return response
