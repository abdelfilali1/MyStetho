"""Journal d'audit des accès aux données de santé (loi 09-08 / RGPD).

Enregistre qui a consulté, exporté ou modifié quelle donnée patient.
Le journal est append-only : aucune route ne doit le modifier ni le purger.
"""
from typing import Optional

import aiosqlite


async def log_audit(
    db: aiosqlite.Connection,
    user: Optional[dict],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    patient_id: Optional[int] = None,
    ip: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Insère une entrée d'audit et commit immédiatement.

    Ne lève jamais : l'audit ne doit pas casser la requête métier.
    `user` est le payload JWT (clés sub/email) ou None (ex. échec de login).
    """
    try:
        await db.execute(
            """INSERT INTO audit_log (user_id, user_email, action, entity_type, entity_id, patient_id, ip, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user.get("sub") if user else None,
                user.get("email") if user else None,
                action,
                entity_type,
                entity_id,
                patient_id,
                ip,
                details,
            ),
        )
        await db.commit()
    except Exception:
        pass


def client_ip(request) -> str:
    """IP du client, en tenant compte d'un éventuel reverse proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""
