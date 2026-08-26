"""Service odontogramme (port de dentalpin `odontogram/service.py`) sur aiosqlite.

Modèle :
- odo_tooth_records   : état de la dent (general_condition, faces, position)
- odo_treatments      : acte clinique (1 ou N dents), status planned|performed, soft delete
- odo_treatment_teeth : membres d'un traitement (rôle pilier/pont, faces)
- odo_history         : journal des changements d'état de dent

Passerelle legacy : `migrate_legacy_odontogram` (une fois, idempotente par ligne
via `odo_synced`) et `mirror_to_legacy` (écriture miroir dans dental_teeth /
dental_condition_history / dental_treatments pour les consultations et le PDF).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, date, timezone

UTC = timezone.utc  # `datetime.UTC` n'existe qu'à partir de Python 3.11 (la VM est en 3.10)
from typing import Any, Iterable

import aiosqlite

from services.odonto_constants import (
    ATOMIC_MULTI_TOOTH_TYPES,
    CLINICAL_TO_LEGACY_PRIORITY,
    LEGACY_SURFACE_MAP,
    LEGACY_TO_CLINICAL,
    LEGACY_TREATMENT_TYPE_MAP,
    SCOPES,
    STATUSES,
    SURFACES,
    TOOTH_CONDITIONS,
    TREATMENT_LABELS_FR,
    contiguous_runs,
    get_tooth_type,
    is_valid_tooth_number,
    is_valid_treatment_type,
)


class ApiError(Exception):
    """Erreur métier convertie en JSON `{"error": message}` par les routers."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_iso(value: Any) -> str:
    """Convertit un horodatage legacy (`YYYY-MM-DD HH:MM:SS` ou `YYYY-MM-DD`) en ISO UTC `Z`."""
    if not value:
        return now_iso()
    s = str(value).strip()
    if len(s) == 10:
        return s + "T00:00:00Z"
    s = s.replace(" ", "T")
    if "." in s:
        s = s.split(".")[0]
    if not s.endswith("Z"):
        s += "Z"
    return s


def default_surfaces() -> dict[str, str]:
    return {s: "healthy" for s in SURFACES}


def _row_tooth(row: aiosqlite.Row) -> dict:
    d = dict(row)
    try:
        surfaces = json.loads(d.pop("surfaces_json") or "{}")
    except Exception:
        surfaces = {}
    base = default_surfaces()
    base.update({k: v for k, v in surfaces.items() if k in SURFACES})
    d["surfaces"] = base
    d["is_displaced"] = bool(d.get("is_displaced"))
    d["is_rotated"] = bool(d.get("is_rotated"))
    return d


async def _patient_doctor(db: aiosqlite.Connection, patient_id: int) -> int | None:
    cur = await db.execute("SELECT doctor_id FROM patients WHERE id = ?", (patient_id,))
    row = await cur.fetchone()
    return row["doctor_id"] if row else None


# ---------------------------------------------------------------------------
# Dents (ToothRecord)
# ---------------------------------------------------------------------------

async def get_teeth(db: aiosqlite.Connection, patient_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM odo_tooth_records WHERE patient_id = ? ORDER BY tooth_number", (patient_id,)
    )
    return [_row_tooth(r) for r in await cur.fetchall()]


async def get_tooth_record(db: aiosqlite.Connection, patient_id: int, tooth_number: int) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM odo_tooth_records WHERE patient_id = ? AND tooth_number = ?",
        (patient_id, tooth_number),
    )
    row = await cur.fetchone()
    return _row_tooth(row) if row else None


