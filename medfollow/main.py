import sys
import os

# Ensure the application directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import HOST, PORT
from database.connection import init_db
from database.seed import seed_db
from routers import auth, dashboard, patients, appointments, consultations, prescriptions, documents, messages, invoices


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


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)


