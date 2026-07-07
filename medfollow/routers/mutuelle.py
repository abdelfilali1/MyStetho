import io
import json
import os
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user
from routers.deps import deny_secretaire

router = APIRouter(prefix="/mutuelle", dependencies=[Depends(deny_secretaire)])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def mutuelle_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT code, categorie, libelle, lettre, cotation, cotation_bis, valeure_lettre, remarques FROM ngap_acts ORDER BY categorie, code"
    )
    rows = await cursor.fetchall()
    acts = [
        {
            "code": r["code"],
            "categorie": r["categorie"],
            "libelle": r["libelle"],
            "lettre": r["lettre"],
            "cotation": r["cotation"],
            "cotation_bis": r["cotation_bis"],
            "valeure_lettre": r["valeure_lettre"],
            "remarques": r["remarques"],
            "montant": round(r["cotation"] * r["valeure_lettre"], 2),
        }
        for r in rows
    ]

    categories = sorted(set(a["categorie"] for a in acts))

    pcursor = await db.execute(
        "SELECT id, first_name, last_name, date_of_birth, gender, social_security_number "
        "FROM patients WHERE is_active = 1 AND doctor_id = ? ORDER BY last_name, first_name",
        (user["sub"],)
    )
    patients = [
        {
            "id": p["id"],
            "nom": f"{p['last_name']} {p['first_name']}",
            "dob": p["date_of_birth"] or "",
            "gender": p["gender"] or "",
            "cin": p["social_security_number"] or "",
        }
        for p in await pcursor.fetchall()
    ]

    return templates.TemplateResponse(
        "mutuelle/index.html",
        {
            "request": request,
            "user": user,
            "active": "mutuelle",
            "acts_json": json.dumps(acts, ensure_ascii=False),
            "categories": categories,
            "total_acts": len(acts),
            "patients_json": json.dumps(patients, ensure_ascii=False),
        },
    )


FEUILLES_DIR = os.path.join("data", "feuilles")


def _feuille_html_path(feuille_id: int) -> str:
    return os.path.join(FEUILLES_DIR, f"{feuille_id}.html")