async def _add_history(
    db: aiosqlite.Connection, patient_id: int, tooth_number: int, change_type: str,
    surface: str | None, old: str | None, new: str | None, user_id: int | None, changed_at: str | None = None,
) -> None:
    await db.execute(
        """INSERT INTO odo_history (patient_id, tooth_number, change_type, surface, old_condition, new_condition, changed_by, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, tooth_number, change_type, surface, old, new, user_id, changed_at or now_iso()),
    )


async def update_tooth(
    db: aiosqlite.Connection, patient_id: int, tooth_number: int, user_id: int | None,
    general_condition: str | None = None, surface_updates: list[dict] | None = None,
    is_displaced: bool | None = None, is_rotated: bool | None = None, changed_at: str | None = None,
) -> dict:
    """Crée ou met à jour l'état d'une dent, avec journalisation (identique à dentalpin)."""
    if not is_valid_tooth_number(tooth_number):
        raise ApiError(400, f"Numéro de dent invalide : {tooth_number}")
    if general_condition is not None and general_condition not in TOOTH_CONDITIONS:
        raise ApiError(400, f"État invalide : {general_condition}")
    for upd in surface_updates or []:
        if upd.get("surface") not in SURFACES:
            raise ApiError(400, f"Face invalide : {upd.get('surface')}")
        if upd.get("condition") not in TOOTH_CONDITIONS:
            raise ApiError(400, f"État invalide : {upd.get('condition')}")

    ts = changed_at or now_iso()
    existing = await get_tooth_record(db, patient_id, tooth_number)
    if existing:
        if general_condition is not None and general_condition != existing["general_condition"]:
            await _add_history(db, patient_id, tooth_number, "general_condition", None,
                               existing["general_condition"], general_condition, user_id, ts)
            await db.execute(
                "UPDATE odo_tooth_records SET general_condition = ?, updated_at = ? WHERE id = ?",
                (general_condition, ts, existing["id"]),
            )
        if surface_updates:
            current = dict(existing["surfaces"])
            changed = False
            for upd in surface_updates:
                old = current.get(upd["surface"], "healthy")
                if upd["condition"] != old:
                    current[upd["surface"]] = upd["condition"]
                    changed = True
                    await _add_history(db, patient_id, tooth_number, "surface_update", upd["surface"],
                                       old, upd["condition"], user_id, ts)
            if changed:
                await db.execute(
                    "UPDATE odo_tooth_records SET surfaces_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(current), ts, existing["id"]),
                )
        if is_displaced is not None or is_rotated is not None:
            await db.execute(
                "UPDATE odo_tooth_records SET is_displaced = ?, is_rotated = ?, updated_at = ? WHERE id = ?",
                (
                    int(existing["is_displaced"] if is_displaced is None else is_displaced),
                    int(existing["is_rotated"] if is_rotated is None else is_rotated),
                    ts, existing["id"],
                ),
            )
    else:
        surfaces = default_surfaces()
        for upd in surface_updates or []:
            surfaces[upd["surface"]] = upd["condition"]
        gc = general_condition or "healthy"
        await db.execute(
            """INSERT INTO odo_tooth_records
               (patient_id, tooth_number, tooth_type, general_condition, surfaces_json, is_displaced, is_rotated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (patient_id, tooth_number, get_tooth_type(tooth_number), gc, json.dumps(surfaces),
             int(bool(is_displaced)), int(bool(is_rotated)), ts, ts),
        )
        await _add_history(db, patient_id, tooth_number, "created", None, None, gc, user_id, ts)
    record = await get_tooth_record(db, patient_id, tooth_number)
    assert record is not None
    return record


async def get_or_create_tooth_record(db: aiosqlite.Connection, patient_id: int, tooth_number: int, user_id: int | None) -> dict:
    rec = await get_tooth_record(db, patient_id, tooth_number)
    if rec:
        return rec
    return await update_tooth(db, patient_id, tooth_number, user_id)


# ---------------------------------------------------------------------------
# Historique / chronologie
# ---------------------------------------------------------------------------

async def get_history(
    db: aiosqlite.Connection, patient_id: int, tooth_number: int | None = None, page: int = 1, page_size: int = 50,
) -> tuple[list[dict], int]:
    where = "h.patient_id = ?"
    params: list[Any] = [patient_id]
    if tooth_number is not None:
        where += " AND h.tooth_number = ?"
        params.append(tooth_number)
    cur = await db.execute(f"SELECT COUNT(*) AS c FROM odo_history h WHERE {where}", params)
    total = (await cur.fetchone())["c"]
    cur = await db.execute(
        f"""SELECT h.*, u.first_name || ' ' || u.last_name AS changed_by_name
            FROM odo_history h LEFT JOIN users u ON u.id = h.changed_by
            WHERE {where} ORDER BY h.changed_at DESC, h.id DESC LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    )
    return [dict(r) for r in await cur.fetchall()], total


async def get_timeline_dates(db: aiosqlite.Connection, patient_id: int) -> list[dict]:
    dates: dict[str, int] = {}
    cur = await db.execute(
        "SELECT substr(changed_at, 1, 10) AS d, COUNT(*) AS c FROM odo_history WHERE patient_id = ? GROUP BY d",
        (patient_id,),
    )
    for r in await cur.fetchall():
        dates[r["d"]] = dates.get(r["d"], 0) + r["c"]
    cur = await db.execute(
        "SELECT substr(recorded_at, 1, 10) AS d, COUNT(*) AS c FROM odo_treatments WHERE patient_id = ? GROUP BY d",
        (patient_id,),
    )
    for r in await cur.fetchall():
        dates[r["d"]] = dates.get(r["d"], 0) + r["c"]
    return [{"date": d, "change_count": c} for d, c in sorted(dates.items())]


async def get_odontogram_at_date(db: aiosqlite.Connection, patient_id: int, target: date) -> dict:
    limit = target.isoformat() + "T23:59:59Z"
    cur = await db.execute(
        "SELECT * FROM odo_history WHERE patient_id = ? AND changed_at <= ? ORDER BY changed_at ASC, id ASC",
        (patient_id, limit),
    )
    teeth: dict[int, dict] = {}
    for e in await cur.fetchall():
        n = e["tooth_number"]
        t = teeth.setdefault(n, {
            "tooth_number": n,
            "tooth_type": "permanent" if n < 50 else "deciduous",
            "general_condition": "healthy",
            "surfaces": default_surfaces(),
            "is_displaced": False,
            "is_rotated": False,
        })
        if e["change_type"] in ("created", "general_condition") and e["new_condition"]:
            t["general_condition"] = e["new_condition"]
        elif e["change_type"] == "surface_update" and e["surface"] and e["new_condition"]:
            t["surfaces"][e["surface"]] = e["new_condition"]
    treatments = await list_treatments(
        db, patient_id, extra_where="t.recorded_at <= ? AND (t.deleted_at IS NULL OR t.deleted_at > ?)",
        extra_params=[limit, limit], include_deleted=True,
    )
    return {"teeth": list(teeth.values()), "treatments": treatments}


# ---------------------------------------------------------------------------
# Traitements
# ---------------------------------------------------------------------------

async def _attach_teeth(db: aiosqlite.Connection, treatments: list[dict]) -> list[dict]:
    if not treatments:
        return treatments
    ids = [t["id"] for t in treatments]
    by_id = {t["id"]: t for t in treatments}
    for t in treatments:
        t["teeth"] = []
    cur = await db.execute(
        f"SELECT * FROM odo_treatment_teeth WHERE treatment_id IN ({','.join('?' * len(ids))}) ORDER BY tooth_number",
        ids,
    )
    for r in await cur.fetchall():
        d = dict(r)
        raw = d.pop("surfaces_json", None)
        try:
            d["surfaces"] = json.loads(raw) if raw else None
        except Exception:
            d["surfaces"] = None
        by_id[d.pop("treatment_id")]["teeth"].append(d)
    return treatments


async def list_treatments(
    db: aiosqlite.Connection, patient_id: int, *, status: str | None = None, clinical_type: str | None = None,
    tooth_number: int | None = None, include_deleted: bool = False, extra_where: str | None = None,
    extra_params: list | None = None,
) -> list[dict]:
    where = ["t.patient_id = ?"]
    params: list[Any] = [patient_id]
    if not include_deleted:
        where.append("t.deleted_at IS NULL")
    if status:
        where.append("t.status = ?")
        params.append(status)
    if clinical_type:
        where.append("t.clinical_type = ?")
        params.append(clinical_type)
    if tooth_number is not None:
        where.append("EXISTS (SELECT 1 FROM odo_treatment_teeth tt WHERE tt.treatment_id = t.id AND tt.tooth_number = ?)")
        params.append(tooth_number)
    if extra_where:
        where.append(extra_where)
        params.extend(extra_params or [])
    cur = await db.execute(
        f"""SELECT t.*, u.first_name || ' ' || u.last_name AS performed_by_name
            FROM odo_treatments t LEFT JOIN users u ON u.id = t.performed_by
            WHERE {' AND '.join(where)} ORDER BY t.recorded_at DESC, t.id DESC""",
        params,
    )
    rows = [dict(r) for r in await cur.fetchall()]
    for r in rows:
        if r.get("performed_by") is None:
            r["performed_by_name"] = None
    return await _attach_teeth(db, rows)


async def get_treatment(db: aiosqlite.Connection, patient_id: int, treatment_id: int, include_deleted: bool = False) -> dict | None:
    rows = await list_treatments(
        db, patient_id, include_deleted=include_deleted, extra_where="t.id = ?", extra_params=[treatment_id]
    )
    return rows[0] if rows else None


async def get_odontogram(db: aiosqlite.Connection, patient_id: int) -> dict:
    return {"teeth": await get_teeth(db, patient_id), "treatments": await list_treatments(db, patient_id)}


def _validate_shape(data: dict) -> tuple[str, str, list[dict], str]:
    """Reprise de `TreatmentCreate.validate_shape` + `_build_teeth_inputs`.

    Retourne (clinical_type, scope, teeth_inputs, status)."""
    clinical_type = data.get("clinical_type")
    if not clinical_type or not is_valid_treatment_type(clinical_type):
        raise ApiError(400, f"Type de traitement invalide : {clinical_type}")
    status = data.get("status") or "planned"
    if status not in STATUSES:
        raise ApiError(400, f"Statut invalide : {status}")

    common_surfaces = data.get("surfaces")
    if common_surfaces is not None:
        for s in common_surfaces:
            if s not in SURFACES:
                raise ApiError(400, f"Face invalide : {s}")

    teeth_inputs: list[dict] = []
    if data.get("teeth"):
        for t in data["teeth"]:
            n = int(t.get("tooth_number", 0))
            role = t.get("role")
            surfaces = t.get("surfaces") if t.get("surfaces") is not None else common_surfaces
            if role is not None and role not in ("pillar", "pontic"):
                raise ApiError(400, f"Rôle invalide : {role}")
            teeth_inputs.append({"tooth_number": n, "role": role, "surfaces": surfaces})
    else:
        for n in data.get("tooth_numbers") or []:
            teeth_inputs.append({"tooth_number": int(n), "role": None, "surfaces": common_surfaces})

    nums = [t["tooth_number"] for t in teeth_inputs]
    for n in nums:
        if not is_valid_tooth_number(n):
            raise ApiError(400, f"Numéro de dent invalide : {n}")
    if len(nums) != len(set(nums)):
        raise ApiError(400, "Dents en double")
    for t in teeth_inputs:
        for s in t["surfaces"] or []:
            if s not in SURFACES:
                raise ApiError(400, f"Face invalide : {s}")

    count = len(teeth_inputs)
    scope = data.get("scope")
    if scope is None:
        if count == 0:
            raise ApiError(400, "Aucune dent sélectionnée")
        scope = "tooth" if count == 1 else "multi_tooth"
    if scope not in SCOPES:
        raise ApiError(400, f"Portée invalide : {scope}")
    if scope in ("global_mouth", "global_arch"):
        raise ApiError(400, "Traitements globaux non pris en charge")
    if scope == "tooth" and count != 1:
        raise ApiError(400, "scope=tooth requiert exactement une dent")
    if scope == "multi_tooth" and count < 2:
        raise ApiError(400, "scope=multi_tooth requiert au moins deux dents")
    if clinical_type in ATOMIC_MULTI_TOOTH_TYPES and count < 2:
        raise ApiError(400, f"{TREATMENT_LABELS_FR.get(clinical_type, clinical_type)} : au moins deux dents requises")
    return clinical_type, scope, teeth_inputs, status


def _assign_roles(teeth_inputs: list[dict], clinical_type: str) -> list[dict]:
    if clinical_type != "bridge":
        return teeth_inputs
    sorted_teeth = sorted(teeth_inputs, key=lambda x: x["tooth_number"])
    if any(t.get("role") in ("pillar", "pontic") for t in sorted_teeth):
        for t in sorted_teeth:
            if t.get("role") not in ("pillar", "pontic"):
                t["role"] = "pontic"
    else:
        first, last = sorted_teeth[0]["tooth_number"], sorted_teeth[-1]["tooth_number"]
        for t in sorted_teeth:
            t["role"] = "pillar" if t["tooth_number"] in (first, last) else "pontic"
    if not any(t["role"] == "pillar" for t in sorted_teeth):
        raise ApiError(400, "Le bridge nécessite au moins une dent pilier.")
    return sorted_teeth


async def _insert_treatment(
    db: aiosqlite.Connection, patient_id: int, user_id: int | None, clinical_type: str, scope: str,
    teeth_inputs: list[dict], status: str, *, recorded_at: str | None = None, performed_at: str | None = None,
    performed_by: int | None = None, consultation_id: int | None = None, source_module: str = "odontogram",
) -> int:
    ts = recorded_at or now_iso()
    is_performed = status == "performed"
    cur = await db.execute(
        """INSERT INTO odo_treatments
           (patient_id, clinical_type, scope, arch, status, recorded_at, performed_at, performed_by,
            source_module, consultation_id, created_at, updated_at)
           VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, clinical_type, scope, status, ts,
         (performed_at or ts) if is_performed else None,
         (performed_by if performed_by is not None else user_id) if is_performed else None,
         source_module, consultation_id, ts, ts),
    )
    treatment_id = cur.lastrowid
    for t in teeth_inputs:
        rec = await get_or_create_tooth_record(db, patient_id, t["tooth_number"], user_id)
        await db.execute(
            """INSERT INTO odo_treatment_teeth (treatment_id, tooth_record_id, tooth_number, role, surfaces_json)
               VALUES (?, ?, ?, ?, ?)""",
            (treatment_id, rec["id"], t["tooth_number"], t.get("role"),
             json.dumps(t["surfaces"]) if t.get("surfaces") else None),
        )
    return treatment_id


async def create_treatment(db: aiosqlite.Connection, patient_id: int, user_id: int, data: dict) -> dict:
    clinical_type, scope, teeth_inputs, status = _validate_shape(data)
    teeth_inputs = _assign_roles(teeth_inputs, clinical_type)
    consultation_id = data.get("consultation_id")
    tid = await _insert_treatment(db, patient_id, user_id, clinical_type, scope, teeth_inputs, status,
                                  consultation_id=consultation_id)
    treatment = await get_treatment(db, patient_id, tid)
    assert treatment is not None
    await mirror_to_legacy(db, patient_id, user_id, [t["tooth_number"] for t in teeth_inputs],
                           consultation_id, created_treatment=treatment)
    return treatment


async def update_treatment(
    db: aiosqlite.Connection, patient_id: int, user_id: int, treatment_id: int,
    status: str | None = None, surfaces: list[str] | None = None, consultation_id: int | None = None,
) -> dict:
    treatment = await get_treatment(db, patient_id, treatment_id)
    if not treatment:
        raise ApiError(404, "Traitement introuvable")
    ts = now_iso()
    if status is not None:
        if status not in STATUSES:
            raise ApiError(400, f"Statut invalide : {status}")
        if status != treatment["status"]:
            if status == "performed":
                await db.execute(
                    "UPDATE odo_treatments SET status = ?, performed_at = ?, performed_by = ?, updated_at = ? WHERE id = ?",
                    (status, ts, user_id, ts, treatment_id),
                )
            else:
                await db.execute(
                    "UPDATE odo_treatments SET status = ?, performed_at = NULL, performed_by = NULL, updated_at = ? WHERE id = ?",
                    (status, ts, treatment_id),
                )
    if surfaces is not None:
        for s in surfaces:
            if s not in SURFACES:
                raise ApiError(400, f"Face invalide : {s}")
        await db.execute(
            "UPDATE odo_treatment_teeth SET surfaces_json = ? WHERE treatment_id = ?",
            (json.dumps(list(surfaces)) if surfaces else None, treatment_id),
        )
        await db.execute("UPDATE odo_treatments SET updated_at = ? WHERE id = ?", (ts, treatment_id))
    updated = await get_treatment(db, patient_id, treatment_id)
    assert updated is not None
    await mirror_to_legacy(db, patient_id, user_id, [t["tooth_number"] for t in updated["teeth"]], consultation_id)
    return updated


