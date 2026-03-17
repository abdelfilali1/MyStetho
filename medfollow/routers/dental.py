from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite
import json
from datetime import date, datetime

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/dental")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Default canals per tooth type (FDI numbering)
ENDO_CANALS = {
    # Maxillary
    11: ["Canal unique"], 12: ["Canal unique"], 13: ["Canal unique"],
    14: ["Vestibulaire", "Palatin"], 15: ["Canal unique"],
    16: ["MV1", "MV2", "DV", "Palatin"], 17: ["MV", "DV", "Palatin"], 18: ["MV", "DV", "Palatin"],
    21: ["Canal unique"], 22: ["Canal unique"], 23: ["Canal unique"],
    24: ["Vestibulaire", "Palatin"], 25: ["Canal unique"],
    26: ["MV1", "MV2", "DV", "Palatin"], 27: ["MV", "DV", "Palatin"], 28: ["MV", "DV", "Palatin"],
    # Mandibular
    31: ["Canal unique"], 32: ["Canal unique"], 33: ["Canal unique"],
    34: ["Canal unique"], 35: ["Canal unique"],
    36: ["MV", "ML", "Distal"], 37: ["MV", "ML", "Distal"], 38: ["MV", "ML", "Distal"],
    41: ["Canal unique"], 42: ["Canal unique"], 43: ["Canal unique"],
    44: ["Canal unique"], 45: ["Canal unique"],
    46: ["MV", "ML", "Distal"], 47: ["MV", "ML", "Distal"], 48: ["MV", "ML", "Distal"],
}

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


# ===== ENDODONTIC ENDPOINTS =====

@router.get("/{patient_id}/endo/{tooth_number}")
async def get_endo_data(request: Request, patient_id: int, tooth_number: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    # Get canals
    cursor = await db.execute(
        "SELECT * FROM endo_canals WHERE patient_id = ? AND tooth_number = ? ORDER BY id",
        (patient_id, tooth_number)
    )
    canals = [dict(r) for r in await cursor.fetchall()]

    # If no canals exist, return defaults
    if not canals:
        default_names = ENDO_CANALS.get(tooth_number, ["Canal unique"])
        canals = [{"canal_name": n, "estimated_length": None, "working_length": None,
                    "final_length": None, "status": "non_localise", "notes": "", "updated_at": None}
                  for n in default_names]

    # Get history
    cursor = await db.execute(
        "SELECT eh.*, u.first_name || ' ' || u.last_name AS changed_by_name FROM endo_history eh LEFT JOIN users u ON eh.changed_by = u.id WHERE eh.patient_id = ? AND eh.tooth_number = ? ORDER BY eh.changed_at DESC LIMIT 50",
        (patient_id, tooth_number)
    )
    history = [dict(r) for r in await cursor.fetchall()]

    # Get general notes
    cursor = await db.execute(
        "SELECT general_notes FROM endo_notes WHERE patient_id = ? AND tooth_number = ?",
        (patient_id, tooth_number)
    )
    notes_row = await cursor.fetchone()
    general_notes = notes_row["general_notes"] if notes_row else ""

    return JSONResponse(content={
        "canals": canals,
        "history": history,
        "general_notes": general_notes or "",
        "tooth_name": TOOTH_NAMES.get(tooth_number, f"Dent {tooth_number}"),
        "default_canals": ENDO_CANALS.get(tooth_number, ["Canal unique"]),
    })


@router.post("/{patient_id}/endo/{tooth_number}/save")
async def save_endo_data(request: Request, patient_id: int, tooth_number: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    body = await request.json()
    canals_data = body.get("canals", [])
    general_notes = body.get("general_notes", "")

    for canal in canals_data:
        name = canal.get("canal_name", "")
        if not name:
            continue

        est = canal.get("estimated_length")
        wl = canal.get("working_length")
        fl = canal.get("final_length")
        status = canal.get("status", "non_localise")
        notes = canal.get("notes", "")

        # Validate lengths
        for val in [est, wl, fl]:
            if val is not None:
                try:
                    val_f = float(val)
                    if val_f < 0 or val_f > 40:
                        return JSONResponse(status_code=400, content={"error": f"Longueur invalide: {val}"})
                except (ValueError, TypeError):
                    return JSONResponse(status_code=400, content={"error": f"Valeur non numérique: {val}"})

        # Get old values for history
        cursor = await db.execute(
            "SELECT estimated_length, working_length, final_length, status FROM endo_canals WHERE patient_id = ? AND tooth_number = ? AND canal_name = ?",
            (patient_id, tooth_number, name)
        )
        old_row = await cursor.fetchone()

        # Upsert canal
        await db.execute(
            """INSERT INTO endo_canals (patient_id, tooth_number, canal_name, estimated_length, working_length, final_length, status, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(patient_id, tooth_number, canal_name) DO UPDATE SET
               estimated_length=excluded.estimated_length, working_length=excluded.working_length,
               final_length=excluded.final_length, status=excluded.status, notes=excluded.notes,
               updated_at=excluded.updated_at""",
            (patient_id, tooth_number, name, est, wl, fl, status, notes or None)
        )

        # Record history for changed fields
        if old_row:
            old = dict(old_row)
            field_map = {
                "estimated_length": ("Longueur estimée", est),
                "working_length": ("Longueur de travail", wl),
                "final_length": ("Longueur finale", fl),
                "status": ("Statut", status),
            }
            for field_key, (label, new_val) in field_map.items():
                old_val = old.get(field_key)
                old_str = str(old_val) if old_val is not None else None
                new_str = str(new_val) if new_val is not None else None
                if old_str != new_str:
                    await db.execute(
                        "INSERT INTO endo_history (patient_id, tooth_number, canal_name, field, old_value, new_value, changed_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (patient_id, tooth_number, name, label, old_str, new_str, user["sub"])
                    )

    # Save general notes
    await db.execute(
        """INSERT INTO endo_notes (patient_id, tooth_number, general_notes, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(patient_id, tooth_number) DO UPDATE SET
           general_notes=excluded.general_notes, updated_at=excluded.updated_at""",
        (patient_id, tooth_number, general_notes or None)
    )

    await db.commit()
    return JSONResponse(content={"ok": True})
