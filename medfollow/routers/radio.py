"""Module Radio IA : détection de pathologies sur radiographie dentaire.

Le cliché est stocké sur le serveur Doctivo (comme tout document patient). Le
modèle YOLOv8 DentalXrayAI (DENTEX) tourne DANS LE NAVIGATEUR via onnxruntime-web
(static/js/radio/detect.js) — comme la Céphalométrie — et repère carie, carie
profonde, dent incluse et lésion périapicale. Le serveur ne fait donc PAS
d'inférence : il stocke le cliché, persiste l'état (détections validées, ajouts
manuels, notes) via /save, et produit l'image annotée + le rapport PDF (Pillow /
reportlab, sans torch). Le praticien peut écarter les faux positifs et ajouter
une détection à la main.

L'IA est une aide au dépistage, jamais un diagnostic : rien n'est écarté ni
retenu sans la validation du praticien.
"""
import io
import json
import os
import uuid
from datetime import date

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response, StreamingResponse)
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from config import MAX_UPLOAD_SIZE_MB, TEMPLATES_DIR, UPLOAD_DIR
from database.connection import get_db
from routers.deps import (deny_secretaire, effective_doctor_id, require_login,
                          require_login_api, set_flash)
from services import radio_ai
from services.audit import client_ip, log_audit

router = APIRouter(prefix="/radio-ia", dependencies=[Depends(deny_secretaire)])
templates = Jinja2Templates(directory=TEMPLATES_DIR)

RADIO_DIR = os.path.join(UPLOAD_DIR, "radio")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_IMAGE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

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