async def perform_treatment(db: aiosqlite.Connection, patient_id: int, user_id: int, treatment_id: int,
                            consultation_id: int | None = None) -> dict:
    return await update_treatment(db, patient_id, user_id, treatment_id, status="performed", consultation_id=consultation_id)


async def delete_treatment(db: aiosqlite.Connection, patient_id: int, user_id: int, treatment_id: int) -> bool:
    treatment = await get_treatment(db, patient_id, treatment_id)
    if not treatment:
        return False
    await db.execute("UPDATE odo_treatments SET deleted_at = ?, updated_at = ? WHERE id = ?",
                     (now_iso(), now_iso(), treatment_id))
    await mirror_to_legacy(db, patient_id, user_id, [t["tooth_number"] for t in treatment["teeth"]],
                           treatment.get("consultation_id"), deleted_treatment_id=treatment_id)
    return True


# ---------------------------------------------------------------------------
# Miroir vers les anciennes tables (consultations, PDF patient)
# ---------------------------------------------------------------------------

def _legacy_condition_for(record: dict | None, performed_types: Iterable[str]) -> str:
    types = set(performed_types)
    if record and record.get("general_condition") == "missing":
        types.add("missing")
    for group, legacy in CLINICAL_TO_LEGACY_PRIORITY:
        if types & group:
            return legacy
    return "sain"


async def mirror_to_legacy(
    db: aiosqlite.Connection, patient_id: int, user_id: int | None, tooth_numbers: list[int],
    consultation_id: int | None = None, created_treatment: dict | None = None,
    deleted_treatment_id: int | None = None,
) -> None:
    for n in sorted(set(tooth_numbers)):
        cur = await db.execute(
            """SELECT t.clinical_type FROM odo_treatments t
               JOIN odo_treatment_teeth tt ON tt.treatment_id = t.id
               WHERE t.patient_id = ? AND tt.tooth_number = ? AND t.status = 'performed' AND t.deleted_at IS NULL""",
            (patient_id, n),
        )
        performed = [r["clinical_type"] for r in await cur.fetchall()]
        record = await get_tooth_record(db, patient_id, n)
        condition = _legacy_condition_for(record, performed)
        cur = await db.execute("SELECT condition FROM dental_teeth WHERE patient_id = ? AND tooth_number = ?", (patient_id, n))
        prev = await cur.fetchone()
        prev_condition = prev["condition"] if prev else None
        if prev is None:
            if condition == "sain":
                continue
            await db.execute(
                "INSERT INTO dental_teeth (patient_id, tooth_number, condition, updated_at, odo_synced) VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)",
                (patient_id, n, condition),
            )
        elif prev_condition != condition:
            await db.execute(
                "UPDATE dental_teeth SET condition = ?, updated_at = CURRENT_TIMESTAMP, odo_synced = 1 WHERE patient_id = ? AND tooth_number = ?",
                (condition, patient_id, n),
            )
        if prev_condition != condition:
            await db.execute(
                """INSERT INTO dental_condition_history (patient_id, tooth_number, condition, changed_by, consultation_id, odo_synced)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (patient_id, n, condition, user_id, consultation_id),
            )
    if created_treatment:
        label = TREATMENT_LABELS_FR.get(created_treatment["clinical_type"], created_treatment["clinical_type"])
        tdate = (created_treatment.get("performed_at") or created_treatment.get("recorded_at") or now_iso())[:10]
        for t in created_treatment["teeth"]:
            await db.execute(
                """INSERT INTO dental_treatments
                   (patient_id, tooth_number, treatment_type, treatment_date, doctor_id, consultation_id, odo_treatment_id, odo_synced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (patient_id, t["tooth_number"], label, tdate, user_id, consultation_id, created_treatment["id"]),
            )
    if deleted_treatment_id is not None:
        await db.execute("DELETE FROM dental_treatments WHERE odo_treatment_id = ?", (deleted_treatment_id,))


# ---------------------------------------------------------------------------
# Migration unique des anciennes tables
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.lower()).strip()


