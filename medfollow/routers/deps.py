"""Dépendances FastAPI partagées par tous les routers.

Remplace le boilerplate `user = get_current_user(request); if not user: ...`
répété dans chaque handler par des Depends() uniformes :

- require_login       → pages HTML : redirige vers /login si non connecté
- require_login_api   → endpoints JSON : 401 {"error": "Non authentifié"}
- deny_secretaire     → modules cliniques interdits au rôle secrétaire
- effective_doctor_id → id du médecin dont on voit les données (une secrétaire
                        voit les données de son médecin lié)
"""
from fastapi import HTTPException, Request

from routers.auth import get_current_user, require_admin  # noqa: F401 (re-export)
from services.flash import set_flash  # noqa: F401 (re-export)


def require_login(request: Request) -> dict:
    """Pour les routes qui rendent des pages HTML."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def require_login_api(request: Request) -> dict:
    """Pour les endpoints JSON (fetch). Rendu en {"error": ...} par le handler global."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user


def deny_secretaire(request: Request) -> dict:
    """Routes cliniques (consultations, ordonnances, dentaire, documents,
    facturation, mutuelle) inaccessibles au rôle secrétaire."""
    user = require_login(request)
    if user.get("role") == "secretaire":
        raise HTTPException(status_code=403, detail="Accès non autorisé pour le rôle secrétaire")
    return user


def effective_doctor_id(user: dict) -> int:
    """Le périmètre de données d'une secrétaire est celui de son médecin lié."""
    if user.get("role") == "secretaire" and user.get("linked_doctor_id"):
        return user["linked_doctor_id"]
    return user["sub"]
