from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import io
import json
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/consultations")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DENTAL_HISTORY_PRESETS = [
    "Diabète",
    "HTA",
    "Cardiopathie",
    "Trouble de coagulation",
    "Allergie médicamenteuse",
    "Allergie au latex",
    "Hépatite",
    "VIH",
    "Grossesse",
    "Traitement anticoagulant",
    "Bisphosphonates",
    "Radiothérapie cervico-faciale",
    "Prothèse valvulaire",
    "Endocardite",
    "Autre",
]


def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip()


# --- Examen clinique dentaire structuré (douleur spontanée, sensibilité, etc.) ---
# Champs à choix unique (radio)
DENTAL_EXAM_SINGLE = [
    ("douleur_spontanee", "de_douleur_spontanee", "Douleur spontanée"),
    ("sensibilite", "de_sensibilite", "Test de sensibilité"),
    ("mobilite", "de_mobilite", "Mobilité dentaire"),
    ("oedeme_godet", "de_oedeme_godet", "Signe du godet (extra-oral)"),
]
# Champs à choix multiple (cases à cocher) — stockés en liste
DENTAL_EXAM_MULTI = [
    ("percussion", "de_percussion", "Percussion"),
    ("palpation", "de_palpation", "Palpation apicale"),
]
# Drapeaux (présence Oui/Non) avec description multiple optionnelle (consistance, etc.)
# (clé json, champ, libellé, clé description, champ description)
DENTAL_EXAM_FLAGS = [
    ("tumefaction", "de_tumefaction", "Tuméfaction / œdème intra-oral", "tumefaction_desc", "de_tumefaction_desc"),
    ("oedeme_extra", "de_oedeme_extra", "Œdème / tuméfaction extra-orale", "oedeme_extra_desc", "de_oedeme_extra_desc"),
    ("saignement", "de_saignement", "Saignement gingival", None, None),
]
# Ordre + libellés pour le résumé lisible
DENTAL_EXAM_LABELS = {key: label for key, _f, label in DENTAL_EXAM_SINGLE + DENTAL_EXAM_MULTI}
DENTAL_EXAM_LABELS.update({key: label for key, _f, label, _dk, _df in DENTAL_EXAM_FLAGS})
DENTAL_EXAM_DISPLAY_ORDER = [
    "douleur_spontanee", "sensibilite", "percussion", "palpation", "mobilite",
    "tumefaction", "oedeme_extra", "oedeme_godet", "saignement",
]


def _build_dental_exam_json(form) -> Optional[str]:
    """Sérialise les champs structurés de l'examen clinique dentaire en JSON."""
    de: dict = {}
    for key, field, _label in DENTAL_EXAM_SINGLE:
        v = _clean_text(form.get(field))
        if v:
            de[key] = v
    for key, field, _label in DENTAL_EXAM_MULTI:
        vals = [_clean_text(v) for v in form.getlist(field) if _clean_text(v)]
        if vals:
            de[key] = vals
    for key, field, _label, desc_key, desc_field in DENTAL_EXAM_FLAGS:
        if _clean_text(form.get(field)):
            de[key] = True
            if desc_field:
                descs = [_clean_text(v) for v in form.getlist(desc_field) if _clean_text(v)]
                if descs:
                    de[desc_key] = descs
    # Le signe du godet ne décrit l'œdème extra-oral que si celui-ci est coché
    # (le radio reste sélectionné même si la case est décochée puis masquée en CSS).
    if not de.get("oedeme_extra"):
        de.pop("oedeme_godet", None)
    return json.dumps(de, ensure_ascii=False) if de else None


def _format_dental_exam(exam_json: Optional[str]) -> list[str]:
    """Transforme l'examen structuré en lignes lisibles pour le résumé/affichage."""
    try:
        de = json.loads(exam_json) if exam_json else {}
    except Exception:
        de = {}
    if not isinstance(de, dict):
        return []
    lines: list[str] = []
    for key in DENTAL_EXAM_DISPLAY_ORDER:
        if key not in de or not de[key]:
            continue
        label = DENTAL_EXAM_LABELS.get(key, key)
        val = de[key]
        if val is True:
            text = "Oui"
            desc = de.get(f"{key}_desc")
            if isinstance(desc, list) and desc:
                text += " (" + ", ".join(str(d) for d in desc) + ")"
            elif desc:
                text += f" ({desc})"
        elif isinstance(val, list):
            text = ", ".join(str(v) for v in val)
        else:
            text = str(val)
        lines.append(f"{label} : {text}")
    return lines


def _decode_vitals_notes(raw_notes: Optional[str]) -> dict:
    if not raw_notes:
        return {}
    try:
        payload = json.loads(raw_notes)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _merge_history_options(patient_history: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in patient_history + DENTAL_HISTORY_PRESETS:
        item = _clean_text(value)
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


async def _fetch_patient_history(
    db: aiosqlite.Connection,
    patient_id: Optional[int],
    doctor_id: int,
) -> list[str]:
    if not patient_id:
        return []

    cursor = await db.execute(
        "SELECT id FROM patients WHERE id = ? AND doctor_id = ? AND is_active = 1",
        (patient_id, doctor_id),
    )
    if not await cursor.fetchone():
        return []

    cursor = await db.execute(
        """SELECT type, description
           FROM medical_history
           WHERE patient_id = ? AND trim(COALESCE(description, '')) != ''
           ORDER BY date_recorded DESC, created_at DESC""",
        (patient_id,),
    )
    rows = await cursor.fetchall()

    history: list[str] = []
    seen: set[str] = set()
    type_labels = {
        "medical": "Médical",
        "surgical": "Chirurgical",
        "family": "Familial",
        "allergy": "Allergie",
    }
    for row in rows:
        desc = _clean_text(row["description"])
        if not desc:
            continue
        history_type = _clean_text(row["type"]).lower()
        if history_type == "medical":
            formatted = desc
        else:
            type_label = type_labels.get(history_type, history_type.title() if history_type else "Médical")
            formatted = f"{type_label}: {desc}"
        key = formatted.casefold()
        if key in seen:
            continue
        seen.add(key)
        history.append(formatted)

    return history


async def _fetch_patient_allergies(db: aiosqlite.Connection, patient_id: Optional[int]) -> str:
    """Return the most recent allergy description for a patient, or empty string."""
    if not patient_id:
        return ""
    cursor = await db.execute(
        "SELECT description FROM medical_history WHERE patient_id = ? AND type = 'allergy' ORDER BY date_recorded DESC, created_at DESC LIMIT 1",
        (patient_id,),
    )
    row = await cursor.fetchone()
    return _clean_text(row[0]) if row else ""


async def _save_history_item_if_new(
    db: aiosqlite.Connection,
    patient_id: Optional[int],
    entry: str,
) -> None:
    value = _clean_text(entry)
    if not patient_id or not value:
        return

    # Le préfixe "Type: …" n'est interprété que s'il correspond à un type connu
    # (ex. les wrappers internes "Allergie: X"). Sinon, le texte libre est conservé
    # tel quel (un ':' saisi par l'utilisateur ne doit pas tronquer l'antécédent).
    type_by_prefix = {
        "médical": "medical",
        "medical": "medical",
        "chirurgical": "surgical",
        "familial": "family",
        "allergie": "allergy",
        "allergy": "allergy",
    }
    history_type = "medical"
    description = value
    if ":" in value:
        prefix, desc = value.split(":", 1)
        prefix_key = _clean_text(prefix).casefold()
        desc = _clean_text(desc)
        if prefix_key in type_by_prefix and desc:
            history_type = type_by_prefix[prefix_key]
            description = desc

    cursor = await db.execute(
        """SELECT 1 FROM medical_history
           WHERE patient_id = ? AND type = ? AND lower(trim(description)) = lower(?)
           LIMIT 1""",
        (patient_id, history_type, description),
    )
    if await cursor.fetchone():
        return

    await db.execute(
        "INSERT INTO medical_history (patient_id, type, description, date_recorded) VALUES (?, ?, ?, DATE('now'))",
        (patient_id, history_type, description),
    )


async def _persist_intake_patient_data(
    db: aiosqlite.Connection,
    patient_id: int,
    doctor_id,
    pathologies: list[str],
    allergies: list[str],
    tabac_statut: str,
    tabac_paquets: str,
) -> None:
    """Enregistre sur la fiche patient les antécédents/allergies/tabac saisis dans le
    questionnaire de début de consultation (indépendant de la consultation active)."""
    for pathologie in pathologies:
        await _save_history_item_if_new(db, patient_id, pathologie)
    for allergie in allergies:
        await _save_history_item_if_new(db, patient_id, f"Allergie: {allergie}")
    if tabac_statut:
        if tabac_statut == "Non":
            smoking_val = "Non"
        elif tabac_paquets:
            smoking_val = f"{tabac_statut} — {tabac_paquets} paquet(s)/jour"
        else:
            smoking_val = tabac_statut
        await db.execute(
            "UPDATE patients SET smoking = ? WHERE id = ? AND doctor_id = ?",
            (smoking_val, patient_id, doctor_id),
        )


@router.get("/", response_class=HTMLResponse)
async def list_consultations(
    request: Request,
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    uid = user["sub"]
    per_page = 20
    offset = (page - 1) * per_page

    base_query = """FROM consultations c
        JOIN patients p ON c.patient_id = p.id
        JOIN users u ON c.doctor_id = u.id
        WHERE c.doctor_id = ? AND (c.status IS NULL OR c.status = 'terminee')"""
    params: list = [uid]

    if q:
        like = f"%{q.strip().lower()}%"
        base_query += """ AND (lower(p.first_name) LIKE ? OR lower(p.last_name) LIKE ?
                          OR lower(c.reason) LIKE ? OR lower(c.diagnosis) LIKE ?)"""
        params.extend([like, like, like, like])

    if date_from:
        base_query += " AND c.consultation_date >= ?"
        params.append(date_from)

    if date_to:
        base_query += " AND c.consultation_date <= ?"
        params.append(date_to)

    count_cursor = await db.execute(f"SELECT COUNT(*) {base_query}", params)
    total_count = (await count_cursor.fetchone())[0]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    cursor = await db.execute(
        f"""SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name,
                   u.first_name || ' ' || u.last_name AS doctor_name
            {base_query} ORDER BY c.consultation_date DESC LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    )
    consultations = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/list.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultations": consultations,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_consultation_form(
    request: Request,
    patient_id: Optional[int] = None,
    appointment_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    uid = user["sub"]
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name",
        (uid,),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
    )
    doctors = [dict(r) for r in await cursor.fetchall()]

    patient_history = await _fetch_patient_history(db, patient_id, uid)

    return templates.TemplateResponse(
        "consultations/form.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultation": None,
            "patients": patients,
            "doctors": doctors,
            "selected_patient_id": patient_id,
            "selected_appointment_id": appointment_id,
            "dental_history_options": _merge_history_options(patient_history),
            "selected_dental_history": "",
            "selected_dental_allergies": await _fetch_patient_allergies(db, patient_id),
            "dental_history_presets_json": json.dumps(DENTAL_HISTORY_PRESETS, ensure_ascii=False),
            "error": None,
        },
    )


@router.get("/patient/{patient_id}/history")
async def patient_history_for_consultation(
    request: Request,
    patient_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    history = await _fetch_patient_history(db, patient_id, user["sub"])
    return JSONResponse(content={"items": history})


@router.post("/new", response_class=HTMLResponse)
async def create_consultation(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()

    def _int(key):
        try:
            v = form.get(key, "")
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    def _float(key):
        try:
            v = form.get(key, "")
            return float(v) if v else None
        except (ValueError, TypeError):
            return None

    patient_id = _int("patient_id")
    doctor_id = _int("doctor_id")
    dental_medical_history = _clean_text(form.get("dental_medical_history"))
    dental_allergies = _clean_text(form.get("dental_allergies"))

    if not patient_id or not doctor_id:
        cursor = await db.execute(
            "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name",
            (user["sub"],),
        )
        patients = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name"
        )
        doctors = [dict(r) for r in await cursor.fetchall()]
        patient_history = await _fetch_patient_history(db, patient_id, user["sub"])
        return templates.TemplateResponse(
            "consultations/form.html",
            {
                "request": request,
                "user": user,
                "active": "consultations",
                "consultation": None,
                "patients": patients,
                "doctors": doctors,
                "selected_patient_id": patient_id,
                "selected_appointment_id": _int("appointment_id"),
                "dental_history_options": _merge_history_options(patient_history),
                "selected_dental_history": dental_medical_history,
                "selected_dental_allergies": dental_allergies,
                "dental_history_presets_json": json.dumps(DENTAL_HISTORY_PRESETS, ensure_ascii=False),
                "error": "Veuillez sélectionner un patient et un praticien.",
            },
        )

    appointment_id = _int("appointment_id")
    reason = form.get("reason", "") or None
    symptoms = form.get("symptoms", "") or None
    clinical_exam = form.get("clinical_exam", "") or None
    dental_exam_json = _build_dental_exam_json(form)
    diagnosis = form.get("diagnosis", "") or None
    treatment_plan = form.get("treatment_plan", "") or None
    notes = form.get("notes", "") or None
    weight = _float("weight")
    height = _float("height")
    blood_pressure_sys = _int("blood_pressure_sys")
    blood_pressure_dia = _int("blood_pressure_dia")
    heart_rate = _int("heart_rate")
    temperature = _float("temperature")
    spo2 = _float("spo2")

    vitals_notes_payload = {}
    if dental_medical_history:
        vitals_notes_payload["dental_medical_history"] = dental_medical_history
    if dental_allergies:
        vitals_notes_payload["dental_allergies"] = dental_allergies
    vitals_notes = json.dumps(vitals_notes_payload, ensure_ascii=False) if vitals_notes_payload else None

    cursor = await db.execute(
        """INSERT INTO consultations (patient_id, doctor_id, appointment_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes, dental_exam_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, doctor_id, appointment_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes, dental_exam_json),
    )
    consultation_id = cursor.lastrowid

    has_vitals = any(
        v is not None
        for v in [weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2]
    ) or (vitals_notes is not None)

    if has_vitals:
        await db.execute(
            """INSERT INTO vitals (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, vitals_notes),
        )

    await _save_history_item_if_new(db, patient_id, dental_medical_history)
    if dental_allergies:
        await _save_history_item_if_new(db, patient_id, f"Allergie: {dental_allergies}")

    if appointment_id:
        await db.execute(
            "UPDATE appointments SET status = 'termine', updated_at = CURRENT_TIMESTAMP WHERE id = ? ",
            (appointment_id,),
        )

    await db.commit()
    return RedirectResponse(url=f"/consultations/{consultation_id}", status_code=302)


@router.post("/start")
async def start_consultation(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    try:
        patient_id = int(form.get("patient_id", 0))
    except (ValueError, TypeError):
        return RedirectResponse(url="/patients", status_code=302)
    appointment_id_raw = form.get("appointment_id")
    appointment_id = int(appointment_id_raw) if appointment_id_raw else None
    uid = user["sub"]

    # Questionnaire de début de consultation (QCM + texte libre)
    intake: dict = {}

    def _list(field: str) -> list[str]:
        return [_clean_text(v) for v in form.getlist(field) if _clean_text(v)]

    def _split_extra(value: str) -> list[str]:
        return [p.strip() for p in _clean_text(value).replace(";", ",").split(",") if p.strip()]

    motifs = _list("intake_motif")
    arcade = _list("intake_arcade")
    cote = _list("intake_cote")
    douleur = _clean_text(form.get("intake_douleur"))
    caractere = _list("intake_caractere")
    depuis = _clean_text(form.get("intake_depuis"))
    pathologies = _list("intake_pathologies") + _split_extra(form.get("intake_pathologies_autres"))
    allergies = _list("intake_allergies") + _split_extra(form.get("intake_allergies_autres"))
    tabac_statut = _clean_text(form.get("intake_tabac"))
    tabac_paquets = _clean_text(form.get("intake_tabac_paquets"))
    habitudes = _list("intake_habitudes")
    intake_notes = _clean_text(form.get("intake_notes"))

    if motifs:
        intake["motif"] = motifs
    if arcade:
        intake["arcade"] = arcade
    if cote:
        intake["cote"] = cote
    if douleur:
        intake["douleur"] = douleur
    if caractere:
        intake["caractere"] = caractere
    if depuis:
        intake["depuis"] = depuis
    if pathologies:
        intake["antecedents"] = pathologies
    if allergies:
        intake["allergies"] = allergies
    # Le nombre de paquets n'a de sens qu'avec un statut tabagique → on n'enregistre
    # le tabac (intake + colonne patients.smoking) que si un statut est sélectionné.
    if tabac_statut:
        tabac: dict = {"statut": tabac_statut}
        if tabac_paquets:
            tabac["paquets_jour"] = tabac_paquets
        intake["tabac"] = tabac
    if habitudes:
        intake["habitudes"] = habitudes
    if intake_notes:
        intake["notes"] = intake_notes
    intake_json = json.dumps(intake, ensure_ascii=False) if intake else None

    motif = ", ".join(motifs) if motifs else ""

    # Guard: resume existing en_cours session (ne pas écraser le questionnaire existant)
    cursor = await db.execute(
        """SELECT id FROM consultations
           WHERE patient_id = ? AND doctor_id = ? AND status = 'en_cours'
           ORDER BY created_at DESC LIMIT 1""",
        (patient_id, uid),
    )
    existing = await cursor.fetchone()
    if existing:
        # On ne réécrit pas le questionnaire d'une session déjà en cours, mais les
        # données patient (antécédents/allergies/tabac) saisies doivent être conservées.
        await _persist_intake_patient_data(db, patient_id, uid, pathologies, allergies, tabac_statut, tabac_paquets)
        # Compléter le questionnaire de la session existante seulement s'il est vide.
        if intake_json:
            cur2 = await db.execute("SELECT intake_json, reason FROM consultations WHERE id = ?", (existing["id"],))
            row2 = await cur2.fetchone()
            if row2 and not _clean_text(row2["intake_json"]):
                await db.execute(
                    "UPDATE consultations SET intake_json = ?, reason = COALESCE(NULLIF(TRIM(reason), ''), ?) WHERE id = ?",
                    (intake_json, motif or None, existing["id"]),
                )
        await db.commit()
        return RedirectResponse(
            url=f"/patients/{patient_id}?consultation_id={existing['id']}",
            status_code=302,
        )

    if appointment_id:
        await db.execute(
            "UPDATE appointments SET status = 'en_cours', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (appointment_id,),
        )

    cursor = await db.execute(
        """INSERT INTO consultations (patient_id, doctor_id, appointment_id, status, consultation_date, reason, intake_json)
           VALUES (?, ?, ?, 'en_cours', CURRENT_TIMESTAMP, ?, ?)""",
        (patient_id, uid, appointment_id, motif or None, intake_json),
    )
    consultation_id = cursor.lastrowid

    # Persister antécédents / allergies / tabac sur la fiche patient
    await _persist_intake_patient_data(db, patient_id, uid, pathologies, allergies, tabac_statut, tabac_paquets)

    await db.commit()

    return RedirectResponse(
        url=f"/patients/{patient_id}?consultation_id={consultation_id}",
        status_code=302,
    )


@router.get("/{consultation_id}", response_class=HTMLResponse)
async def view_consultation(request: Request, consultation_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name, p.date_of_birth, p.gender, p.id AS pid, u.first_name || ' ' || u.last_name AS doctor_name FROM consultations c JOIN patients p ON c.patient_id = p.id JOIN users u ON c.doctor_id = u.id WHERE c.id = ? """,
        (consultation_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/consultations", status_code=302)
    consultation = dict(row)

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    vitals = dict(vitals_row) if vitals_row else None

    cursor = await db.execute(
        """SELECT p.*, GROUP_CONCAT(pi.medication_name || ' - ' || pi.dosage, ' | ') AS items_summary FROM prescriptions p LEFT JOIN prescription_items pi ON p.id = pi.prescription_id WHERE p.consultation_id = ? GROUP BY p.id""",
        (consultation_id,),
    )
    prescriptions = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "consultations/detail.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultation": consultation,
            "vitals": vitals,
            "prescriptions": prescriptions,
        },
    )


@router.get("/{consultation_id}/pdf")
async def consultation_pdf(request: Request, consultation_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT c.*, p.first_name || ' ' || p.last_name AS patient_name, p.date_of_birth, p.gender, u.first_name || ' ' || u.last_name AS doctor_name, u.pdf_template_path FROM consultations c JOIN patients p ON c.patient_id = p.id JOIN users u ON c.doctor_id = u.id WHERE c.id = ? """,
        (consultation_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/consultations", status_code=302)
    consultation = dict(row)

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    vitals = dict(vitals_row) if vitals_row else None

    from services.pdf_service import generate_consultation_pdf

    pdf_bytes = generate_consultation_pdf(consultation, vitals, consultation.get("summary"), consultation.get("pdf_template_path"))
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=consultation_{consultation_id}.pdf"},
    )


@router.get("/{consultation_id}/edit", response_class=HTMLResponse)
async def edit_consultation_form(request: Request, consultation_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT * FROM consultations WHERE id = ? ", (consultation_id,))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/consultations", status_code=302)
    consultation = dict(row)

    selected_dental_history = ""
    selected_dental_allergies = ""

    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    vitals_row = await cursor.fetchone()
    if vitals_row:
        vitals_data = dict(vitals_row)
        consultation.update({f"v_{k}": v for k, v in vitals_data.items()})
        notes_payload = _decode_vitals_notes(vitals_data.get("notes"))
        selected_dental_history = _clean_text(notes_payload.get("dental_medical_history"))
        selected_dental_allergies = _clean_text(notes_payload.get("dental_allergies"))

    if not selected_dental_allergies:
        selected_dental_allergies = await _fetch_patient_allergies(db, consultation["patient_id"])

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name",
        (user["sub"],),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]

    patient_history = await _fetch_patient_history(db, consultation["patient_id"], user["sub"])

    return templates.TemplateResponse(
        "consultations/form.html",
        {
            "request": request,
            "user": user,
            "active": "consultations",
            "consultation": consultation,
            "patients": patients,
            "doctors": doctors,
            "selected_patient_id": consultation["patient_id"],
            "selected_appointment_id": consultation.get("appointment_id"),
            "dental_history_options": _merge_history_options(patient_history),
            "selected_dental_history": selected_dental_history,
            "selected_dental_allergies": selected_dental_allergies,
            "dental_history_presets_json": json.dumps(DENTAL_HISTORY_PRESETS, ensure_ascii=False),
            "error": None,
        },
    )


@router.post("/{consultation_id}/edit")
async def update_consultation(
    request: Request,
    consultation_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()

    def _int(key):
        try:
            v = form.get(key, "")
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    def _float(key):
        try:
            v = form.get(key, "")
            return float(v) if v else None
        except (ValueError, TypeError):
            return None

    patient_id = _int("patient_id")
    doctor_id = _int("doctor_id")
    reason = form.get("reason", "") or None
    symptoms = form.get("symptoms", "") or None
    clinical_exam = form.get("clinical_exam", "") or None
    dental_exam_json = _build_dental_exam_json(form)
    diagnosis = form.get("diagnosis", "") or None
    treatment_plan = form.get("treatment_plan", "") or None
    notes = form.get("notes", "") or None
    weight = _float("weight")
    height = _float("height")
    blood_pressure_sys = _int("blood_pressure_sys")
    blood_pressure_dia = _int("blood_pressure_dia")
    heart_rate = _int("heart_rate")
    temperature = _float("temperature")
    spo2 = _float("spo2")
    dental_medical_history = _clean_text(form.get("dental_medical_history"))
    dental_allergies = _clean_text(form.get("dental_allergies"))

    vitals_notes_payload = {}
    if dental_medical_history:
        vitals_notes_payload["dental_medical_history"] = dental_medical_history
    if dental_allergies:
        vitals_notes_payload["dental_allergies"] = dental_allergies
    vitals_notes = json.dumps(vitals_notes_payload, ensure_ascii=False) if vitals_notes_payload else None

    await db.execute(
        """UPDATE consultations SET patient_id= ?, doctor_id= ?, reason= ?, symptoms= ?, clinical_exam= ?, diagnosis= ?, treatment_plan= ?, notes= ?, dental_exam_json= ?, updated_at=CURRENT_TIMESTAMP WHERE id= ? """,
        (patient_id, doctor_id, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes, dental_exam_json, consultation_id),
    )

    cursor = await db.execute("SELECT id FROM vitals WHERE consultation_id = ? ", (consultation_id,))
    existing = await cursor.fetchone()
    if existing:
        await db.execute(
            """UPDATE vitals SET patient_id= ?, weight= ?, height= ?, blood_pressure_sys= ?, blood_pressure_dia= ?, heart_rate= ?, temperature= ?, spo2= ?, notes= ? WHERE consultation_id= ? """,
            (patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, vitals_notes, consultation_id),
        )
    elif any(v is not None for v in [weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2]) or vitals_notes is not None:
        await db.execute(
            """INSERT INTO vitals (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2, vitals_notes),
        )

    await _save_history_item_if_new(db, patient_id, dental_medical_history)
    if dental_allergies:
        await _save_history_item_if_new(db, patient_id, f"Allergie: {dental_allergies}")

    await db.commit()
    return RedirectResponse(url=f"/consultations/{consultation_id}", status_code=302)


# ---------------------------------------------------------------------------
# Consultation workflow: start / summary-data / terminate
# ---------------------------------------------------------------------------

async def _build_summary(
    db: aiosqlite.Connection,
    consultation_id: int,
    reason: Optional[str],
    diagnosis: Optional[str],
    treatment_plan: Optional[str],
    clinical_exam: Optional[str] = None,
    dental_exam_json: Optional[str] = None,
) -> str:
    parts = []

    if reason:
        parts.append(f"Motif : {reason}")

    exam_lines = _format_dental_exam(dental_exam_json)
    ce = _clean_text(clinical_exam)
    if exam_lines or ce:
        block = "Examen clinique :"
        if exam_lines:
            block += "\n  - " + "\n  - ".join(exam_lines)
        if ce:
            block += ("\n  " + ce) if exam_lines else (" " + ce)
        parts.append(block)

    if diagnosis:
        parts.append(f"Diagnostic : {diagnosis}")
    if treatment_plan:
        parts.append(f"Plan de traitement : {treatment_plan}")

    # Constantes vitales
    cursor = await db.execute("SELECT * FROM vitals WHERE consultation_id = ?", (consultation_id,))
    vitals_row = await cursor.fetchone()
    if vitals_row:
        v = dict(vitals_row)
        v_parts = []
        if v.get("weight"): v_parts.append(f"Poids : {v['weight']} kg")
        if v.get("height"): v_parts.append(f"Taille : {v['height']} cm")
        if v.get("blood_pressure_sys") and v.get("blood_pressure_dia"):
            v_parts.append(f"TA : {v['blood_pressure_sys']}/{v['blood_pressure_dia']} mmHg")
        if v.get("heart_rate"): v_parts.append(f"FC : {v['heart_rate']} bpm")
        if v.get("temperature"): v_parts.append(f"Température : {v['temperature']} °C")
        if v.get("spo2"): v_parts.append(f"SpO₂ : {v['spo2']} %")
        if v_parts:
            parts.append("Constantes vitales : " + ", ".join(v_parts))

    # Ordonnances
    cursor = await db.execute(
        """SELECT p.id, GROUP_CONCAT(pi.medication_name || ' ' || pi.dosage, ' | ') AS meds
           FROM prescriptions p
           LEFT JOIN prescription_items pi ON p.id = pi.prescription_id
           WHERE p.consultation_id = ?
           GROUP BY p.id""",
        (consultation_id,),
    )
    rxs = await cursor.fetchall()
    if rxs:
        rx_lines = [f"  - Ordonnance #{r['id']}: {r['meds'] or 'vide'}" for r in rxs]
        parts.append("Ordonnances :\n" + "\n".join(rx_lines))

    # Antécédents / modifications médicales
    cursor = await db.execute(
        "SELECT type, description FROM medical_history WHERE consultation_id = ?",
        (consultation_id,),
    )
    ants = await cursor.fetchall()
    if ants:
        ant_lines = [f"  - [{r['type']}] {r['description']}" for r in ants]
        parts.append("Antécédents ajoutés :\n" + "\n".join(ant_lines))

    # Actes dentaires (avec le RDV créé)
    cursor = await db.execute(
        """SELECT dt.tooth_number, dt.treatment_type, dt.description,
                  a.start_datetime AS appt_date
           FROM dental_treatments dt
           LEFT JOIN appointments a ON dt.appointment_id = a.id
           WHERE dt.consultation_id = ?
           ORDER BY dt.tooth_number""",
        (consultation_id,),
    )
    dental = await cursor.fetchall()
    if dental:
        d_lines = []
        for r in dental:
            appt_str = f" (RDV : {r['appt_date'][:10] if r['appt_date'] else '—'})" if r['appt_date'] else ""
            d_lines.append(f"  - Dent {r['tooth_number']}: {r['treatment_type']} — {r['description'] or ''}{appt_str}")
        parts.append("Actes dentaires :\n" + "\n".join(d_lines))

    # Modifications endodontiques
    cursor = await db.execute(
        """SELECT tooth_number, canal_name, field, old_value, new_value
           FROM endo_history
           WHERE consultation_id = ?
           ORDER BY tooth_number, canal_name, changed_at""",
        (consultation_id,),
    )
    endo_changes = await cursor.fetchall()
    if endo_changes:
        e_lines = [
            f"  - Dent {r['tooth_number']}, {r['canal_name']} — {r['field']} : {r['old_value'] or '—'} → {r['new_value'] or '—'}"
            for r in endo_changes
        ]
        parts.append("Modifications endodontiques :\n" + "\n".join(e_lines))

    # Changements de condition dentaire
    cursor = await db.execute(
        """SELECT tooth_number, condition, notes
           FROM dental_condition_history
           WHERE consultation_id = ?
           ORDER BY tooth_number, changed_at""",
        (consultation_id,),
    )
    cond_changes = await cursor.fetchall()
    if cond_changes:
        c_lines = [
            f"  - Dent {r['tooth_number']}: {r['condition']}" + (f" ({r['notes']})" if r['notes'] else "")
            for r in cond_changes
        ]
        parts.append("Changements de condition dentaire :\n" + "\n".join(c_lines))

    # Feuilles de soin
    cursor = await db.execute(
        "SELECT mutuelle, type_feuille, total_montant FROM feuilles_soin WHERE consultation_id = ?",
        (consultation_id,),
    )
    feuilles = await cursor.fetchall()
    if feuilles:
        f_lines = [f"  - {r['mutuelle']} ({r['type_feuille']}) — {r['total_montant'] or 0:.2f} Dh" for r in feuilles]
        parts.append("Feuilles de soin :\n" + "\n".join(f_lines))

    # Documents ajoutés
    cursor = await db.execute(
        "SELECT title, category FROM documents WHERE consultation_id = ?",
        (consultation_id,),
    )
    docs = await cursor.fetchall()
    if docs:
        doc_lines = [f"  - {r['title']} [{r['category']}]" for r in docs]
        parts.append("Documents ajoutés :\n" + "\n".join(doc_lines))

    return "\n\n".join(parts) if parts else "Consultation sans résumé."


@router.get("/{consultation_id}/summary-data")
async def get_summary_data(
    request: Request,
    consultation_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    cursor = await db.execute(
        """SELECT p.id, GROUP_CONCAT(pi.medication_name, ', ') AS meds
           FROM prescriptions p
           LEFT JOIN prescription_items pi ON p.id = pi.prescription_id
           WHERE p.consultation_id = ?
           GROUP BY p.id""",
        (consultation_id,),
    )
    prescriptions = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT type, description FROM medical_history WHERE consultation_id = ?",
        (consultation_id,),
    )
    antecedents = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT tooth_number, treatment_type, description FROM dental_treatments WHERE consultation_id = ?",
        (consultation_id,),
    )
    dental = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT mutuelle, type_feuille, total_montant FROM feuilles_soin WHERE consultation_id = ?",
        (consultation_id,),
    )
    feuilles = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT title, category FROM documents WHERE consultation_id = ?",
        (consultation_id,),
    )
    documents = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT DISTINCT tooth_number, canal_name FROM endo_history WHERE consultation_id = ?",
        (consultation_id,),
    )
    endo = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT tooth_number, condition FROM dental_condition_history WHERE consultation_id = ?",
        (consultation_id,),
    )
    conditions = [dict(r) for r in await cursor.fetchall()]

    return JSONResponse(content={
        "prescriptions": prescriptions,
        "antecedents": antecedents,
        "dental": dental,
        "feuilles": feuilles,
        "documents": documents,
        "endo": endo,
        "conditions": conditions,
    })


@router.post("/{consultation_id}/terminate")
async def terminate_consultation(
    request: Request,
    consultation_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    is_ajax = request.query_params.get("ajax") == "1"

    user = get_current_user(request)
    if not user:
        if is_ajax:
            return JSONResponse(status_code=401, content={"ok": False, "error": "Non authentifié"})
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    try:
        patient_id = int(form.get("patient_id", 0))
    except (ValueError, TypeError):
        if is_ajax:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Patient invalide"})
        return RedirectResponse(url="/patients", status_code=302)

    reason = form.get("reason", "") or None
    clinical_exam = form.get("clinical_exam", "") or None
    diagnosis = form.get("diagnosis", "") or None
    treatment_plan = form.get("treatment_plan", "") or None
    notes = form.get("notes", "") or None
    dental_exam_json = _build_dental_exam_json(form)

    cursor = await db.execute(
        "SELECT * FROM consultations WHERE id = ? AND doctor_id = ? AND status = 'en_cours'",
        (consultation_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        if is_ajax:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Consultation introuvable ou déjà terminée"})
        return RedirectResponse(url=f"/patients/{patient_id}", status_code=302)
    consultation = dict(row)

    summary = await _build_summary(
        db, consultation_id, reason, diagnosis, treatment_plan, clinical_exam, dental_exam_json
    )

    await db.execute(
        """UPDATE consultations
           SET status = 'terminee', reason = ?, clinical_exam = ?, diagnosis = ?,
               treatment_plan = ?, notes = ?, summary = ?, dental_exam_json = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (reason, clinical_exam, diagnosis, treatment_plan, notes, summary, dental_exam_json, consultation_id),
    )

    if consultation.get("appointment_id"):
        await db.execute(
            "UPDATE appointments SET status = 'termine', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (consultation["appointment_id"],),
        )

    await db.commit()

    if is_ajax:
        return JSONResponse(content={
            "ok": True,
            "consultation_id": consultation_id,
            "patient_id": patient_id,
            "doctor_id": user["sub"],
        })
    return RedirectResponse(url=f"/patients/{patient_id}?tab=appts", status_code=302)