def _legacy_treatment_type(raw: str) -> str | None:
    n = _normalize(raw)
    for fragment, ctype in LEGACY_TREATMENT_TYPE_MAP:
        if fragment in n:
            return ctype
    return None


async def _has_treatment(db: aiosqlite.Connection, patient_id: int, tooth_number: int, clinical_type: str) -> dict | None:
    rows = await list_treatments(db, patient_id, clinical_type=clinical_type, tooth_number=tooth_number)
    return rows[0] if rows else None


async def _create_bridges(db, patient_id: int, doctor_id: int | None, bridge_teeth: list[int], ts: str, status: str,
                          consultation_id: int | None = None) -> None:
    """Groupe les dents `bridge` en séquences contiguës (≥ 2 → bridge, isolée → couronne)."""
    seen: set[int] = set()
    for run in contiguous_runs(bridge_teeth):
        seen.update(run)
        if len(run) >= 2:
            if await _has_treatment(db, patient_id, run[0], "bridge"):
                continue
            inputs = _assign_roles([{"tooth_number": n, "role": None, "surfaces": None} for n in run], "bridge")
            await _insert_treatment(db, patient_id, doctor_id, "bridge", "multi_tooth", inputs, status,
                                    recorded_at=ts, performed_at=ts, performed_by=doctor_id,
                                    consultation_id=consultation_id, source_module="legacy_migration")
        else:
            n = run[0]
            if not await _has_treatment(db, patient_id, n, "crown"):
                await _insert_treatment(db, patient_id, doctor_id, "crown", "tooth",
                                        [{"tooth_number": n, "role": None, "surfaces": None}], status,
                                        recorded_at=ts, performed_at=ts, performed_by=doctor_id,
                                        consultation_id=consultation_id, source_module="legacy_migration")
    for n in bridge_teeth:
        if n not in seen and is_valid_tooth_number(n) and not await _has_treatment(db, patient_id, n, "crown"):
            await _insert_treatment(db, patient_id, doctor_id, "crown", "tooth",
                                    [{"tooth_number": n, "role": None, "surfaces": None}], status,
                                    recorded_at=ts, performed_at=ts, performed_by=doctor_id,
                                    consultation_id=consultation_id, source_module="legacy_migration")


