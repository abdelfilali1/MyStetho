"""« Mon compte » : le praticien gère lui-même sa fiche et son mot de passe.

Accessible depuis le bloc nom/e-mail en bas de la barre latérale.

Périmètre volontairement restreint : un utilisateur modifie ses **coordonnées**
(identité, e-mail, téléphone, adresse du cabinet, spécialité). Le rôle, l'état
actif/inactif et le médecin lié d'une secrétaire restent du ressort de
l'administrateur — les exposer ici ouvrirait une escalade de privilèges, chaque
route étant atteignable par URL directe.

Le mot de passe ne se change pas au formulaire : le bouton ouvre un **lien
magique** à usage unique dans une fenêtre dédiée. On réutilise la table
`password_resets` et la page `/reset-password/{token}` déjà en place, donc la
même expiration (1 h) et le même usage unique.
"""
import os
import re
import secrets
from datetime import datetime, timedelta

import aiosqlite
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import HTTPS_ENABLED, TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login
from services.audit import client_ip, log_audit
from services.auth_service import create_token
from services.flash import set_flash
from services.rate_limit import record_failure, retry_after

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Durée de validité du lien magique. Doit rester alignée sur le texte de l'e-mail
# et sur le message d'expiration de /reset-password/{token}.
LINK_HOURS = 1


