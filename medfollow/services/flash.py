"""Messages flash (toast) après POST-redirect.

Le message est posé dans un cookie court ('flash') lu puis supprimé par le JS
global de base.html, qui l'affiche via window.showToast. Aucune signature
nécessaire : le contenu n'est qu'un texte d'affichage côté client.
"""
import json
import urllib.parse

from config import HTTPS_ENABLED


def set_flash(response, message: str, type_: str = "success") -> None:
    """Attache un message flash à une réponse (typiquement une RedirectResponse).

    type_: 'success' | 'error' | 'info' — mappe sur les classes toast-<type>.
    """
    payload = urllib.parse.quote(json.dumps({"m": message, "t": type_}, ensure_ascii=False))
    response.set_cookie(
        "flash", payload, max_age=20, samesite="lax", httponly=False, path="/",
        secure=HTTPS_ENABLED,
    )
