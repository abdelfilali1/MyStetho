"""Service parodontogramme (port de dentalpin `periodontogram/{service,indices}.py`).

Un examen = un snapshot daté (draft -> closed, immuable une fois clôturé), avec
32 dents permanentes (11-48) et jusqu'à 6 sites par dent (MV V DV ML L DL).
Un seul brouillon par patient.
"""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from services.odonto_constants import PERMANENT_TEETH
from services.odonto_service import ApiError, now_iso

PERIO_TEETH = list(PERMANENT_TEETH)
SITE_CODES = ["MV", "V", "DV", "ML", "L", "DL"]
SITES_PER_TOOTH = 6
DEEP_POCKET_THRESHOLD_MM = 5

TOOTH_FIELDS = ("is_present", "is_implant", "mobility", "prognosis", "furcation_buccal",
                "furcation_lingual", "keratinized_gingiva_mm")
SITE_FIELDS = ("probing_depth_mm", "gingival_margin_mm", "bleeding_on_probing", "plaque", "suppuration")


# ---------------------------------------------------------------------------
# Indices SEPA
# ---------------------------------------------------------------------------

def compute_indices(teeth: list[dict]) -> dict:
    present = [t for t in teeth if t.get("is_present")]
    total = SITES_PER_TOOTH * len(present)
    if total == 0:
        return {"bop_pct": 0.0, "pi_pct": 0.0, "cal_mean_mm": 0.0, "deep_pockets_count": 0}
    bop = plaque = 0
    cal_sum = 0.0
    deep = 0
    for t in present:
        has_deep = False
        for s in t.get("sites", []):
            if s.get("bleeding_on_probing"):
                bop += 1
            if s.get("plaque"):
                plaque += 1
            pd, gm = s.get("probing_depth_mm"), s.get("gingival_margin_mm")
            if pd is not None and gm is not None:
                cal_sum += pd + gm
            if pd is not None and pd >= DEEP_POCKET_THRESHOLD_MM:
                has_deep = True
        if has_deep:
            deep += 1
    return {
        "bop_pct": round(100.0 * bop / total, 2),
        "pi_pct": round(100.0 * plaque / total, 2),
        "cal_mean_mm": round(cal_sum / total, 2),
        "deep_pockets_count": deep,
    }


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def _summary(row: aiosqlite.Row | dict) -> dict:
    d = dict(row)
    return {"id": d["id"], "patient_id": d["patient_id"], "status": d["status"],
            "recorded_at": d["recorded_at"], "closed_at": d.get("closed_at")}


async def _snapshot_row(db: aiosqlite.Connection, patient_id: int, snapshot_id: int) -> dict:
    cur = await db.execute("SELECT * FROM perio_snapshots WHERE id = ? AND patient_id = ?", (snapshot_id, patient_id))
    row = await cur.fetchone()
    if row is None:
        raise ApiError(404, "Session parodontale introuvable")
    return dict(row)


async def serialize_snapshot(db: aiosqlite.Connection, patient_id: int, snapshot_id: int) -> dict:
    snap = await _snapshot_row(db, patient_id, snapshot_id)
    cur = await db.execute("SELECT * FROM perio_teeth WHERE snapshot_id = ? ORDER BY tooth_number", (snapshot_id,))
    teeth = []
    for r in await cur.fetchall():
        d = dict(r)
        teeth.append({
            "tooth_number": d["tooth_number"],
            "is_present": bool(d["is_present"]),
            "is_implant": bool(d["is_implant"]),
            "mobility": d["mobility"],
            "prognosis": d["prognosis"],
            "furcation_buccal": d["furcation_buccal"],
            "furcation_lingual": d["furcation_lingual"],
            "keratinized_gingiva_mm": d["keratinized_gingiva_mm"],
            "sites": [],
        })
    by_tooth = {t["tooth_number"]: t for t in teeth}
    cur = await db.execute("SELECT * FROM perio_sites WHERE snapshot_id = ? ORDER BY tooth_number, site_code", (snapshot_id,))
    for r in await cur.fetchall():
        d = dict(r)
        t = by_tooth.get(d["tooth_number"])
        if t is not None:
            t["sites"].append(_site_value(d))
    indices = None
    if snap.get("indices_json"):
        try:
            indices = json.loads(snap["indices_json"])
        except Exception:
            indices = None
    return {
        "id": snap["id"], "patient_id": snap["patient_id"], "status": snap["status"],
        "recorded_at": snap["recorded_at"], "recorded_by": snap["recorded_by"],
        "closed_at": snap.get("closed_at"), "closed_by": snap.get("closed_by"),
        "indices": indices, "teeth": teeth,
    }