@router.get("/feuille/{feuille_id}/view", response_class=HTMLResponse)
async def view_feuille(request: Request, feuille_id: int, db: aiosqlite.Connection = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT html_path FROM feuilles_soin WHERE id = ? AND doctor_id = ?",
        (feuille_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return HTMLResponse("<h2>Feuille introuvable</h2>", status_code=404)

    html_path = row["html_path"]
    if html_path and os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h2>Fichier non disponible</h2>", status_code=404)


@router.get("/feuille/{feuille_id}/download")
async def download_feuille(request: Request, feuille_id: int, db: aiosqlite.Connection = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT html_path, mutuelle, date_soin, nom_beneficiaire FROM feuilles_soin WHERE id = ? AND doctor_id = ?",
        (feuille_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row or not row["html_path"] or not os.path.exists(row["html_path"]):
        return HTMLResponse("<h2>Fichier non disponible</h2>", status_code=404)

    nom = f"feuille_{row['mutuelle']}_{row['date_soin'] or 'soin'}_{feuille_id}.html"
    return FileResponse(row["html_path"], filename=nom, media_type="text/html")


@router.post("/feuille/save")
async def save_feuille(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    data = await request.json()
    patient_id = data.get("patient_id")
    if not patient_id:
        return JSONResponse({"error": "patient_id requis"}, status_code=400)

    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cur.fetchone():
        return JSONResponse({"error": "not found"}, status_code=404)

    consultation_id = data.get("consultation_id") or None

    cursor = await db.execute(
        """INSERT INTO feuilles_soin
           (patient_id, doctor_id, mutuelle, type_feuille, nom_beneficiaire, ddn, cin, sexe,
            lien_assure, inpe, type_soin, numero_entente, ville, date_soin, total_montant, actes_json, consultation_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            patient_id, user["sub"],
            data.get("mutuelle"), data.get("type_feuille"),
            data.get("nom_beneficiaire"), data.get("ddn"),
            data.get("cin"), data.get("sexe"),
            data.get("lien_assure"), data.get("inpe"),
            data.get("type_soin"), data.get("numero_entente"),
            data.get("ville"), data.get("date_soin"),
            data.get("total_montant", 0),
            json.dumps(data.get("actes", []), ensure_ascii=False),
            consultation_id,
        ),
    )
    await db.commit()
    feuille_id = cursor.lastrowid

    # Sauvegarder le HTML généré côté client
    html_content = data.get("html_content", "")
    if html_content:
        os.makedirs(FEUILLES_DIR, exist_ok=True)
        html_path = _feuille_html_path(feuille_id)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        await db.execute("UPDATE feuilles_soin SET html_path = ? WHERE id = ?", (html_path, feuille_id))
        await db.commit()

    return JSONResponse({"ok": True, "id": feuille_id})


async def _next_numero_note(db: aiosqlite.Connection, doctor_id: str) -> str:
    """Generate the next sequential note number for the current year and doctor.

    Format: YYYY-NNN (e.g. 2026-001). Sequence resets each calendar year per doctor.
    """
    year = datetime.now().year
    prefix = f"{year}-"
    cur = await db.execute(
        """SELECT MAX(CAST(SUBSTR(numero_note, 6) AS INTEGER)) AS max_n
           FROM feuilles_soin
           WHERE doctor_id = ? AND type_feuille = 'honoraires'
             AND numero_note LIKE ?""",
        (doctor_id, prefix + "%"),
    )
    row = await cur.fetchone()
    max_n = row[0] if row and row[0] is not None else 0
    return f"{year}-{(max_n + 1):03d}"


@router.post("/note/save")
async def save_note(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    data = await request.json()
    patient_id = data.get("patient_id")
    if not patient_id:
        return JSONResponse({"error": "patient_id requis"}, status_code=400)

    cur = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cur.fetchone():
        return JSONResponse({"error": "not found"}, status_code=404)

    numero_note = await _next_numero_note(db, user["sub"])

    # Identifiants fiscaux du praticien + cases « Afficher sur la note »
    # (cochées par défaut). Persistés avec la note pour que le PDF (regénéré
    # côté serveur) puisse les inclure.
    def _flag(key):
        return 1 if data.get(key, True) else 0

    cursor = await db.execute(
        """INSERT INTO feuilles_soin
           (patient_id, doctor_id, mutuelle, type_feuille, nom_beneficiaire, date_soin, total_montant, actes_json, numero_note,
            inpe, ice, if_number, cnss, show_inpe, show_ice, show_if)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            patient_id, user["sub"],
            "Note", "honoraires",
            data.get("nom_patient"),
            data.get("date_soin"),
            data.get("total_montant", 0),
            json.dumps(data.get("actes", []), ensure_ascii=False),
            numero_note,
            (data.get("inpe") or "").strip() or None,
            (data.get("ice") or "").strip() or None,
            (data.get("if_number") or "").strip() or None,
            (data.get("cnss") or "").strip() or None,
            _flag("show_inpe"), _flag("show_ice"), _flag("show_if"),
        ),
    )
    await db.commit()
    note_id = cursor.lastrowid

    html_content = data.get("html_content", "")
    if html_content:
        os.makedirs(FEUILLES_DIR, exist_ok=True)
        html_path = _feuille_html_path(note_id)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        await db.execute("UPDATE feuilles_soin SET html_path = ? WHERE id = ?", (html_path, note_id))
        await db.commit()

    return JSONResponse({"ok": True, "id": note_id, "numero_note": numero_note})


@router.get("/note/{note_id}/pdf")
async def note_pdf(request: Request, note_id: int, dl: int = 0, db: aiosqlite.Connection = Depends(get_db)):
    """Génère la note d'honoraires en PDF, posée sur le papier à en-tête du praticien."""
    from fastapi.responses import RedirectResponse
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT * FROM feuilles_soin WHERE id = ? AND doctor_id = ? AND type_feuille = 'honoraires'",
        (note_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return HTMLResponse("<h2>Note introuvable</h2>", status_code=404)
    note = dict(row)

    try:
        actes = json.loads(note.get("actes_json") or "[]")
    except Exception:
        actes = []
    if not isinstance(actes, list):
        actes = []

    cursor = await db.execute(
        "SELECT first_name, last_name, specialty, phone, address, pdf_template_path FROM users WHERE id = ?",
        (user["sub"],),
    )
    d = await cursor.fetchone()
    doctor_name = f"Dr. {d['first_name']} {d['last_name']}" if d else ""
    specialty = (d["specialty"] if d else "") or ""
    doc_phone = (d["phone"] if d else None)
    doc_address = (d["address"] if d else None)
    template_path = d["pdf_template_path"] if d else None

    # Identifiants fiscaux : n'inclure que ceux marqués « Afficher sur la note »
    # (défaut coché). CNSS praticien affiché s'il est renseigné.
    def _shown(val_key, flag_key):
        v = (note.get(val_key) or "").strip()
        return v if (v and note.get(flag_key, 1)) else None

    from services.pdf_service import generate_note_honoraires_pdf
    pdf_bytes = generate_note_honoraires_pdf(
        note, actes, doctor_name, specialty, template_path,
        address=doc_address, phone=doc_phone,
        inpe=_shown("inpe", "show_inpe"),
        ice=_shown("ice", "show_ice"),
        if_number=_shown("if_number", "show_if"),
        cnss=(note.get("cnss") or "").strip() or None,
    )
    fname = f"note_honoraires_{note.get('numero_note') or note_id}.pdf"
    disp = "attachment" if dl else "inline"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{fname}"'},
    )


@router.get("/note/next-number")
async def next_note_number(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    """Preview the next N° Note that will be assigned (for display in the form)."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"numero_note": await _next_numero_note(db, user["sub"])})


@router.get("/api/acts")
async def acts_api(
    request: Request,
    q: str = "",
    categorie: str = "",
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    query = "SELECT * FROM ngap_acts WHERE 1=1"
    params = []

    if q:
        query += " AND (LOWER(libelle) LIKE ? OR LOWER(code) LIKE ?)"
        like = f"%{q.lower()}%"
        params.extend([like, like])

    if categorie:
        query += " AND categorie = ?"
        params.append(categorie)

    query += " ORDER BY categorie, code"
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [
        {
            "code": r["code"],
            "categorie": r["categorie"],
            "libelle": r["libelle"],
            "lettre": r["lettre"],
            "cotation": r["cotation"],
            "valeure_lettre": r["valeure_lettre"],
            "montant": round(r["cotation"] * r["valeure_lettre"], 2),
            "remarques": r["remarques"],
        }
        for r in rows
    ]
