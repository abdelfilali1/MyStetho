"""Module Céphalométrie : analyse de téléradiographie de profil.

Le cliché est stocké sur le serveur Doctivo (comme tout document patient) ; le
moteur d'analyse (points, plans, mesures, normes) vit côté navigateur, dans
/static/js/ceph/. Ce router ne fait que : héberger les clichés, persister l'état
d'un cas (points, calibration, tracés) et rendre le rapport PDF sur le papier à
en-tête du praticien — comme tous les autres PDF de l'application.
"""
import base64
import io
import json
import os
import uuid
from datetime import date

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from config import MAX_UPLOAD_SIZE_MB, TEMPLATES_DIR, UPLOAD_DIR
from database.connection import get_db
from routers.deps import deny_secretaire, effective_doctor_id, require_login, require_login_api, set_flash
from services.audit import client_ip, log_audit

router = APIRouter(prefix="/cephalometrie", dependencies=[Depends(deny_secretaire)])
templates = Jinja2Templates(directory=TEMPLATES_DIR)

CEPH_DIR = os.path.join(UPLOAD_DIR, "cephalo")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
# Le tracé composé côté navigateur est renvoyé en PNG base64 : plafonné pour ne
# pas transformer un POST en canal d'upload arbitraire.
MAX_TRACING_BYTES = 12 * 1024 * 1024

ANALYSIS_LABELS = {
    "steiner": "Steiner",
    "downs": "Downs",
    "tweed": "Tweed",
    "ricketts": "Ricketts",
    "mcnamara": "McNamara",
    "jarabak": "Jarabak / Björk",
    "wits": "Wits",
    "soft-tissue": "Tissus mous",
    "dental": "Dentaire",
    "vertical": "Vertical / croissance",
}

_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


def _fr_date(s) -> str:
    try:
        y, m, d = str(s)[:10].split("-")
        return f"{int(d):02d} {_MONTHS[int(m) - 1]} {y}"
    except Exception:
        return ""


def _age(dob) -> int | None:
    try:
        y, m, d = str(dob)[:10].split("-")
        today = date.today()
        born = date(int(y), int(m), int(d))
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return None


def _sex_code(gender) -> str:
    """Les normes de plusieurs mesures (Wits, McNamara, LAFH…) dépendent du sexe."""
    g = (gender or "").strip().lower()
    if g.startswith(("f", "femme")):
        return "female"
    if g.startswith(("m", "h")):   # 'M', 'Masculin', 'Homme'
        return "male"
    return "unknown"


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (s or "patient")).strip("_").lower() or "patient"


def _loads(raw, fallback):
    try:
        v = json.loads(raw) if raw else fallback
        return v if v is not None else fallback
    except Exception:
        return fallback