async def migrate_legacy_odontogram(db: aiosqlite.Connection) -> dict:
    """Convertit une fois les données dental_* (lignes `odo_synced = 0`) vers le nouveau modèle."""
    # init_db() ouvre sa connexion sans row_factory : on impose Row le temps de la migration.
    previous_factory = db.row_factory
    db.row_factory = aiosqlite.Row
    try:
        return await _migrate_legacy_odontogram(db)
    finally:
        db.row_factory = previous_factory


async def _migrate_legacy_odontogram(db: aiosqlite.Connection) -> dict:
    stats = {"teeth": 0, "surfaces": 0, "history": 0, "treatments": 0, "skipped_treatments": 0}

    # 1. dental_teeth -> état + traitement réalisé
    cur = await db.execute(
        "SELECT * FROM dental_teeth WHERE COALESCE(odo_synced, 0) = 0 ORDER BY patient_id, tooth_number"
    )
    rows = [dict(r) for r in await cur.fetchall()]
    by_patient: dict[int, list[dict]] = {}
    for r in rows:
        by_patient.setdefault(r["patient_id"], []).append(r)
    for pid, prows in by_patient.items():
        doctor_id = await _patient_doctor(db, pid)
        bridge_teeth: list[int] = []
        bridge_ts = now_iso()
        for r in prows:
            n = r["tooth_number"]
            cond = (r.get("condition") or "sain").strip()
            ts = to_iso(r.get("updated_at"))
            if is_valid_tooth_number(n) and cond in LEGACY_TO_CLINICAL:
                gc, ctype = LEGACY_TO_CLINICAL[cond]
                if gc:
                    await update_tooth(db, pid, n, doctor_id, general_condition=gc, changed_at=ts)
                if ctype == "bridge":
                    bridge_teeth.append(n)
                    bridge_ts = ts
                elif ctype and not await _has_treatment(db, pid, n, ctype):
                    await _insert_treatment(db, pid, doctor_id, ctype, "tooth",
                                            [{"tooth_number": n, "role": None, "surfaces": None}], "performed",
                                            recorded_at=ts, performed_at=ts, performed_by=doctor_id,
                                            source_module="legacy_migration")
            await db.execute("UPDATE dental_teeth SET odo_synced = 1 WHERE id = ?", (r["id"],))
            stats["teeth"] += 1
        if bridge_teeth:
            await _create_bridges(db, pid, doctor_id, bridge_teeth, bridge_ts, "performed")
        await db.commit()

    # 2. dental_tooth_surfaces -> faces + traitements de surface
    cur = await db.execute(
        "SELECT * FROM dental_tooth_surfaces WHERE COALESCE(odo_synced, 0) = 0 ORDER BY patient_id, tooth_number, surface"
    )
    srows = [dict(r) for r in await cur.fetchall()]
    grouped: dict[tuple[int, int, str], list[dict]] = {}
    for r in srows:
        cond = (r.get("condition") or "sain").strip()
        grouped.setdefault((r["patient_id"], r["tooth_number"], cond), []).append(r)
    touched_patients: set[int] = set()
    for (pid, n, cond), group in grouped.items():
        doctor_id = await _patient_doctor(db, pid)
        surfaces = sorted({LEGACY_SURFACE_MAP.get(r["surface"], "") for r in group} - {""})
        ts = to_iso(max((r.get("updated_at") or "") for r in group))
        if is_valid_tooth_number(n) and cond in LEGACY_TO_CLINICAL and surfaces:
            gc, ctype = LEGACY_TO_CLINICAL[cond]
            if gc:
                await update_tooth(db, pid, n, doctor_id,
                                   surface_updates=[{"surface": s, "condition": gc} for s in surfaces], changed_at=ts)
            if ctype and ctype in ("caries", "filling_composite", "filling_amalgam"):
                existing = await _has_treatment(db, pid, n, ctype)
                if existing:
                    member = existing["teeth"][0]
                    merged = sorted(set(member.get("surfaces") or []) | set(surfaces))
                    await db.execute("UPDATE odo_treatment_teeth SET surfaces_json = ? WHERE id = ?",
                                     (json.dumps(merged), member["id"]))
                else:
                    await _insert_treatment(db, pid, doctor_id, ctype, "tooth",
                                            [{"tooth_number": n, "role": None, "surfaces": surfaces}], "performed",
                                            recorded_at=ts, performed_at=ts, performed_by=doctor_id,
                                            source_module="legacy_migration")
            elif ctype == "bridge":
                await _create_bridges(db, pid, doctor_id, [n], ts, "performed")
            elif ctype and not await _has_treatment(db, pid, n, ctype):
                await _insert_treatment(db, pid, doctor_id, ctype, "tooth",
                                        [{"tooth_number": n, "role": None, "surfaces": None}], "performed",
                                        recorded_at=ts, performed_at=ts, performed_by=doctor_id,
                                        source_module="legacy_migration")
        for r in group:
            await db.execute("UPDATE dental_tooth_surfaces SET odo_synced = 1 WHERE id = ?", (r["id"],))
            stats["surfaces"] += 1
        touched_patients.add(pid)
    if touched_patients:
        await db.commit()

    # 3. dental_condition_history -> odo_history (chronologie)
    cur = await db.execute(
        "SELECT * FROM dental_condition_history WHERE COALESCE(odo_synced, 0) = 0 ORDER BY changed_at, id"
    )
    hrows = [dict(r) for r in await cur.fetchall()]
    for r in hrows:
        cond = (r.get("condition") or "").strip()
        n = r["tooth_number"]
        if is_valid_tooth_number(n) and cond in LEGACY_TO_CLINICAL:
            gc, _ = LEGACY_TO_CLINICAL[cond]
            surface = LEGACY_SURFACE_MAP.get(r.get("surface") or "", None)
            await _add_history(db, r["patient_id"], n, "surface_update" if surface else "general_condition",
                               surface, None, gc or "healthy", r.get("changed_by"), to_iso(r.get("changed_at")))
        await db.execute("UPDATE dental_condition_history SET odo_synced = 1 WHERE id = ?", (r["id"],))
        stats["history"] += 1
    if hrows:
        await db.commit()

    # 4. dental_treatments -> traitements (planifiés si RDV à venir)
    cur = await db.execute(
        """SELECT dt.*, a.status AS appt_status FROM dental_treatments dt
           LEFT JOIN appointments a ON a.id = dt.appointment_id
           WHERE COALESCE(dt.odo_synced, 0) = 0 AND dt.odo_treatment_id IS NULL
           ORDER BY dt.patient_id, dt.treatment_date, dt.id"""
    )
    trows = [dict(r) for r in await cur.fetchall()]
    pending_bridges: dict[tuple[int, str, str | None, int | None], list[int]] = {}
    for r in trows:
        n = r["tooth_number"]
        ctype = _legacy_treatment_type(r.get("treatment_type") or "")
        status = "planned" if (r.get("appt_status") in ("planifie", "confirme")) else "performed"
        ts = to_iso(r.get("treatment_date") or r.get("created_at"))
        if ctype and is_valid_tooth_number(n):
            doctor_id = r.get("doctor_id") or await _patient_doctor(db, r["patient_id"])
            if ctype == "bridge":
                pending_bridges.setdefault((r["patient_id"], status, ts, r.get("consultation_id")), []).append(n)
            elif not await _has_treatment(db, r["patient_id"], n, ctype):
                tid = await _insert_treatment(
                    db, r["patient_id"], doctor_id, ctype, "tooth",
                    [{"tooth_number": n, "role": None, "surfaces": None}], status,
                    recorded_at=to_iso(r.get("created_at")), performed_at=ts, performed_by=doctor_id,
                    consultation_id=r.get("consultation_id"), source_module="legacy_migration",
                )
                await db.execute("UPDATE dental_treatments SET odo_treatment_id = ? WHERE id = ?", (tid, r["id"]))
            stats["treatments"] += 1
        else:
            stats["skipped_treatments"] += 1
        await db.execute("UPDATE dental_treatments SET odo_synced = 1 WHERE id = ?", (r["id"],))
    for (pid, status, ts, cid), teeth in pending_bridges.items():
        doctor_id = await _patient_doctor(db, pid)
        await _create_bridges(db, pid, doctor_id, teeth, ts, status, consultation_id=cid)
    if trows:
        await db.commit()

    if any(stats.values()):
        print(f"[odontogramme] migration legacy : {stats}")
    return stats
