"""API JSON du parodontogramme (port de dentalpin `periodontogram/router.py`).

Préfixe /perio/{patient_id}/… — mêmes gardes que l'odontogramme.
"""
from __future__ import annotations

from typing import Literal, Optional

import aiosqlite
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from database.connection import get_db
from routers.dental import _owns_patient
from routers.deps import deny_secretaire
from services import perio_service as svc
from services.audit import client_ip, log_audit
from services.odonto_service import ApiError

router = APIRouter(prefix="/perio", dependencies=[Depends(deny_secretaire)])


class ToothPatch(BaseModel):
    is_present: Optional[bool] = None
    is_implant: Optional[bool] = None
    mobility: Optional[int] = Field(default=None, ge=0, le=3)
    prognosis: Optional[Literal["good", "fair", "poor", "hopeless"]] = None
    furcation_buccal: Optional[Literal["0", "I", "II", "III"]] = None
    furcation_lingual: Optional[Literal["0", "I", "II", "III"]] = None
    keratinized_gingiva_mm: Optional[int] = Field(default=None, ge=0, le=20)


class SitePatch(BaseModel):
    probing_depth_mm: Optional[int] = Field(default=None, ge=0, le=15)
    gingival_margin_mm: Optional[int] = Field(default=None, ge=-5, le=10)
    bleeding_on_probing: Optional[bool] = None
    plaque: Optional[bool] = None
    suppuration: Optional[bool] = None


def _err(exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": exc.message})


async def _guard(db: aiosqlite.Connection, patient_id: int, user: dict) -> JSONResponse | None:
    if not await _owns_patient(db, patient_id, user["sub"]):
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})
    return None


@router.get("/{patient_id}/timeline")
async def timeline(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                   db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    dates = await svc.get_timeline(db, patient_id)
    draft = await svc.get_active_draft(db, patient_id)
    return JSONResponse(content={"dates": dates, "draft": svc._summary(draft) if draft else None})


@router.get("/{patient_id}/draft")
async def get_draft(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                    db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    draft = await svc.get_active_draft(db, patient_id)
    if draft is None:
        return JSONResponse(content=None)
    return JSONResponse(content=await svc.serialize_snapshot(db, patient_id, draft["id"]))


@router.post("/{patient_id}/draft")
async def open_draft(request: Request, patient_id: int, user: dict = Depends(deny_secretaire),
                     db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        snap, created = await svc.get_or_create_draft(db, patient_id, user["sub"])
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    if created:
        await log_audit(db, user, "perio_session_ouverte", entity_type="perio_snapshot", entity_id=snap["id"],
                        patient_id=patient_id, ip=client_ip(request), details="brouillon créé")
    return JSONResponse(content=await svc.serialize_snapshot(db, patient_id, snap["id"]))


@router.get("/{patient_id}/snapshots/{snapshot_id}")
async def get_snapshot(request: Request, patient_id: int, snapshot_id: int, user: dict = Depends(deny_secretaire),
                       db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        return JSONResponse(content=await svc.serialize_snapshot(db, patient_id, snapshot_id))
    except ApiError as exc:
        return _err(exc)


@router.patch("/{patient_id}/snapshots/{snapshot_id}/teeth/{tooth_number}")
async def patch_tooth(request: Request, patient_id: int, snapshot_id: int, tooth_number: int, data: ToothPatch,
                      user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        tooth = await svc.update_tooth(db, patient_id, snapshot_id, tooth_number, data.model_dump(exclude_unset=True))
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    return JSONResponse(content=tooth)


@router.patch("/{patient_id}/snapshots/{snapshot_id}/teeth/{tooth_number}/sites/{site_code}")
async def patch_site(request: Request, patient_id: int, snapshot_id: int, tooth_number: int, site_code: str,
                     data: SitePatch, user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        site = await svc.update_site(db, patient_id, snapshot_id, tooth_number, site_code,
                                     data.model_dump(exclude_unset=True))
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    return JSONResponse(content=site)


@router.post("/{patient_id}/snapshots/{snapshot_id}/close")
async def close_snapshot(request: Request, patient_id: int, snapshot_id: int,
                         user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        detail = await svc.close_snapshot(db, patient_id, snapshot_id, user["sub"])
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    await log_audit(db, user, "perio_session_cloturee", entity_type="perio_snapshot", entity_id=snapshot_id,
                    patient_id=patient_id, ip=client_ip(request), details=str(detail.get("indices")))
    return JSONResponse(content=detail)


@router.get("/{patient_id}/snapshots/{snapshot_id}/indices")
async def snapshot_indices(request: Request, patient_id: int, snapshot_id: int,
                           user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        return JSONResponse(content=await svc.get_indices(db, patient_id, snapshot_id))
    except ApiError as exc:
        return _err(exc)


@router.delete("/{patient_id}/snapshots/{snapshot_id}")
async def discard_snapshot(request: Request, patient_id: int, snapshot_id: int,
                           user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if (bad := await _guard(db, patient_id, user)):
        return bad
    try:
        await svc.discard_draft(db, patient_id, snapshot_id)
        await db.commit()
    except ApiError as exc:
        return _err(exc)
    await log_audit(db, user, "perio_brouillon_abandonne", entity_type="perio_snapshot", entity_id=snapshot_id,
                    patient_id=patient_id, ip=client_ip(request), details="brouillon supprimé")
    return Response(status_code=204)