def _sex_label(gender) -> str:
    g = (gender or "").strip().lower()
    if g.startswith("f"):
        return "Femme"
    if g.startswith(("m", "h")):
        return "Homme"
    return ""


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
           FROM radio_cases c JOIN patients p ON c.patient_id = p.id
           WHERE c.id = ? AND c.doctor_id = ?""",
        (case_id, doctor_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


def _kept_detections(detections: list) -> list:
    return [d for d in detections if not d.get("dismissed")]


# ---------------------------------------------------------------------------
# Liste des analyses
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def index(request: Request, patient_id: int | None = None,
                user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)

    cur = await db.execute(
        """SELECT c.id, c.taken_on, c.status, c.detections_json,
                  p.first_name, p.last_name
           FROM radio_cases c JOIN patients p ON c.patient_id = p.id
           WHERE c.doctor_id = ?
           ORDER BY c.updated_at DESC, c.id DESC""",
        (doctor_id,),
    )
    cases = []
    for r in await cur.fetchall():
        data = _loads(r["detections_json"], {})
        kept = _kept_detections(data.get("detections", []) if isinstance(data, dict) else [])
        cases.append({
            "id": r["id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "taken_on_fr": _fr_date(r["taken_on"]),
            "status": r["status"] or "importe",
            "n_findings": len(kept),
        })

    cur = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 "
        "ORDER BY last_name, first_name",
        (doctor_id,),
    )
    patients = [dict(p) for p in await cur.fetchall()]

    return templates.TemplateResponse("radio/index.html", {
        "request": request,
        "user": user,
        "active": "radio",
        "cases": cases,
        "patients": patients,
        "preselect_patient": patient_id,
        "today": date.today().isoformat(),
        "ai": radio_ai.availability(),
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
        resp = RedirectResponse(url="/radio-ia", status_code=302)
        set_flash(resp, "Patient introuvable", "error")
        return resp

    ext = os.path.splitext(image.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        resp = RedirectResponse(url="/radio-ia", status_code=302)
        set_flash(resp, "Format non pris en charge : importez un JPEG, PNG, WebP ou BMP.", "error")
        return resp

    # Nom de fichier généré côté serveur : le nom client peut porter un « ../ ».
    os.makedirs(RADIO_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(RADIO_DIR, stored)

    size = 0
    with open(path, "wb") as f:
        while chunk := await image.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                f.close()
                os.remove(path)
                resp = RedirectResponse(url="/radio-ia", status_code=302)
                set_flash(resp, f"Cliché trop volumineux (max {MAX_UPLOAD_SIZE_MB} Mo).", "error")
                return resp
            f.write(chunk)

    cur = await db.execute(
        """INSERT INTO radio_cases (patient_id, doctor_id, taken_on, image_path, status)
           VALUES (?, ?, ?, ?, 'importe')""",
        (patient_id, doctor_id, (taken_on or date.today().isoformat())[:10], path),
    )
    await db.commit()
    case_id = cur.lastrowid

    await log_audit(db, user, "radio_cree", entity_type="radio_case", entity_id=case_id,
                    patient_id=patient_id, ip=client_ip(request))

    resp = RedirectResponse(url=f"/radio-ia/{case_id}", status_code=302)
    set_flash(resp, "Cliché importé — lancez la détection IA.")
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

    await log_audit(db, user, "radio_consultee", entity_type="radio_case", entity_id=case_id,
                    patient_id=case["patient_id"], ip=client_ip(request))

    data = _loads(case["detections_json"], {})
    if not isinstance(data, dict):
        data = {}

    radio = {
        "case": {
            "id": case["id"],
            "image_url": f"/radio-ia/{case_id}/image",
            "status": case["status"] or "importe",
            "detections": data.get("detections", []),
            "model": data.get("model"),
            "notes": case["notes"] or "",
        },
    }

    return templates.TemplateResponse("radio/workstation.html", {
        "request": request,
        "user": user,
        "active": "radio",
        "case": {**case, "taken_on_fr": _fr_date(case["taken_on"])},
        "patient": {
            "name": f"{case['last_name'].upper()} {case['first_name']}",
            "age": _age(case["date_of_birth"]),
            "sex_label": _sex_label(case["gender"]),
        },
        "radio_json": json.dumps(radio, ensure_ascii=False),
        "ai": radio_ai.availability(),
    })


@router.get("/{case_id}/image")
async def case_image(request: Request, case_id: int,
                     user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    case = await _owned_case(db, case_id, effective_doctor_id(user))
    if not case or not case["image_path"] or not os.path.exists(case["image_path"]):
        return HTMLResponse("<h2>Cliché introuvable</h2>", status_code=404)
    return FileResponse(case["image_path"])


@router.get("/{case_id}/annotated")
async def case_annotated(request: Request, case_id: int,
                         user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    """Cliché avec les boîtes des détections retenues, rendu par le serveur (PNG)."""
    case = await _owned_case(db, case_id, effective_doctor_id(user))
    if not case or not case["image_path"] or not os.path.exists(case["image_path"]):
        return HTMLResponse("<h2>Cliché introuvable</h2>", status_code=404)
    data = _loads(case["detections_json"], {})
    dets = data.get("detections", []) if isinstance(data, dict) else []
    try:
        png = await run_in_threadpool(radio_ai.render_annotated_png, case["image_path"], dets)
    except Exception:
        return FileResponse(case["image_path"])
    return Response(content=png, media_type="image/png")


# ---------------------------------------------------------------------------
# Persistance des détections (calculées dans le navigateur)
# ---------------------------------------------------------------------------
# Il n'y a PAS de route d'analyse serveur : l'inférence YOLOv8 tourne dans le
# navigateur (static/js/radio/detect.js) puis le résultat est persisté via /save.


def _clamp_nbox(nb):
    """Valide/normalise une boîte cliente (coords 0-1) ; None si trop petite."""
    try:
        x1, y1, x2, y2 = (max(0.0, min(1.0, float(v))) for v in nb)
    except (TypeError, ValueError):
        return None
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    if (x2 - x1) < 0.005 or (y2 - y1) < 0.005:
        return None
    return [x1, y1, x2, y2]


@router.post("/{case_id}/save")
async def save_case(request: Request, case_id: int,
                    user: dict = Depends(require_login_api), db: aiosqlite.Connection = Depends(get_db)):
    """Persiste les notes et l'état des détections.

    Le corps envoie la liste complète `detections`. Pour les détections du modèle
    (source='ai'), la GÉOMÉTRIE reste celle calculée par le serveur (retrouvée par
    id, non falsifiable) ; seuls l'écartement et le n° de dent corrigé sont repris.
    Pour les détections ajoutées à la main (source='manual'), on accepte la boîte
    du client, bornée dans l'image. Rétro-compatible avec l'ancien format
    {dismissed, teeth}.
    """
    doctor_id = effective_doctor_id(user)
    case = await _owned_case(db, case_id, doctor_id)
    if not case:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    data = _loads(case["detections_json"], {})
    if not isinstance(data, dict):
        data = {}

    img_w = data.get("image_w") or 0
    img_h = data.get("image_h") or 0
    # Dimensions inconnues (aucune analyse IA lancée) : on les lit du fichier pour
    # pouvoir situer une détection ajoutée à la main.
    if (not img_w or not img_h) and case["image_path"] and os.path.exists(case["image_path"]):
        try:
            from PIL import Image
            with Image.open(case["image_path"]) as im:
                img_w, img_h = im.size
            data["image_w"], data["image_h"] = img_w, img_h
        except Exception:
            pass

    incoming = body.get("detections")
    if incoming is None:
        # --- Ancien format : {dismissed, teeth} ---
        dismissed_ids = set(body.get("dismissed") or [])
        teeth = body.get("teeth") or {}
        for d in data.get("detections", []):
            did = d.get("id")
            d["dismissed"] = did in dismissed_ids
            if str(did) in teeth or did in teeth:
                raw = teeth.get(str(did), teeth.get(did))
                try:
                    d["tooth"] = int(raw) if raw not in (None, "") else None
                except (TypeError, ValueError):
                    d["tooth"] = None
                d["tooth_estimated"] = False
    else:
        # L'inférence étant navigateur, le client est la source des détections
        # (comme les points de la Céphalométrie). On borne les boîtes, on recalcule
        # le libellé/la couleur FR côté serveur (cohérence image annotée + PDF), et
        # on garde confiance / n° de dent / écartement tels quels.
        merged = []
        for d in incoming:
            nb = _clamp_nbox(d.get("nbox"))
            if nb is None:
                continue
            manual = d.get("source") == "manual"
            cx, cy = (nb[0] + nb[2]) / 2 * img_w, (nb[1] + nb[3]) / 2 * img_h
            tooth = d.get("tooth")
            try:
                tooth = (int(tooth) if tooth not in (None, "")
                         else radio_ai.estimate_fdi(cx, cy, img_w, img_h))
            except (TypeError, ValueError):
                tooth = None
            conf = d.get("conf")
            try:
                conf = float(conf) if conf not in (None, "") else None
            except (TypeError, ValueError):
                conf = None
            cls = str(d.get("cls") or "")
            merged.append({
                "cls": cls,
                "label": radio_ai.label_fr(cls),
                "color": radio_ai.color_for(cls),
                "conf": conf,
                "box": [round(nb[0] * img_w, 1), round(nb[1] * img_h, 1),
                        round(nb[2] * img_w, 1), round(nb[3] * img_h, 1)],
                "nbox": [round(v, 5) for v in nb],
                "tooth": tooth,
                "tooth_estimated": bool(d.get("tooth_estimated", True)),
                "dismissed": bool(d.get("dismissed")),
                "source": "manual" if manual else "ai",
            })
        for i, d in enumerate(merged):
            d["id"] = i
        data["detections"] = merged

    # Un ajout manuel sur un cliché jamais analysé fait passer le cas en « analysé ».
    new_status = "analyse" if data.get("detections") else (case["status"] or "importe")

    await db.execute(
        """UPDATE radio_cases
           SET detections_json = ?, notes = ?, status = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND doctor_id = ?""",
        (
            json.dumps(data, ensure_ascii=False),
            (body.get("notes") or "").strip() or None,
            new_status,
            case_id, doctor_id,
        ),
    )
    await db.commit()
    return JSONResponse({"ok": True, "detections": data.get("detections", [])})


@router.post("/{case_id}/supprimer")
async def delete_case(request: Request, case_id: int,
                      user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)
    case = await _owned_case(db, case_id, doctor_id)
    if not case:
        resp = RedirectResponse(url="/radio-ia", status_code=302)
        set_flash(resp, "Analyse introuvable", "error")
        return resp

    await db.execute("DELETE FROM radio_cases WHERE id = ? AND doctor_id = ?", (case_id, doctor_id))
    await db.commit()
    if case["image_path"] and os.path.exists(case["image_path"]):
        try:
            os.remove(case["image_path"])
        except OSError:
            pass

    await log_audit(db, user, "radio_supprimee", entity_type="radio_case", entity_id=case_id,
                    patient_id=case["patient_id"], ip=client_ip(request))

    resp = RedirectResponse(url="/radio-ia", status_code=302)
    set_flash(resp, "Analyse supprimée")
    return resp


# ---------------------------------------------------------------------------
# Rapport PDF (papier à en-tête du praticien, comme tous les PDF Doctivo)
# ---------------------------------------------------------------------------

@router.get("/{case_id}/rapport.pdf")
async def report_pdf(request: Request, case_id: int,
                     user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    doctor_id = effective_doctor_id(user)
    case = await _owned_case(db, case_id, doctor_id)
    if not case:
        return JSONResponse({"error": "not found"}, status_code=404)

    data = _loads(case["detections_json"], {})
    dets = data.get("detections", []) if isinstance(data, dict) else []
    kept = _kept_detections(dets)

    # Image annotée (détections retenues) posée telle quelle dans le rapport.
    annotated_png = None
    if case["image_path"] and os.path.exists(case["image_path"]):
        try:
            annotated_png = await run_in_threadpool(
                radio_ai.render_annotated_png, case["image_path"], dets)
        except Exception:
            annotated_png = None

    cur = await db.execute(
        "SELECT first_name, last_name, specialty, phone, address, pdf_template_path FROM users WHERE id = ?",
        (doctor_id,),
    )
    d = await cur.fetchone()
    doctor_name = f"Dr. {d['first_name']} {d['last_name']}" if d else ""

    patient = {
        "name": f"{case['last_name'].upper()} {case['first_name']}",
        "dob": case["date_of_birth"],
        "age": _age(case["date_of_birth"]),
        "sex_label": _sex_label(case["gender"]),
        "taken_on": _fr_date(case["taken_on"]),
    }

    findings = [{
        "label": k.get("label") or k.get("cls") or "Anomalie",
        "conf": k.get("conf"),
        "color": k.get("color") or "#0ea5e9",
        "tooth": k.get("tooth"),
        "tooth_estimated": k.get("tooth_estimated", True),
    } for k in kept]

    from services.pdf_service import generate_radio_ai_pdf
    pdf_bytes = generate_radio_ai_pdf(
        patient=patient,
        model_name=data.get("model") or case["model_name"] or "DentalXrayAI",
        findings=findings,
        analysed=(case["status"] == "analyse"),
        notes=(case["notes"] or "").strip(),
        annotated_png=annotated_png,
        doctor_name=doctor_name,
        specialty=(d["specialty"] if d else "") or "",
        address=(d["address"] if d else None),
        phone=(d["phone"] if d else None),
        template_path=(d["pdf_template_path"] if d else None),
    )

    await log_audit(db, user, "radio_rapport", entity_type="radio_case", entity_id=case_id,
                    patient_id=case["patient_id"], ip=client_ip(request))

    fname = f"radio_ia_{_slug(case['last_name'])}_{case_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )
