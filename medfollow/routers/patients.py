from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite
import json
import os

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, require_login_api, effective_doctor_id, set_flash, deny_secretaire
from services.audit import log_audit, client_ip

router = APIRouter(prefix="/patients")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


SORT_WHITELIST = {"last_name", "date_of_birth", "city", "created_at", "last_visit"}

HISTORY_TYPES = {"medical", "surgical", "family", "allergy"}

@router.get("/", response_class=HTMLResponse)
async def list_patients(
    request: Request,
    q: str = "",
    page: int = 1,
    sort_by: str = "last_name",
    sort_order: str = "asc",
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    doctor_id = effective_doctor_id(user)

    if sort_by not in SORT_WHITELIST:
        sort_by = "last_name"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"
    if sort_by == "last_visit":
        # last_visit est un alias SELECT pouvant être NULL (patient sans consultation) :
        # on repousse toujours les NULL en fin de liste.
        order_clause = f"ORDER BY (last_visit IS NULL), last_visit {sort_order.upper()}, last_name ASC"
    else:
        order_clause = f"ORDER BY {sort_by} {sort_order.upper()}, last_name ASC"

    per_page = 20
    offset = (page - 1) * per_page

    if q:
        like = f"%{q.lower()}%"
        count_cursor = await db.execute(
            """SELECT COUNT(*) FROM patients WHERE doctor_id = ? AND is_active = 1 AND (lower(first_name) LIKE ? OR lower(last_name) LIKE ? OR phone LIKE ? OR social_security_number LIKE ?)""",
            (doctor_id, like, like, f"%{q}%", f"%{q}%"),
        )
        total_count = (await count_cursor.fetchone())[0]

        cursor = await db.execute(
            f"""SELECT p.*, (SELECT MAX(consultation_date) FROM consultations WHERE patient_id = p.id) AS last_visit
                FROM patients p WHERE p.doctor_id = ? AND p.is_active = 1
                AND (lower(p.first_name) LIKE ? OR lower(p.last_name) LIKE ? OR p.phone LIKE ? OR p.social_security_number LIKE ?)
                {order_clause} LIMIT ? OFFSET ?""",
            (doctor_id, like, like, f"%{q}%", f"%{q}%", per_page, offset),
        )
    else:
        count_cursor = await db.execute(
            "SELECT COUNT(*) FROM patients WHERE doctor_id = ? AND is_active = 1",
            (doctor_id,),
        )
        total_count = (await count_cursor.fetchone())[0]

        cursor = await db.execute(
            f"""SELECT p.*, (SELECT MAX(consultation_date) FROM consultations WHERE patient_id = p.id) AS last_visit
                FROM patients p WHERE p.doctor_id = ? AND p.is_active = 1 {order_clause} LIMIT ? OFFSET ?""",
            (doctor_id, per_page, offset),
        )

    rows = await cursor.fetchall()
    patients = [dict(row) for row in rows]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return templates.TemplateResponse(
        "patients/list.html",
        {
            "request": request, "user": user, "active": "patients",
            "patients": patients, "search": q,
            "page": page, "total_pages": total_pages, "total_count": total_count,
            "sort_by": sort_by, "sort_order": sort_order,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_patient_form(request: Request, next: str = "", user: dict = Depends(require_login)):
    return templates.TemplateResponse(
        "patients/form.html",
        {"request": request, "user": user, "active": "patients", "patient": None, "error": None, "next": next},
    )


@router.post("/quick")
async def quick_create_patient(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(...),
    user: dict = Depends(require_login_api),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        "INSERT INTO patients (doctor_id, first_name, last_name, date_of_birth) VALUES (?, ?, ?, ?)",
        (effective_doctor_id(user), first_name.strip(), last_name.strip(), date_of_birth),
    )
    await db.commit()
    new_id = cursor.lastrowid
    await log_audit(
        db, user, "patient_cree", entity_type="patient", entity_id=new_id,
        patient_id=new_id, ip=client_ip(request), details="création rapide",
    )
    return JSONResponse(content={"id": new_id, "name": f"{last_name.upper()} {first_name}"})


def _parse_int(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def _parse_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


@router.post("/new", response_class=HTMLResponse)
async def create_patient(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(...),
    gender: str = Form(""),
    social_security_number: str = Form(""),
    identity_document_type: str = Form("CIN"),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    postal_code: str = Form(""),
    blood_type: str = Form(""),
    referring_doctor: str = Form(""),
    referring_doctor_phone: str = Form(""),
    insurance_name: str = Form(""),
    insurance_number: str = Form(""),
    insurance_serial: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    emergency_contact_relation: str = Form(""),
    profession: str = Form(""),
    marital_status: str = Form(""),
    height_cm: str = Form(""),
    weight_kg: str = Form(""),
    smoking: str = Form(""),
    alcohol: str = Form(""),
    pregnant: str = Form(""),
    breastfeeding: str = Form(""),
    current_medications: str = Form(""),
    gdpr_consent: str = Form(""),
    notes: str = Form(""),
    whatsapp_opt_out: str = Form(""),
    next_url: str = Form(""),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    height_i = _parse_int(height_cm)
    weight_f = _parse_float(weight_kg)
    pregnant_i = 1 if pregnant in ("1", "on", "true", "yes") else 0
    breastfeeding_i = 1 if breastfeeding in ("1", "on", "true", "yes") else 0
    gdpr_i = 1 if gdpr_consent in ("1", "on", "true", "yes") else 0
    wa_opt_out_i = 1 if whatsapp_opt_out in ("1", "on", "true", "yes") else 0

    try:
        cur = await db.execute(
            """INSERT INTO patients (
                doctor_id, first_name, last_name, date_of_birth, gender, social_security_number,
                identity_document_type,
                email, phone, address, city, postal_code, blood_type,
                referring_doctor, referring_doctor_phone,
                insurance_name, insurance_number, insurance_serial,
                emergency_contact_name, emergency_contact_phone, emergency_contact_relation,
                profession, marital_status, height_cm, weight_kg, smoking, alcohol,
                pregnant, breastfeeding, current_medications, gdpr_consent, notes, whatsapp_opt_out
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                effective_doctor_id(user),
                first_name, last_name, date_of_birth,
                gender or None, social_security_number or None,
                identity_document_type or None,
                email or None, phone or None, address or None,
                city or None, postal_code or None, blood_type or None,
                referring_doctor or None, referring_doctor_phone or None,
                insurance_name or None, insurance_number or None, insurance_serial or None,
                emergency_contact_name or None, emergency_contact_phone or None, emergency_contact_relation or None,
                profession or None, marital_status or None, height_i, weight_f,
                smoking or None, alcohol or None,
                pregnant_i, breastfeeding_i, current_medications or None, gdpr_i, notes or None, wa_opt_out_i,
            ),
        )
        await db.commit()
        new_id = cur.lastrowid
        await log_audit(
            db, user, "patient_cree", entity_type="patient", entity_id=new_id,
            patient_id=new_id, ip=client_ip(request),
        )
        if next_url:
            sep = "&" if "?" in next_url else "?"
            response = RedirectResponse(url=f"{next_url}{sep}patient_id={new_id}", status_code=302)
        else:
            response = RedirectResponse(url=f"/patients/{new_id}", status_code=302)
        set_flash(response, "Patient créé")
        return response
    except Exception as e:
        error = "Ce numéro CIN existe déjà." if "UNIQUE" in str(e) else str(e)
        patient_data = {
            "first_name": first_name, "last_name": last_name, "date_of_birth": date_of_birth,
            "gender": gender, "social_security_number": social_security_number,
            "identity_document_type": identity_document_type,
            "email": email, "phone": phone, "address": address, "city": city,
            "postal_code": postal_code, "blood_type": blood_type,
            "referring_doctor": referring_doctor, "referring_doctor_phone": referring_doctor_phone,
            "insurance_name": insurance_name,
            "insurance_number": insurance_number, "insurance_serial": insurance_serial,
            "emergency_contact_name": emergency_contact_name,
            "emergency_contact_phone": emergency_contact_phone,
            "emergency_contact_relation": emergency_contact_relation,
            "profession": profession, "marital_status": marital_status,
            "height_cm": height_i, "weight_kg": weight_f,
            "smoking": smoking, "alcohol": alcohol,
            "pregnant": pregnant_i, "breastfeeding": breastfeeding_i,
            "current_medications": current_medications, "gdpr_consent": gdpr_i,
            "notes": notes,
        }
        return templates.TemplateResponse(
            "patients/form.html",
            {"request": request, "user": user, "active": "patients", "patient": patient_data, "error": error},
        )


@router.get("/{patient_id}", response_class=HTMLResponse, dependencies=[Depends(deny_secretaire)])
async def view_patient(
    request: Request,
    patient_id: int,
    consultation_id: Optional[int] = None,
    tab: str = "info",
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    doctor_id = effective_doctor_id(user)
    cursor = await db.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, doctor_id))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/patients", status_code=302)
    patient = dict(row)

    await log_audit(
        db, user, "patient_consulte", entity_type="patient", entity_id=patient_id,
        patient_id=patient_id, ip=client_ip(request),
    )

    cursor = await db.execute(
        "SELECT * FROM medical_history WHERE patient_id = ? ORDER BY date_recorded DESC", (patient_id,)
    )
    history = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM appointments WHERE patient_id = ? ORDER BY start_datetime DESC LIMIT 10", (patient_id,)
    )
    appointments = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM consultations WHERE patient_id = ? AND (status IS NULL OR status = 'terminee') ORDER BY consultation_date DESC LIMIT 10",
        (patient_id,),
    )
    consultations = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY prescription_date DESC", (patient_id,)
    )
    prescriptions = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM documents WHERE patient_id = ? ORDER BY created_at DESC LIMIT 20", (patient_id,)
    )
    documents = [dict(r) for r in await cursor.fetchall()]
    previewable_exts = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    for d in documents:
        fp = d.get("file_path") or ""
        d["file_name"] = os.path.basename(fp)
        d["is_previewable"] = os.path.splitext(fp)[1].lower() in previewable_exts

    cursor = await db.execute(
        "SELECT * FROM feuilles_soin WHERE patient_id = ? ORDER BY created_at DESC LIMIT 30", (patient_id,)
    )
    feuilles_soin = [dict(r) for r in await cursor.fetchall()]

    # Detect active consultation session for this doctor+patient
    active_consultation = None
    if consultation_id:
        cursor = await db.execute(
            "SELECT * FROM consultations WHERE id = ? AND patient_id = ? AND doctor_id = ? AND status = 'en_cours'",
            (consultation_id, patient_id, doctor_id),
        )
        row = await cursor.fetchone()
        if row:
            active_consultation = dict(row)
    if active_consultation is None:
        cursor = await db.execute(
            """SELECT * FROM consultations
               WHERE patient_id = ? AND doctor_id = ? AND status = 'en_cours'
               ORDER BY created_at DESC LIMIT 1""",
            (patient_id, doctor_id),
        )
        row = await cursor.fetchone()
        if row:
            active_consultation = dict(row)

    # Décoder le questionnaire de début de consultation (QCM + texte libre)
    if active_consultation and active_consultation.get("intake_json"):
        try:
            active_consultation["intake"] = json.loads(active_consultation["intake_json"])
        except Exception:
            active_consultation["intake"] = None

    from datetime import datetime
    now_year = datetime.now().year
    user_specialty = user.get("specialty", "") or ""
    is_dentist = "dent" in user_specialty.lower()

    teeth_data_json = "{}"
    endo_summary_json = "{}"
    if is_dentist:
        cursor = await db.execute("SELECT * FROM dental_teeth WHERE patient_id = ?", (patient_id,))
        teeth_rows = await cursor.fetchall()
        teeth_data = {str(r["tooth_number"]): dict(r) for r in teeth_rows}
        teeth_data_json = json.dumps(teeth_data)

        cursor = await db.execute(
            "SELECT tooth_number, status FROM endo_canals WHERE patient_id = ?", (patient_id,)
        )
        endo_rows = await cursor.fetchall()
        status_priority = ["non_localise", "localise", "mesure", "prepare", "obture"]
        endo_summary: dict = {}
        for er in endo_rows:
            tn = str(er["tooth_number"])
            st = er["status"] or "non_localise"
            cur_st = endo_summary.get(tn, "non_localise")
            if status_priority.index(st) > status_priority.index(cur_st):
                endo_summary[tn] = st
        endo_summary_json = json.dumps(endo_summary)

    return templates.TemplateResponse(
        "patients/detail.html",
        {
            "request": request, "user": user, "active": "patients",
            "patient": patient, "history": history,
            "appointments": appointments, "consultations": consultations,
            "prescriptions": prescriptions, "documents": documents, "feuilles_soin": feuilles_soin,
            "now_year": now_year, "is_dentist": is_dentist,
            "teeth_data_json": teeth_data_json,
            "endo_summary_json": endo_summary_json,
            "active_consultation": active_consultation,
            "initial_tab": tab,
        },
    )


@router.get("/{patient_id}/edit", response_class=HTMLResponse)
async def edit_patient_form(
    request: Request,
    patient_id: int,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, effective_doctor_id(user)))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/patients", status_code=302)

    return templates.TemplateResponse(
        "patients/form.html",
        {"request": request, "user": user, "active": "patients", "patient": dict(row), "error": None},
    )


@router.post("/{patient_id}/edit", response_class=HTMLResponse)
async def update_patient(
    request: Request,
    patient_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(...),
    gender: str = Form(""),
    social_security_number: str = Form(""),
    identity_document_type: str = Form("CIN"),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    postal_code: str = Form(""),
    blood_type: str = Form(""),
    referring_doctor: str = Form(""),
    referring_doctor_phone: str = Form(""),
    insurance_name: str = Form(""),
    insurance_number: str = Form(""),
    insurance_serial: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    emergency_contact_relation: str = Form(""),
    profession: str = Form(""),
    marital_status: str = Form(""),
    height_cm: str = Form(""),
    weight_kg: str = Form(""),
    smoking: str = Form(""),
    alcohol: str = Form(""),
    pregnant: str = Form(""),
    breastfeeding: str = Form(""),
    current_medications: str = Form(""),
    gdpr_consent: str = Form(""),
    notes: str = Form(""),
    whatsapp_opt_out: str = Form(""),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    height_i = _parse_int(height_cm)
    weight_f = _parse_float(weight_kg)
    pregnant_i = 1 if pregnant in ("1", "on", "true", "yes") else 0
    breastfeeding_i = 1 if breastfeeding in ("1", "on", "true", "yes") else 0
    gdpr_i = 1 if gdpr_consent in ("1", "on", "true", "yes") else 0
    wa_opt_out_i = 1 if whatsapp_opt_out in ("1", "on", "true", "yes") else 0

    try:
        await db.execute(
            """UPDATE patients SET
                first_name=?, last_name=?, date_of_birth=?, gender=?, social_security_number=?,
                identity_document_type=?,
                email=?, phone=?, address=?, city=?, postal_code=?, blood_type=?,
                referring_doctor=?, referring_doctor_phone=?,
                insurance_name=?, insurance_number=?, insurance_serial=?,
                emergency_contact_name=?, emergency_contact_phone=?, emergency_contact_relation=?,
                profession=?, marital_status=?, height_cm=?, weight_kg=?, smoking=?, alcohol=?,
                pregnant=?, breastfeeding=?, current_medications=?, gdpr_consent=?, notes=?,
                whatsapp_opt_out=?,
                updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND doctor_id=?""",
            (
                first_name, last_name, date_of_birth,
                gender or None, social_security_number or None,
                identity_document_type or None,
                email or None, phone or None, address or None,
                city or None, postal_code or None, blood_type or None,
                referring_doctor or None, referring_doctor_phone or None,
                insurance_name or None, insurance_number or None, insurance_serial or None,
                emergency_contact_name or None, emergency_contact_phone or None, emergency_contact_relation or None,
                profession or None, marital_status or None, height_i, weight_f,
                smoking or None, alcohol or None,
                pregnant_i, breastfeeding_i, current_medications or None, gdpr_i, notes or None,
                wa_opt_out_i,
                patient_id, effective_doctor_id(user),
            ),
        )
        await db.commit()
        await log_audit(
            db, user, "patient_modifie", entity_type="patient", entity_id=patient_id,
            patient_id=patient_id, ip=client_ip(request),
        )
        response = RedirectResponse(url=f"/patients/{patient_id}", status_code=302)
        set_flash(response, "Patient modifié")
        return response
    except Exception as e:
        error = "Ce numéro CIN existe déjà." if "UNIQUE" in str(e) else str(e)
        patient_data = {"id": patient_id, "first_name": first_name, "last_name": last_name,
                        "date_of_birth": date_of_birth, "gender": gender,
                        "social_security_number": social_security_number,
                        "identity_document_type": identity_document_type,
                        "email": email, "phone": phone, "address": address, "city": city,
                        "postal_code": postal_code, "blood_type": blood_type,
                        "referring_doctor": referring_doctor,
                        "referring_doctor_phone": referring_doctor_phone,
                        "insurance_name": insurance_name,
                        "insurance_number": insurance_number, "insurance_serial": insurance_serial,
                        "emergency_contact_name": emergency_contact_name,
                        "emergency_contact_phone": emergency_contact_phone,
                        "emergency_contact_relation": emergency_contact_relation,
                        "profession": profession, "marital_status": marital_status,
                        "height_cm": height_i, "weight_kg": weight_f,
                        "smoking": smoking, "alcohol": alcohol,
                        "pregnant": pregnant_i, "breastfeeding": breastfeeding_i,
                        "current_medications": current_medications, "gdpr_consent": gdpr_i,
                        "notes": notes}
        return templates.TemplateResponse(
            "patients/form.html",
            {"request": request, "user": user, "active": "patients", "patient": patient_data, "error": error},
        )


@router.post("/{patient_id}/delete")
async def delete_patient(
    request: Request,
    patient_id: int,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Soft delete
    await db.execute("UPDATE patients SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND doctor_id = ?", (patient_id, effective_doctor_id(user)))
    await db.commit()
    await log_audit(
        db, user, "patient_supprime", entity_type="patient", entity_id=patient_id,
        patient_id=patient_id, ip=client_ip(request),
    )
    response = RedirectResponse(url="/patients", status_code=302)
    set_flash(response, "Patient supprimé")
    return response


@router.post("/{patient_id}/history", response_class=HTMLResponse)
async def add_history(
    request: Request,
    patient_id: int,
    type: str = Form(...),
    description: str = Form(...),
    date_recorded: str = Form(""),
    consultation_id: Optional[int] = Form(None),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Only the owning doctor may append history to a patient record.
    cursor = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cursor.fetchone():
        return RedirectResponse(url="/patients", status_code=302)

    await db.execute(
        "INSERT INTO medical_history (patient_id, type, description, date_recorded, consultation_id) VALUES (?, ?, ?, ?, ?)",
        (patient_id, type, description, date_recorded or None, consultation_id),
    )
    await db.commit()
    await log_audit(db, user, "antecedent_ajoute", entity_type="patient", entity_id=patient_id, patient_id=patient_id, ip=client_ip(request))
    redirect = f"/patients/{patient_id}?tab=info"
    if consultation_id:
        redirect += f"&consultation_id={consultation_id}"
    resp = RedirectResponse(url=redirect, status_code=302)
    set_flash(resp, "Antécédent ajouté")
    return resp


@router.post("/{patient_id}/history/{history_id}/edit", response_class=HTMLResponse)
async def edit_history(
    request: Request,
    patient_id: int,
    history_id: int,
    type: str = Form(...),
    description: str = Form(...),
    date_recorded: str = Form(""),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    # L'antécédent doit appartenir à un patient du praticien.
    cursor = await db.execute(
        """SELECT h.id FROM medical_history h JOIN patients p ON h.patient_id = p.id
           WHERE h.id = ? AND h.patient_id = ? AND p.doctor_id = ?""",
        (history_id, patient_id, user["sub"]),
    )
    if not await cursor.fetchone():
        return RedirectResponse(url="/patients", status_code=302)
    if type not in ("medical", "surgical", "family", "allergy"):
        type = "medical"

    await db.execute(
        "UPDATE medical_history SET type = ?, description = ?, date_recorded = ? WHERE id = ? AND patient_id = ?",
        (type, description, date_recorded or None, history_id, patient_id),
    )
    await db.commit()
    await log_audit(db, user, "antecedent_modifie", entity_type="patient", entity_id=patient_id, patient_id=patient_id, ip=client_ip(request))
    resp = RedirectResponse(url=f"/patients/{patient_id}?tab=info", status_code=302)
    set_flash(resp, "Antécédent modifié")
    return resp


@router.post("/{patient_id}/history/{history_id}/delete", response_class=HTMLResponse)
async def delete_history(
    request: Request,
    patient_id: int,
    history_id: int,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        """SELECT h.id FROM medical_history h JOIN patients p ON h.patient_id = p.id
           WHERE h.id = ? AND h.patient_id = ? AND p.doctor_id = ?""",
        (history_id, patient_id, user["sub"]),
    )
    if not await cursor.fetchone():
        return RedirectResponse(url="/patients", status_code=302)

    await db.execute("DELETE FROM medical_history WHERE id = ? AND patient_id = ?", (history_id, patient_id))
    await db.commit()
    await log_audit(db, user, "antecedent_supprime", entity_type="patient", entity_id=patient_id, patient_id=patient_id, ip=client_ip(request))
    resp = RedirectResponse(url=f"/patients/{patient_id}?tab=info", status_code=302)
    set_flash(resp, "Antécédent supprimé")
    return resp


@router.get("/{patient_id}/brochure.pdf", dependencies=[Depends(deny_secretaire)])
async def patient_brochure_pdf(request: Request, patient_id: int, dl: int = 0, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ? AND is_active = 1", (patient_id, user["sub"]))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/patients", status_code=302)
    patient = dict(row)

    cursor = await db.execute(
        "SELECT * FROM medical_history WHERE patient_id = ? ORDER BY date_recorded DESC", (patient_id,)
    )
    history = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM appointments WHERE patient_id = ? AND status NOT IN ('annule','absent') ORDER BY start_datetime ASC LIMIT 10",
        (patient_id,)
    )
    appointments = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY prescription_date DESC LIMIT 3",
        (patient_id,)
    )
    rx_rows = [dict(r) for r in await cursor.fetchall()]
    for rx in rx_rows:
        cursor2 = await db.execute(
            "SELECT * FROM prescription_items WHERE prescription_id = ?", (rx["id"],)
        )
        rx["items"] = [dict(i) for i in await cursor2.fetchall()]

    cursor = await db.execute(
        "SELECT first_name, last_name, specialty, phone, address, pdf_template_path FROM users WHERE id = ?",
        (patient.get("doctor_id"),),
    )
    trow = await cursor.fetchone()
    template_path = trow["pdf_template_path"] if trow else None
    doctor_name = f"Dr. {trow['first_name']} {trow['last_name']}" if trow else ""
    specialty = (trow["specialty"] if trow else "") or ""
    doc_phone = (trow["phone"] if trow else None)
    doc_address = (trow["address"] if trow else None)

    # État dentaire (odontogramme) — dents non saines uniquement.
    cursor = await db.execute(
        "SELECT tooth_number, condition, notes FROM dental_teeth WHERE patient_id = ? AND condition IS NOT NULL AND condition != 'sain' ORDER BY tooth_number",
        (patient_id,),
    )
    dental = [dict(r) for r in await cursor.fetchall()]

    from services.pdf_service import generate_patient_brochure_pdf
    pdf_bytes = generate_patient_brochure_pdf(
        patient, history, appointments, rx_rows, template_path,
        doctor_name=doctor_name, specialty=specialty,
        address=doc_address, phone=doc_phone, dental=dental,
    )
    filename = f"fiche_{patient['last_name'].lower()}_{patient['first_name'].lower()}.pdf"
    disp = "attachment" if dl else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )
