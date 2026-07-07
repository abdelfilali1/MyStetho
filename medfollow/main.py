import sys
import os

# Ensure the application directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from datetime import date
from config import HOST, PORT


def _calc_age(dob_str):
    """Return exact age in years from a YYYY-MM-DD string."""
    try:
        today = date.today()
        parts = str(dob_str).split("-")
        dob = date(int(parts[0]), int(parts[1]), int(parts[2]))
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        return ""
from database.connection import init_db
from database.seed import seed_db
from routers import auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices, dental, mutuelle, learning, rappels, whatsapp_webhook
from services import reminder_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup, then run the WhatsApp reminder loop."""
    await init_db()
    await seed_db()
    # Boucle de rappels WhatsApp 24h (mono-processus → pas de double déclenchement).
    reminder_scheduler.start(app)
    print(f"\n  MyStetho démarré sur http://{HOST}:{PORT}\n")
    yield
    await reminder_scheduler.stop(app)


app = FastAPI(title="MyStetho", lifespan=lifespan)


# Inject the active (en_cours) consultation into every rendered page so a global
# "Retour à la consultation" banner can be shown across all modules until the
# consultation is closed. Exposed to templates via request.state.active_consultation.
import aiosqlite as _aiosqlite
from config import DATABASE_PATH as _DATABASE_PATH
from routers.auth import get_current_user as _get_current_user


@app.middleware("http")
async def _inject_active_consultation(request, call_next):
    request.state.active_consultation = None
    try:
        path = request.url.path
        if request.method == "GET" and not path.startswith(("/static", "/health")):
            user = _get_current_user(request)
            if user:
                conn = await _aiosqlite.connect(_DATABASE_PATH)
                conn.row_factory = _aiosqlite.Row
                try:
                    cur = await conn.execute(
                        """SELECT c.id, c.patient_id, c.consultation_date,
                                  p.first_name, p.last_name
                           FROM consultations c
                           JOIN patients p ON c.patient_id = p.id
                           WHERE c.doctor_id = ? AND c.status = 'en_cours'
                           ORDER BY c.created_at DESC LIMIT 1""",
                        (user["sub"],),
                    )
                    row = await cur.fetchone()
                    if row:
                        request.state.active_consultation = dict(row)
                finally:
                    await conn.close()
    except Exception:
        request.state.active_consultation = None
    return await call_next(request)


# Security headers applied to every response. CSP intentionally allows the
# origins the app actually loads (Google Fonts, jsDelivr/FullCalendar) plus
# 'unsafe-inline' for the many inline <script>/<style> blocks the templates use.
from config import HTTPS_ENABLED as _HTTPS_ENABLED

_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    # Impression directe des PDF : l'iframe caché charge le PDF depuis un blob
    # same-origin (voir window.printPdf dans base.html).
    "frame-src 'self' blob:; "
    "img-src 'self' data: blob:; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "form-action 'self'"
)


@app.middleware("http")
async def _security_headers(request, call_next):
    response = await call_next(request)
    # Les PDF générés (ordonnance, devis, note…) doivent pouvoir être chargés
    # dans un iframe same-origin pour les boutons « Imprimer » (impression
    # directe). Un PDF est un contenu inerte : on autorise donc son cadrage
    # UNIQUEMENT par l'application elle-même ('self'), pas le cadrage général.
    is_pdf = "application/pdf" in response.headers.get("content-type", "")
    if is_pdf:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
    else:
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if _HTTPS_ENABLED:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    return response


# --- Protection CSRF (double-submit cookie + vérification Origin/Referer) ---
# Le cookie 'csrf_token' (lisible en JS) est posé automatiquement ; base.html
# injecte le jeton dans chaque formulaire POST et le wrapper fetch() ajoute
# l'en-tête X-CSRF-Token. Ce middleware valide les deux côté serveur.
import secrets as _secrets
from urllib.parse import parse_qs as _parse_qs, urlparse as _urlparse
from fastapi.responses import JSONResponse as _JSONResponse, HTMLResponse as _HTMLResponse

_CSRF_COOKIE = "csrf_token"
_UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _csrf_reject(request):
    msg = "Requête bloquée (protection CSRF). Rechargez la page et réessayez."
    if request.headers.get("x-requested-with") or "application/json" in request.headers.get("accept", ""):
        resp = _JSONResponse(status_code=403, content={"error": msg})
    else:
        resp = _HTMLResponse(
            "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'><title>403 — Doctivo</title></head>"
            f"<body style='font-family:sans-serif;padding:40px;'><h1>Requête bloquée</h1><p>{msg}</p>"
            "<p><a href='javascript:history.back()'>Retour</a></p></body></html>",
            status_code=403,
        )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _same_origin(value: str, hosts: set) -> bool:
    try:
        return _urlparse(value).netloc in hosts
    except Exception:
        return False


@app.middleware("http")
async def _csrf_protect(request, call_next):
    # /webhooks/ : POST externes (Meta WhatsApp) qui ne peuvent pas porter de
    # jeton CSRF ; ils sont authentifiés par signature HMAC dans le handler.
    if request.method in _UNSAFE_METHODS and not request.url.path.startswith(("/static", "/webhooks/")):
        # Derrière un reverse proxy (VM en HTTP), le Host vu par uvicorn peut
        # différer du nom public : on accepte aussi X-Forwarded-Host.
        hosts = {h for h in (request.headers.get("host"), request.headers.get("x-forwarded-host")) if h}
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        if origin and origin != "null":
            origin_ok = _same_origin(origin, hosts)
        elif referer:
            origin_ok = _same_origin(referer, hosts)
        else:
            origin_ok = None  # aucune info d'origine fournie par le client

        cookie_token = request.cookies.get(_CSRF_COOKIE, "")
        header_token = request.headers.get("x-csrf-token", "")
        ctype = request.headers.get("content-type", "")

        # Le jeton double-submit est la preuve PRIMAIRE (cryptographique) : un site
        # tiers ne peut pas lire le cookie pour forger le jeton. Il reste donc
        # obligatoire. La vérification Origin/Referer est une défense secondaire
        # et ne doit pas rejeter à tort un POST légitime derrière un proxy qui
        # réécrit Host (sinon la connexion casserait en production).
        token_ok = False
        if cookie_token and header_token:
            token_ok = _secrets.compare_digest(cookie_token, header_token)
        elif cookie_token and ctype.startswith("application/x-www-form-urlencoded"):
            body = await request.body()

            async def _replay():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = _replay  # rejoue le corps pour le handler
            try:
                form_token = (_parse_qs(body.decode("utf-8")).get(_CSRF_COOKIE) or [""])[0]
            except Exception:
                form_token = ""
            token_ok = bool(form_token) and _secrets.compare_digest(cookie_token, form_token)

        if ctype.startswith("multipart/form-data"):
            # Upload : le corps n'est pas bufferisé (gros fichiers) → on ne peut
            # pas lire le jeton de formulaire ; on exige un Origin/Referer présent
            # et concordant (+ cookie SameSite=lax comme filet).
            ok = origin_ok is True
        else:
            # Jeton valide requis. Si un Origin est fourni ET concorde, tant mieux ;
            # s'il concorde pas mais que le jeton est bon, on autorise quand même
            # (cas du proxy) — le jeton reste la garantie anti-CSRF.
            ok = token_ok
        if not ok:
            return _csrf_reject(request)
    response = await call_next(request)
    if _CSRF_COOKIE not in request.cookies:
        response.set_cookie(
            _CSRF_COOKIE,
            _secrets.token_urlsafe(32),
            samesite="lax",
            secure=_HTTPS_ENABLED,
            httponly=False,
            path="/",
            max_age=12 * 3600,
        )
    return response


# --- Gestion globale des erreurs : pages HTML brandées ou enveloppe JSON ---
import traceback as _traceback
from starlette.exceptions import HTTPException as _StarletteHTTPException
from fastapi.exceptions import RequestValidationError as _RequestValidationError
from fastapi.responses import RedirectResponse as _RedirectResponse
from fastapi.encoders import jsonable_encoder as _jsonable_encoder

_ERROR_TITLES = {
    400: ("Requête invalide", "La requête envoyée est incomplète ou mal formée."),
    401: ("Authentification requise", "Veuillez vous connecter pour accéder à cette page."),
    403: ("Accès refusé", "Vous n'avez pas les droits nécessaires pour accéder à cette page."),
    404: ("Page introuvable", "La page demandée n'existe pas ou a été déplacée."),
    500: ("Erreur interne", "Une erreur inattendue s'est produite. Si le problème persiste, contactez l'administrateur."),
}


def _wants_json(request) -> bool:
    if request.headers.get("x-requested-with"):
        return True
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return True
    return "/api/" in request.url.path


def _error_response(request, status_code: int, detail=None):
    title, default_msg = _ERROR_TITLES.get(status_code, _ERROR_TITLES[500])
    message = detail if (isinstance(detail, str) and detail and status_code != 500) else default_msg
    if _wants_json(request):
        return _JSONResponse(status_code=status_code, content={"error": message})
    try:
        user = _get_current_user(request)
    except Exception:
        user = None
    try:
        return _global_templates.TemplateResponse(
            "errors/error.html",
            {"request": request, "user": user, "code": status_code, "title": title, "message": message},
            status_code=status_code,
        )
    except Exception:
        return _HTMLResponse(f"<h1>{status_code} — {title}</h1><p>{message}</p>", status_code=status_code)


@app.exception_handler(_StarletteHTTPException)
async def _http_exception_handler(request, exc):
    # Les dépendances d'auth utilisent HTTPException(302/303, Location) comme redirection
    if 300 <= exc.status_code < 400 and exc.headers and exc.headers.get("Location"):
        return _RedirectResponse(url=exc.headers["Location"], status_code=exc.status_code)
    return _error_response(request, exc.status_code, exc.detail if isinstance(exc.detail, str) else None)


@app.exception_handler(_RequestValidationError)
async def _validation_exception_handler(request, exc):
    if _wants_json(request):
        return _JSONResponse(status_code=422, content={"error": "Requête invalide", "details": _jsonable_encoder(exc.errors())})
    return _error_response(request, 400)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):
    _traceback.print_exception(type(exc), exc, exc.__traceback__)
    return _error_response(request, 500)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Add global template variables
import json as _json
from fastapi.templating import Jinja2Templates
from config import TEMPLATES_DIR


def _from_json(value):
    """Jinja filter: parse a JSON string into a dict/list (empty dict on failure)."""
    try:
        return _json.loads(value) if value else {}
    except Exception:
        return {}


_global_templates = Jinja2Templates(directory=TEMPLATES_DIR)
_global_templates.env.globals["now_year"] = date.today().year

# Patch all router template envs to include now_year and calc_age/fromjson filters
for mod in [auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices, dental, mutuelle, learning, rappels]:
    if hasattr(mod, 'templates'):
        mod.templates.env.globals["now_year"] = date.today().year
        mod.templates.env.filters["calc_age"] = _calc_age
        mod.templates.env.filters["fromjson"] = _from_json
_global_templates.env.filters["calc_age"] = _calc_age
_global_templates.env.filters["fromjson"] = _from_json

# Static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(patients.router)
app.include_router(appointments.router)
app.include_router(consultations.router)
app.include_router(prescriptions.router)
app.include_router(documents.router)
app.include_router(messages.router)
app.include_router(invoices.router)
app.include_router(dental.router)
app.include_router(mutuelle.router)
app.include_router(learning.router)
app.include_router(rappels.router)
app.include_router(whatsapp_webhook.router)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)