def _site_value(d: dict) -> dict:
    return {
        "site_code": d["site_code"],
        "probing_depth_mm": d["probing_depth_mm"],
        "gingival_margin_mm": d["gingival_margin_mm"],
        "bleeding_on_probing": bool(d["bleeding_on_probing"]),
        "plaque": bool(d["plaque"]),
        "suppuration": bool(d["suppuration"]),
    }


async def get_active_draft(db: aiosqlite.Connection, patient_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM perio_snapshots WHERE patient_id = ? AND status = 'draft'", (patient_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_timeline(db: aiosqlite.Connection, patient_id: int) -> list[dict]:
    cur = await db.execute(
        """SELECT s.id, s.closed_at,
                  (SELECT COUNT(*) FROM perio_sites p WHERE p.snapshot_id = s.id AND p.probing_depth_mm IS NOT NULL) AS change_count
           FROM perio_snapshots s WHERE s.patient_id = ? AND s.status = 'closed' ORDER BY s.closed_at ASC, s.id ASC""",
        (patient_id,),
    )
    by_date: dict[str, dict] = {}
    for r in await cur.fetchall():
        d = (r["closed_at"] or "")[:10]
        by_date[d] = {"snapshot_id": r["id"], "date": d, "change_count": int(r["change_count"] or 0)}
    return list(by_date.values())


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

async def _odontogram_flags(db: aiosqlite.Connection, patient_id: int) -> dict[int, dict]:
    flags: dict[int, dict] = {}
    cur = await db.execute(
        "SELECT tooth_number FROM odo_tooth_records WHERE patient_id = ? AND general_condition = 'missing'", (patient_id,)
    )
    for r in await cur.fetchall():
        flags[r["tooth_number"]] = {"is_present": 0, "is_implant": 0}
    cur = await db.execute(
        """SELECT tt.tooth_number FROM odo_treatments t JOIN odo_treatment_teeth tt ON tt.treatment_id = t.id
           WHERE t.patient_id = ? AND t.clinical_type = 'implant' AND t.status = 'performed' AND t.deleted_at IS NULL""",
        (patient_id,),
    )
    for r in await cur.fetchall():
        flags[r["tooth_number"]] = {"is_present": 1, "is_implant": 1}
    return flags


async def get_or_create_draft(db: aiosqlite.Connection, patient_id: int, user_id: int) -> tuple[dict, bool]:
    existing = await get_active_draft(db, patient_id)
    if existing:
        return existing, False
    ts = now_iso()
    cur = await db.execute(
        """INSERT INTO perio_snapshots (patient_id, status, recorded_at, recorded_by, created_at, updated_at)
           VALUES (?, 'draft', ?, ?, ?, ?)""",
        (patient_id, ts, user_id, ts, ts),
    )
    sid = cur.lastrowid
    flags = await _odontogram_flags(db, patient_id)
    for n in PERIO_TEETH:
        f = flags.get(n, {})
        await db.execute(
            "INSERT INTO perio_teeth (snapshot_id, tooth_number, is_present, is_implant) VALUES (?, ?, ?, ?)",
            (sid, n, f.get("is_present", 1), f.get("is_implant", 0)),
        )
    snap = await _snapshot_row(db, patient_id, sid)
    return snap, True


async def _writable_snapshot(db: aiosqlite.Connection, patient_id: int, snapshot_id: int) -> dict:
    snap = await _snapshot_row(db, patient_id, snapshot_id)
    if snap["status"] == "closed":
        raise ApiError(409, "Session clôturée : modification impossible")
    return snap


async def _tooth_row(db: aiosqlite.Connection, snapshot_id: int, tooth_number: int) -> dict:
    cur = await db.execute("SELECT * FROM perio_teeth WHERE snapshot_id = ? AND tooth_number = ?", (snapshot_id, tooth_number))
    row = await cur.fetchone()
    if row is None:
        raise ApiError(404, f"Dent {tooth_number} absente de la session")
    return dict(row)


async def update_tooth(db: aiosqlite.Connection, patient_id: int, snapshot_id: int, tooth_number: int, patch: dict) -> dict:
    await _writable_snapshot(db, patient_id, snapshot_id)
    tooth = await _tooth_row(db, snapshot_id, tooth_number)
    sets, params = [], []
    for k in TOOTH_FIELDS:
        if k in patch:
            v = patch[k]
            if k in ("is_present", "is_implant") and v is not None:
                v = int(bool(v))
            sets.append(f"{k} = ?")
            params.append(v)
    if sets:
        params.append(tooth["id"])
        await db.execute(f"UPDATE perio_teeth SET {', '.join(sets)} WHERE id = ?", params)
    await db.execute("UPDATE perio_snapshots SET updated_at = ? WHERE id = ?", (now_iso(), snapshot_id))
    t = await _tooth_row(db, snapshot_id, tooth_number)
    return {
        "tooth_number": t["tooth_number"], "is_present": bool(t["is_present"]), "is_implant": bool(t["is_implant"]),
        "mobility": t["mobility"], "prognosis": t["prognosis"], "furcation_buccal": t["furcation_buccal"],
        "furcation_lingual": t["furcation_lingual"], "keratinized_gingiva_mm": t["keratinized_gingiva_mm"], "sites": [],
    }


async def update_site(db: aiosqlite.Connection, patient_id: int, snapshot_id: int, tooth_number: int,
                      site_code: str, patch: dict) -> dict:
    if site_code not in SITE_CODES:
        raise ApiError(422, f"Site invalide : {site_code}")
    await _writable_snapshot(db, patient_id, snapshot_id)
    tooth = await _tooth_row(db, snapshot_id, tooth_number)
    cur = await db.execute(
        "SELECT * FROM perio_sites WHERE snapshot_id = ? AND tooth_number = ? AND site_code = ?",
        (snapshot_id, tooth_number, site_code),
    )
    site = await cur.fetchone()
    if site is None:
        await db.execute(
            "INSERT INTO perio_sites (snapshot_id, tooth_id, tooth_number, site_code) VALUES (?, ?, ?, ?)",
            (snapshot_id, tooth["id"], tooth_number, site_code),
        )
    sets, params = [], []
    for k in SITE_FIELDS:
        if k in patch:
            v = patch[k]
            if k in ("bleeding_on_probing", "plaque", "suppuration"):
                v = int(bool(v))
            sets.append(f"{k} = ?")
            params.append(v)
    if sets:
        params.extend([snapshot_id, tooth_number, site_code])
        await db.execute(
            f"UPDATE perio_sites SET {', '.join(sets)} WHERE snapshot_id = ? AND tooth_number = ? AND site_code = ?", params
        )
    await db.execute("UPDATE perio_snapshots SET updated_at = ? WHERE id = ?", (now_iso(), snapshot_id))
    cur = await db.execute(
        "SELECT * FROM perio_sites WHERE snapshot_id = ? AND tooth_number = ? AND site_code = ?",
        (snapshot_id, tooth_number, site_code),
    )
    return _site_value(dict(await cur.fetchone()))


async def close_snapshot(db: aiosqlite.Connection, patient_id: int, snapshot_id: int, user_id: int) -> dict:
    snap = await _snapshot_row(db, patient_id, snapshot_id)
    if snap["status"] == "closed":
        raise ApiError(409, "Session déjà clôturée")
    detail = await serialize_snapshot(db, patient_id, snapshot_id)
    indices = compute_indices(detail["teeth"])
    ts = now_iso()
    await db.execute(
        "UPDATE perio_snapshots SET status = 'closed', closed_at = ?, closed_by = ?, indices_json = ?, updated_at = ? WHERE id = ?",
        (ts, user_id, json.dumps(indices), ts, snapshot_id),
    )
    return await serialize_snapshot(db, patient_id, snapshot_id)


async def discard_draft(db: aiosqlite.Connection, patient_id: int, snapshot_id: int) -> None:
    snap = await _snapshot_row(db, patient_id, snapshot_id)
    if snap["status"] != "draft":
        raise ApiError(409, "Seul un brouillon peut être abandonné")
    await db.execute("DELETE FROM perio_sites WHERE snapshot_id = ?", (snapshot_id,))
    await db.execute("DELETE FROM perio_teeth WHERE snapshot_id = ?", (snapshot_id,))
    await db.execute("DELETE FROM perio_snapshots WHERE id = ?", (snapshot_id,))


async def get_indices(db: aiosqlite.Connection, patient_id: int, snapshot_id: int) -> dict:
    detail = await serialize_snapshot(db, patient_id, snapshot_id)
    if detail["indices"]:
        return detail["indices"]
    return compute_indices(detail["teeth"])
