"""API JSON de l'odontogramme (port de dentalpin `odontogram/router.py`).

Préfixe /odonto/{patient_id}/… — réservé aux praticiens (pas de secrétaire),
chaque appel vérifie que le patient appartient au médecin connecté.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from database.connection import get_db
from routers.dental import _owns_patient
from routers.deps import deny_secretaire
from services import odonto_service as svc
from services.audit import client_ip, log_audit
from services.odonto_constants import (
    CATALOG_CATEGORIES, CONDITION_COLORS, ODONTO_CATALOG, SURFACES, TOOTH_CONDITIONS, TREATMENT_DESCRIPTIONS_FR,
    catalog_label,
)
from services.odonto_service import ApiError

router = APIRouter(prefix="/odonto", dependencies=[Depends(deny_secretaire)])


# --- Schémas ---------------------------------------------------------------

class SurfaceUpdate(BaseModel):
    surface: str
    condition: str


class ToothUpdate(BaseModel):
    general_condition: Optional[str] = None
    surface_updates: Optional[list[SurfaceUpdate]] = None
    is_displaced: Optional[bool] = None
    is_rotated: Optional[bool] = None


class ToothInput(BaseModel):
    tooth_number: int
    role: Optional[str] = None
    surfaces: Optional[list[str]] = None


class TreatmentCreate(BaseModel):
    # Soit un type clinique de base, soit un acte du catalogue (qui fixe le type clinique).
    clinical_type: Optional[str] = None
    catalog_code: Optional[str] = None
    scope: Optional[str] = None
    arch: Optional[str] = None  # global_arch uniquement : upper | lower
    tooth_numbers: list[int] = Field(default_factory=list)
    teeth: Optional[list[ToothInput]] = None
    surfaces: Optional[list[str]] = None
    status: str = "planned"
    consultation_id: Optional[int] = None


class TreatmentUpdate(BaseModel):
    status: Optional[str] = None
    surfaces: Optional[list[str]] = None
    consultation_id: Optional[int] = None


class TreatmentPerform(BaseModel):
    consultation_id: Optional[int] = None


# --- Helpers ---------------------------------------------------------------

def _err(exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": exc.message})


async def _guard(db: aiosqlite.Connection, patient_id: int, user: dict) -> JSONResponse | None:
    if not await _owns_patient(db, patient_id, user["sub"]):
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})
    return None


def _treatment_details(t: dict) -> str:
    label = catalog_label(t.get("catalog_code"), t["clinical_type"])
    teeth = "-".join(str(x["tooth_number"]) for x in t.get("teeth", []))
    if not teeth and t.get("arch"):
        teeth = "arcade supérieure" if t["arch"] == "upper" else "arcade inférieure"
    return f"{label} {teeth} ({t['status']})"


# --- Dents -----------------------------------------------------------------

@router.get("/{patient_id}")
async def get_odontogram(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                         db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    data = await svc.get_odontogram(db, patient_id)
    return JSONResponse(content={
        "patient_id": patient_id, "teeth": data["teeth"], "treatments": data["treatments"],
        "condition_colors": CONDITION_COLORS, "available_conditions": TOOTH_CONDITIONS, "surfaces": SURFACES,
        # Catalogue d'actes pour la barre de traitements (équivalent de /catalog/odontogram-treatments).
        "catalog": ODONTO_CATALOG, "catalog_categories": CATALOG_CATEGORIES,
        # Descriptions cliniques des types de base (infobulles des boutons hors catalogue : Diagnostic).
        "type_descriptions": TREATMENT_DESCRIPTIONS_FR,
    })


@router.put("/{patient_id}/teeth/{tooth_number}")
@router.patch("/{patient_id}/teeth/{tooth_number}")
async def update_tooth(request: Request, patient_id: int, tooth_number: int, data: ToothUpdate,
                       user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        record = await svc.update_tooth(
            db, patient_id, tooth_number, user["sub"],
            general_condition=data.general_condition,
            surface_updates=[u.model_dump() for u in data.surface_updates] if data.surface_updates else None,
            is_displaced=data.is_displaced, is_rotated=data.is_rotated,
        )
        await svc.mirror_to_legacy(db, patient_id, user["sub"], [tooth_number])
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    await log_audit(db, user, "odonto_dent_modifiee", entity_type="odo_tooth", entity_id=tooth_number,
                    patient_id=patient_id, ip=client_ip(request), details=f"dent {tooth_number}")
    return JSONResponse(content=record)


@router.get("/{patient_id}/teeth/{tooth_number}/history")
async def tooth_history(request: Request, patient_id: int, tooth_number: int, user: dict = Depends(deny_secretaire),
                        db: aiosqlite.Connection = Depends(get_db),
                        page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    rows, total = await svc.get_history(db, patient_id, tooth_number, page, page_size)
    return JSONResponse(content={"data": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/{patient_id}/history")
async def patient_history(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                          db: aiosqlite.Connection = Depends(get_db),
                          page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    rows, total = await svc.get_history(db, patient_id, None, page, page_size)
    return JSONResponse(content={"data": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/{patient_id}/timeline")
async def timeline(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                   db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    dates = await svc.get_timeline_dates(db, patient_id)
    return JSONResponse(content={"dates": dates, "total": len(dates)})


@router.get("/{patient_id}/at")
async def odontogram_at(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                        db: aiosqlite.Connection = Depends(get_db), target: date = Query(..., alias="date")):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    data = await svc.get_odontogram_at_date(db, patient_id, target)
    return JSONResponse(content={"patient_id": patient_id, **data})


# --- Traitements -----------------------------------------------------------

@router.post("/{patient_id}/treatments", status_code=201)
async def create_treatment(request: Request, patient_id: int, data: TreatmentCreate,
                           user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        treatment = await svc.create_treatment(db, patient_id, user["sub"], data.model_dump())
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    await log_audit(db, user, "odonto_traitement_ajoute", entity_type="odo_treatment", entity_id=treatment["id"],
                    patient_id=patient_id, ip=client_ip(request), details=_treatment_details(treatment))
    return JSONResponse(status_code=201, content=treatment)


@router.get("/{patient_id}/treatments")
async def list_treatments(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                          db: aiosqlite.Connection = Depends(get_db),
                          status: Optional[str] = None, clinical_type: Optional[str] = None,
                          tooth_number: Optional[int] = None):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    rows = await svc.list_treatments(db, patient_id, status=status, clinical_type=clinical_type, tooth_number=tooth_number)
    return JSONResponse(content={"data": rows, "total": len(rows)})


@router.get("/{patient_id}/treatments/{treatment_id}")
async def get_treatment(request: Request, patient_id: int, treatment_id: int, user: dict = Depends(deny_secretaire),
                        db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    t = await svc.get_treatment(db, patient_id, treatment_id)
    if not t:
        return JSONResponse(status_code=404, content={"error": "Traitement introuvable"})
    return JSONResponse(content=t)


@router.put("/{patient_id}/treatments/{treatment_id}")
async def update_treatment(request: Request, patient_id: int, treatment_id: int, data: TreatmentUpdate,
                           user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        t = await svc.update_treatment(db, patient_id, user["sub"], treatment_id, status=data.status,
                                       surfaces=data.surfaces, consultation_id=data.consultation_id)
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    await log_audit(db, user, "odonto_traitement_modifie", entity_type="odo_treatment", entity_id=treatment_id,
                    patient_id=patient_id, ip=client_ip(request), details=_treatment_details(t))
    return JSONResponse(content=t)


@router.patch("/{patient_id}/treatments/{treatment_id}/perform")
async def perform_treatment(request: Request, patient_id: int, treatment_id: int,
                            data: Optional[TreatmentPerform] = None,
                            user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        t = await svc.perform_treatment(db, patient_id, user["sub"], treatment_id,
                                        consultation_id=data.consultation_id if data else None)
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    await log_audit(db, user, "odonto_traitement_realise", entity_type="odo_treatment", entity_id=treatment_id,
                    patient_id=patient_id, ip=client_ip(request), details=_treatment_details(t))
    return JSONResponse(content=t)


@router.delete("/{patient_id}/treatments/{treatment_id}")
async def delete_treatment(request: Request, patient_id: int, treatment_id: int,
                           user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    deleted = await svc.delete_treatment(db, patient_id, user["sub"], treatment_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "Traitement introuvable"})
    await db.commit()
    await log_audit(db, user, "odonto_traitement_supprime", entity_type="odo_treatment", entity_id=treatment_id,
                    patient_id=patient_id, ip=client_ip(request), details=f"traitement {treatment_id}")
    return Response(status_code=204)