async def _load_account(db, user_id: int) -> dict | None:
    cur = await db.execute(
        """SELECT id, email, first_name, last_name, role, specialty, phone, address,
                  pdf_template_path, linked_doctor_id, created_at
           FROM users WHERE id = ?""",
        (user_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    acc = {
        "id": row[0], "email": row[1], "first_name": row[2], "last_name": row[3],
        "role": row[4], "specialty": row[5], "phone": row[6], "address": row[7],
        "has_template": bool(row[8]), "linked_doctor_id": row[9], "created_at": row[10],
        "linked_doctor_name": None,
    }
    if acc["linked_doctor_id"]:
        cur = await db.execute(
            "SELECT first_name, last_name FROM users WHERE id = ?", (acc["linked_doctor_id"],)
        )
        d = await cur.fetchone()
        if d:
            acc["linked_doctor_name"] = f"Dr {d[1]} {d[0]}"
    return acc


def _render(request, user, account, **extra):
    ctx = {
        "request": request, "user": user, "active": "profile",
        "account": account, "form": account,
        "error": None,
        "link_hours": LINK_HOURS,
    }
    ctx.update(extra)
    return templates.TemplateResponse("profile.html", ctx)


@router.get("/mon-compte", response_class=HTMLResponse)
async def account_page(
    request: Request,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    account = await _load_account(db, user["sub"])
    if not account:
        return RedirectResponse(url="/logout", status_code=302)
    return _render(request, user, account)


@router.post("/mon-compte", response_class=HTMLResponse)
async def update_account(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    specialty: str = Form(""),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    account = await _load_account(db, user["sub"])
    if not account:
        return RedirectResponse(url="/logout", status_code=302)

    first_name = first_name.strip()
    last_name = last_name.strip()
    email = email.strip()
    phone = phone.strip()
    address = address.strip()
    specialty = specialty.strip()

    # Valeurs saisies conservées à l'affichage en cas d'erreur, sauf les champs
    # non modifiables ici (rôle, médecin lié, papier à en-tête) qui viennent de
    # la base : le formulaire ne peut pas les changer.
    submitted = dict(account)
    submitted.update({
        "first_name": first_name, "last_name": last_name, "email": email,
        "phone": phone, "address": address, "specialty": specialty,
    })

    def error(msg):
        return _render(request, user, account, form=submitted, error=msg)

    if not first_name or not last_name:
        return error("Le prénom et le nom sont obligatoires.")
    if not _EMAIL_RE.match(email):
        return error("Adresse e-mail invalide.")
    if account["role"] != "secretaire" and not specialty:
        return error("Veuillez choisir votre spécialité.")

    # L'e-mail de l'administrateur est adossé à la configuration du serveur
    # (ADMIN_EMAIL) : /setup et l'attribution du rôle admin s'y réfèrent. On
    # compare à l'adresse ACTUELLE du compte, pas à ADMIN_EMAIL : un admin dont
    # l'adresse diffère déjà de la configuration (installation reprise, valeur
    # par défaut jamais adaptée) doit rester capable de corriger son téléphone
    # ou son adresse de cabinet. Seul le CHANGEMENT d'e-mail lui est fermé.
    if account["role"] == "admin" and email != account["email"]:
        return error(
            "L'adresse e-mail du compte administrateur est liée à la configuration "
            "du serveur et ne peut pas être modifiée ici."
        )

    cur = await db.execute("SELECT id FROM users WHERE email = ? AND id != ?", (email, user["sub"]))
    if await cur.fetchone():
        return error("Cette adresse e-mail est déjà utilisée par un autre compte.")

    final_specialty = specialty or None if account["role"] != "secretaire" else account["specialty"]
    await db.execute(
        """UPDATE users SET first_name = ?, last_name = ?, email = ?, phone = ?,
                            address = ?, specialty = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (first_name, last_name, email, phone or None, address or None,
         final_specialty, user["sub"]),
    )
    await db.commit()
    await log_audit(db, user, "profil_modifie", entity_type="user", entity_id=user["sub"],
                    ip=client_ip(request))

    # Le nom, l'e-mail et la spécialité affichés partout (barre latérale, en-tête
    # des PDF) proviennent du JETON, pas de la base : sans réémission, la
    # modification ne serait visible qu'à la prochaine connexion.
    response = RedirectResponse(url="/mon-compte", status_code=302)
    response.set_cookie(
        key="access_token",
        value=create_token(
            user_id=user["sub"], email=email, role=account["role"],
            specialty=final_specialty, first_name=first_name, last_name=last_name,
            linked_doctor_id=account["linked_doctor_id"],
        ),
        httponly=True,
        samesite="lax",
        secure=HTTPS_ENABLED,
        max_age=8 * 3600,
    )
    set_flash(response, "Vos informations ont été enregistrées")
    return response


@router.post("/mon-compte/mot-de-passe", response_class=HTMLResponse)
async def open_password_link(
    request: Request,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Ouvre le lien à usage unique de changement de mot de passe.

    Le compte concerné n'est jamais choisi par le formulaire : il est lu en base
    pour la session en cours. Le lien ne peut donc pas être détourné vers un
    autre compte, et il n'y a pas d'énumération possible.

    Le formulaire vise une fenêtre dédiée (`target`) : on redirige simplement
    vers /reset-password/{token}, qui s'ouvre donc à côté de Doctivo. Le jeton
    garde ses garanties habituelles — usage unique, expiration à 1 h — de sorte
    qu'une URL restée dans l'historique ne vaut plus rien.
    """
    account = await _load_account(db, user["sub"])
    if not account:
        return RedirectResponse(url="/logout", status_code=302)

    ip = client_ip(request)
    # Chaque clic consomme un jeton : on tolère quelques essais (fenêtre fermée
    # par erreur, hésitation) sans laisser une boucle en générer indéfiniment.
    wait = retry_after(f"pwlink:user:{user['sub']}", max_attempts=6, window_seconds=900)
    if wait:
        minutes = max(1, (wait + 59) // 60)
        return _render(request, user, account,
                       error=f"Trop de demandes. Réessayez dans {minutes} minute(s).")
    record_failure(f"pwlink:user:{user['sub']}")

    # Une nouvelle demande périme les liens précédents encore valides : sinon
    # plusieurs liens actifs circuleraient en même temps pour un même compte.
    now = datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
        (now, user["sub"]),
    )
    token = secrets.token_urlsafe(32)
    await db.execute(
        "INSERT INTO password_resets (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user["sub"], (datetime.utcnow() + timedelta(hours=LINK_HOURS)).isoformat()),
    )
    await db.commit()
    await log_audit(db, user, "ouverture_lien_mot_de_passe", entity_type="user",
                    entity_id=user["sub"], ip=ip)

    # 303 : la réponse à un POST doit être suivie en GET par le navigateur.
    return RedirectResponse(url=f"/reset-password/{token}", status_code=303)


@router.get("/mon-compte/papier-en-tete")
async def own_letterhead(
    request: Request,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Aperçu de son PROPRE papier à en-tête (la route /admin/… est réservée aux admins)."""
    cur = await db.execute("SELECT pdf_template_path FROM users WHERE id = ?", (user["sub"],))
    row = await cur.fetchone()
    path = row[0] if row else None
    if not path or not os.path.exists(path):
        return Response("Aucun papier à en-tête n'est enregistré sur votre compte.", status_code=404)
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="papier-en-tete.pdf"'})
