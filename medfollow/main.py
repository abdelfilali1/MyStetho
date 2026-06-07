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
from routers import auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices, dental, mutuelle, learning


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    await init_db()
    await seed_db()
    print(f"\n  MyStetho démarré sur http://{HOST}:{PORT}\n")
    yield


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
for mod in [auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices, dental, mutuelle, learning]:
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


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)