async def _owned_case(db: aiosqlite.Connection, case_id: int, doctor_id: int) -> dict | None:
    cur = await db.execute(
        """SELECT c.*, p.first_name, p.last_name, p.date_of_birth, p.gender
           FROM ceph_cases c JOIN patients p ON c.patient_id = p.id
           WHERE c.id = ? AND c.doctor_id = ?""",
        (case_id, doctor_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Liste des analyses
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def index(request: Request, patient_id: int | None = None,
                user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)

    cur = await db.execute(
        """SELECT c.id, c.taken_on, c.analysis_id, c.mm_per_px, c.landmarks_json,
                  p.first_name, p.last_name
           FROM ceph_cases c JOIN patients p ON c.patient_id = p.id
           WHERE c.doctor_id = ?
           ORDER BY c.updated_at DESC, c.id DESC""",
        (doctor_id,),
    )
    cases = []
    for r in await cur.fetchall():
        pts = _loads(r["landmarks_json"], {})
        cases.append({
            "id": r["id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "taken_on_fr": _fr_date(r["taken_on"]),
            "analysis_label": ANALYSIS_LABELS.get(r["analysis_id"], r["analysis_id"] or "Steiner"),
            "mm_per_px": r["mm_per_px"],
            "n_points": len(pts) if isinstance(pts, dict) else 0,
        })

    cur = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 "
        "ORDER BY last_name, first_name",
        (doctor_id,),
    )
    patients = [dict(p) for p in await cur.fetchall()]

    return templates.TemplateResponse("cephalo/index.html", {
        "request": request,
        "user": user,
        "active": "cephalo",
        "cases": cases,
        "patients": patients,
        "preselect_patient": patient_id,
        "today": date.today().isoformat(),
    })


# ---------------------------------------------------------------------------
# Création d'un cas (import du cliché)
# ---------------------------------------------------------------------------

@router.post("/nouvelle")
async def create_case(request: Request, patient_id: int = Form(...), taken_on: str = Form(""),
                      image: UploadFile = File(...),
                      user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)

    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, doctor_id))
    if not await cur.fetchone():
        resp = RedirectResponse(url="/cephalometrie", status_code=302)
        set_flash(resp, "Patient introuvable", "error")
        return resp

    ext = os.path.splitext(image.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        resp = RedirectResponse(url="/cephalometrie", status_code=302)
        set_flash(resp, "Format non pris en charge : importez un JPEG, PNG ou WebP.", "error")
        return resp

    # Nom de fichier généré côté serveur : le nom client peut porter un « ../ ».
    os.makedirs(CEPH_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(CEPH_DIR, stored)

    size = 0
    with open(path, "wb") as f:
        while chunk := await image.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                f.close()
                os.remove(path)
                resp = RedirectResponse(url="/cephalometrie", status_code=302)
                set_flash(resp, f"Cliché trop volumineux (max {MAX_UPLOAD_SIZE_MB} Mo).", "error")
                return resp
            f.write(chunk)

    cur = await db.execute(
        """INSERT INTO ceph_cases (patient_id, doctor_id, taken_on, image_path, analysis_id)
           VALUES (?, ?, ?, ?, 'steiner')""",
        (patient_id, doctor_id, (taken_on or date.today().isoformat())[:10], path),
    )
    await db.commit()
    case_id = cur.lastrowid

    await log_audit(db, user, "ceph_cree", entity_type="ceph_case", entity_id=case_id,
                    patient_id=patient_id, ip=client_ip(request))

    resp = RedirectResponse(url=f"/cephalometrie/{case_id}", status_code=302)
    set_flash(resp, "Cliché importé — calibrez l'échelle puis posez les points.")
    return resp


# ---------------------------------------------------------------------------
# Poste de travail
# ---------------------------------------------------------------------------

@router.get("/{case_id}", response_class=HTMLResponse)
async def workstation(request: Request, case_id: int,
                      user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    case = await _owned_case(db, case_id, effective_doctor_id(user))
    if not case:
        return HTMLResponse("<h2>Analyse introuvable</h2>", status_code=404)

    await log_audit(db, user, "ceph_consultee", entity_type="ceph_case", entity_id=case_id,
                    patient_id=case["patient_id"], ip=client_ip(request))

    sex = _sex_code(case["gender"])
    age = _age(case["date_of_birth"])

    ceph = {
        "case": {
            "id": case["id"],
            "image_url": f"/cephalometrie/{case_id}/image",
            "analysis_id": case["analysis_id"] or "steiner",
            "landmarks": _loads(case["landmarks_json"], {}),
            "traces": _loads(case["traces_json"], []),
            # Colonne ajoutee apres coup : absente des dossiers anciens tant que
            # la migration n'a pas tourne, d'ou l'acces defensif.
            "measures": _loads(case["measures_json"] if "measures_json" in case.keys() else None, []),
            "calibration": _loads(case["calibration_json"], {}),
            "adjust": _loads(case["adjust_json"], {}),
        },
        "patient": {
            "name": f"{case['last_name']} {case['first_name']}",
            "slug": _slug(f"{case['last_name']}_{case['first_name']}"),
            "sex": sex,
            "age": age,
        },
    }

    return templates.TemplateResponse("cephalo/workstation.html", {
        "request": request,
        "user": user,
        "active": "cephalo",
        "case": {**case, "taken_on_fr": _fr_date(case["taken_on"])},
        "patient": {
            "age": age,
            "sex_label": {"male": "Homme", "female": "Femme"}.get(sex, ""),
        },
        "ceph_json": json.dumps(ceph, ensure_ascii=False),
    })


@router.get("/{case_id}/image")
async def case_image(request: Request, case_id: int,
                     user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    case = await _owned_case(db, case_id, effective_doctor_id(user))
    if not case or not case["image_path"] or not os.path.exists(case["image_path"]):
        return HTMLResponse("<h2>Cliché introuvable</h2>", status_code=404)
    return FileResponse(case["image_path"])


@router.post("/{case_id}/save")
async def save_case(request: Request, case_id: int,
                    user: dict = Depends(require_login_api), db: aiosqlite.Connection = Depends(get_db)):
    case = await _owned_case(db, case_id, effective_doctor_id(user))
    if not case:
        return JSONResponse({"error": "not found"}, status_code=404)

    data = await request.json()
    calibration = data.get("calibration") or {}
    mm_per_px = calibration.get("mmPerPx")

    await db.execute(
        """UPDATE ceph_cases
           SET analysis_id = ?, landmarks_json = ?, traces_json = ?, measures_json = ?,
               calibration_json = ?, adjust_json = ?, mm_per_px = ?, notes = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND doctor_id = ?""",
        (
            data.get("analysis_id") or "steiner",
            json.dumps(data.get("landmarks") or {}, ensure_ascii=False),
            json.dumps(data.get("traces") or [], ensure_ascii=False),
            json.dumps(data.get("measures") or [], ensure_ascii=False),
            json.dumps(calibration, ensure_ascii=False),
            json.dumps(data.get("adjust") or {}, ensure_ascii=False),
            float(mm_per_px) if isinstance(mm_per_px, (int, float)) else None,
            (data.get("notes") or "").strip() or None,
            case_id, effective_doctor_id(user),
        ),
    )
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/{case_id}/supprimer")
async def delete_case(request: Request, case_id: int,
                      user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)
    case = await _owned_case(db, case_id, doctor_id)
    if not case:
        resp = RedirectResponse(url="/cephalometrie", status_code=302)
        set_flash(resp, "Analyse introuvable", "error")
        return resp

    await db.execute("DELETE FROM ceph_cases WHERE id = ? AND doctor_id = ?", (case_id, doctor_id))
    await db.commit()
    if case["image_path"] and os.path.exists(case["image_path"]):
        try:
            os.remove(case["image_path"])
        except OSError:
            pass

    await log_audit(db, user, "ceph_supprimee", entity_type="ceph_case", entity_id=case_id,
                    patient_id=case["patient_id"], ip=client_ip(request))

    resp = RedirectResponse(url="/cephalometrie", status_code=302)
    set_flash(resp, "Analyse supprimée")
    return resp


# ---------------------------------------------------------------------------
# Rapport PDF (papier à en-tête du praticien, comme tous les PDF Doctivo)
# ---------------------------------------------------------------------------

@router.post("/{case_id}/rapport.pdf")
async def report_pdf(request: Request, case_id: int,
                     user: dict = Depends(require_login_api), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)
    case = await _owned_case(db, case_id, doctor_id)
    if not case:
        return JSONResponse({"error": "not found"}, status_code=404)

    data = await request.json()

    # Le tracé est composé par le navigateur (radio + plans + points), puis posé
    # tel quel dans le rapport : le PDF montre exactement ce que le praticien a vu.
    tracing_png = None
    raw = data.get("tracing_png") or ""
    if raw.startswith("data:image/png;base64,"):
        b64 = raw.split(",", 1)[1]
        if len(b64) <= MAX_TRACING_BYTES:
            try:
                tracing_png = base64.b64decode(b64)
            except Exception:
                tracing_png = None

    cur = await db.execute(
        "SELECT first_name, last_name, specialty, phone, address, pdf_template_path FROM users WHERE id = ?",
        (doctor_id,),
    )
    d = await cur.fetchone()
    doctor_name = f"Dr. {d['first_name']} {d['last_name']}" if d else ""

    sex = _sex_code(case["gender"])
    patient = {
        "name": f"{case['last_name'].upper()} {case['first_name']}",
        "dob": case["date_of_birth"],
        "age": _age(case["date_of_birth"]),
        "sex_label": {"male": "Homme", "female": "Femme"}.get(sex, ""),
        "taken_on": _fr_date(case["taken_on"]),
    }

    from services.pdf_service import generate_cephalo_pdf
    pdf_bytes = generate_cephalo_pdf(
        patient=patient,
        analysis_name=data.get("analysis_name") or "",
        analysis_subtitle=data.get("analysis_subtitle") or "",
        citation=data.get("citation") or "",
        rows=data.get("rows") or [],
        summary=data.get("summary") or [],
        notes=(data.get("notes") or "").strip(),
        calibrated=bool(data.get("calibrated")),
        tracing_png=tracing_png,
        doctor_name=doctor_name,
        specialty=(d["specialty"] if d else "") or "",
        address=(d["address"] if d else None),
        phone=(d["phone"] if d else None),
        template_path=(d["pdf_template_path"] if d else None),
    )

    await log_audit(db, user, "ceph_rapport", entity_type="ceph_case", entity_id=case_id,
                    patient_id=case["patient_id"], ip=client_ip(request))

    fname = f"cephalometrie_{_slug(case['last_name'])}_{case_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )
