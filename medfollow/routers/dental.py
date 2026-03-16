from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import aiosqlite
import json
from datetime import date

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/dental")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

TOOTH_NAMES = {
    11: "Incisive centrale sup. droite", 12: "Incisive latérale sup. droite",
    13: "Canine sup. droite", 14: "1ère prémolaire sup. droite",
    15: "2ème prémolaire sup. droite", 16: "1ère molaire sup. droite",
    17: "2ème molaire sup. droite", 18: "Dent de sagesse sup. droite",
    21: "Incisive centrale sup. gauche", 22: "Incisive latérale sup. gauche",
    23: "Canine sup. gauche", 24: "1ère prémolaire sup. gauche",
    25: "2ème prémolaire sup. gauche", 26: "1ère molaire sup. gauche",
    27: "2ème molaire sup. gauche", 28: "Dent de sagesse sup. gauche",
    31: "Incisive centrale inf. gauche", 32: "Incisive latérale inf. gauche",
    33: "Canine inf. gauche", 34: "1ère prémolaire inf. gauche",
    35: "2ème prémolaire inf. gauche", 36: "1ère molaire inf. gauche",
    37: "2ème molaire inf. gauche", 38: "Dent de sagesse inf. gauche",
    41: "Incisive centrale inf. droite", 42: "Incisive latérale inf. droite",
    43: "Canine inf. droite", 44: "1ère prémolaire inf. droite",
    45: "2ème prémolaire inf. droite", 46: "1ère molaire inf. droite",
    47: "2ème molaire inf. droite", 48: "Dent de sagesse inf. droite",
}


@router.get("/{patient_id}", response_class=HTMLResponse)
async def dental_chart(request: Request, patient_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    cursor = await db.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/patients", status_code=302)
    patient = dict(row)
    cursor = await db.execute("SELECT * FROM dental_teeth WHERE patient_id = ?", (patient_id,))
    teeth_rows = await cursor.fetchall()
    teeth_data = {str(r["tooth_number"]): dict(r) for r in teeth_rows}
    return templates.TemplateResponse("dental/chart.html", {
        "request": request, "user": user, "active": "patients",
        "patient": patient, "teeth_data_json": json.dumps(teeth_data),
    })


@router.get("/{patient_id}/tooth/{tooth_number}/data")
async def get_tooth_data(request: Request, patient_id: int, tooth_number: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    cursor = await db.execute("SELECT * FROM dental_teeth WHERE patient_id = ? AND tooth_number = ?", (patient_id, tooth_number))
    row = await cursor.fetchone()
    tooth = dict(row) if row else {"tooth_number": tooth_number, "condition": "sain", "notes": ""}
    cursor = await db.execute(
        "SELECT * FROM dental_treatments WHERE patient_id = ? AND tooth_number = ? ORDER BY treatment_date DESC",
        (patient_id, tooth_number)
    )
    treatments = [dict(r) for r in await cursor.fetchall()]
    return JSONResponse(content={
        "tooth": tooth, "treatments": treatments,
        "tooth_name": TOOTH_NAMES.get(tooth_number, f"Dent {tooth_number}")
    })


@router.post("/{patient_id}/tooth/{tooth_number}/condition")
async def update_tooth_condition(
    request: Request, patient_id: int, tooth_number: int,
    condition: str = Form(...), notes: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    await db.execute(
        """INSERT INTO dental_teeth (patient_id, tooth_number, condition, notes, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(patient_id, tooth_number) DO UPDATE SET
           condition=excluded.condition, notes=excluded.notes, updated_at=excluded.updated_at""",
        (patient_id, tooth_number, condition, notes or None)
    )
    await db.commit()
    return JSONResponse(content={"ok": True})


@router.post("/{patient_id}/tooth/{tooth_number}/treatment")
async def add_treatment(
    request: Request, patient_id: int, tooth_number: int,
    treatment_type: str = Form(...), description: str = Form(""), treatment_date: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    tdate = treatment_date or date.today().isoformat()
    await db.execute(
        "INSERT INTO dental_treatments (patient_id, tooth_number, treatment_type, description, treatment_date, doctor_id) VALUES (?, ?, ?, ?, ?, ?)",
        (patient_id, tooth_number, treatment_type, description or None, tdate, user["sub"])
    )
    await db.commit()
    return JSONResponse(content={"ok": True})


@router.post("/{patient_id}/tooth/{tooth_number}/treatment/{treatment_id}/delete")
async def delete_treatment(
    request: Request, patient_id: int, tooth_number: int, treatment_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    await db.execute("DELETE FROM dental_treatments WHERE id = ? AND patient_id = ?", (treatment_id, patient_id))
    await db.commit()
    return JSONResponse(content={"ok": True})
