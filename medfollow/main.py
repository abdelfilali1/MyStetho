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
from routers import auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices, dental


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    await init_db()
    await seed_db()
    print(f"\n  MyStetho démarré sur http://{HOST}:{PORT}\n")
    yield


app = FastAPI(title="MyStetho", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Add global template variables
from fastapi.templating import Jinja2Templates
from config import TEMPLATES_DIR
_global_templates = Jinja2Templates(directory=TEMPLATES_DIR)
_global_templates.env.globals["now_year"] = date.today().year

# Patch all router template envs to include now_year and calc_age filter
for mod in [auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices, dental]:
    if hasattr(mod, 'templates'):
        mod.templates.env.globals["now_year"] = date.today().year
        mod.templates.env.filters["calc_age"] = _calc_age
_global_templates.env.filters["calc_age"] = _calc_age

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


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)


