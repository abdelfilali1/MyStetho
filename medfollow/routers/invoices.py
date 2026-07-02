import io
import json
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import date, timedelta
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.deps import require_login, set_flash, deny_secretaire
from services.audit import log_audit, client_ip

router = APIRouter(prefix="/invoices", dependencies=[Depends(deny_secretaire)])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _generate_invoice_number(year: int, count: int) -> str:
    return f"F{year}-{count + 1:04d}"


async def _next_devis_number(db, doctor_id: int, year: int) -> str:
    """Numérotation par praticien et par année : DEV{YYYY}-{NNN}."""
    cur = await db.execute(
        "SELECT MAX(CAST(SUBSTR(devis_number, 9) AS INTEGER)) FROM devis WHERE doctor_id = ? AND devis_number LIKE ?",
        (doctor_id, f"DEV{year}-%"),
    )
    row = await cur.fetchone()
    n = (row[0] or 0) + 1
    return f"DEV{year}-{n:03d}"


async def _doctor_pdf_ctx(db, doctor_id: int):
    cur = await db.execute("SELECT first_name, last_name, specialty, pdf_template_path FROM users WHERE id = ?", (doctor_id,))
    r = await cur.fetchone()
    if not r:
        return "", "", None
    return f"Dr {r[0]} {r[1]}".strip(), (r[2] or ""), r[3]


# ─────────────────────────────────────────────────────────────
# Factures
# ─────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def facturation_home(request: Request, user: dict = Depends(require_login)):
    # Le module Facturation s'ouvre directement sur les devis / plans de traitement.
    return RedirectResponse(url="/invoices/devis", status_code=302)


@router.get("/factures", response_class=HTMLResponse)
async def list_invoices(
    request: Request,
    status: Optional[str] = None,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = user["sub"]
    per_page = 20
    offset = (page - 1) * per_page

    base_where = "WHERE i.doctor_id = ?"
    params: list = [uid]
    if status:
        base_where += " AND i.status = ?"
        params.append(status)
    if date_from:
        base_where += " AND i.invoice_date >= ?"
        params.append(date_from)
    if date_to:
        base_where += " AND i.invoice_date <= ?"
        params.append(date_to)

    count_cursor = await db.execute(f"SELECT COUNT(*) FROM invoices i {base_where}", params)
    total_count = (await count_cursor.fetchone())[0]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    query = f"""SELECT i.*, p.first_name || ' ' || p.last_name AS patient_name,
                       u.first_name || ' ' || u.last_name AS doctor_name
                FROM invoices i
                JOIN patients p ON i.patient_id = p.id
                JOIN users u ON i.doctor_id = u.id
                {base_where} ORDER BY i.invoice_date DESC LIMIT ? OFFSET ?"""
    cursor = await db.execute(query, params + [per_page, offset])
    invoices = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE doctor_id = ? AND status != 'annulee'", (uid,))
    total_ca = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COALESCE(SUM(paid_amount), 0) FROM invoices WHERE doctor_id = ? AND status != 'annulee'", (uid,))
    total_paid = (await cursor.fetchone())[0]

    today = date.today()
    cursor = await db.execute(
        "SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE doctor_id = ? AND status != 'annulee' AND strftime('%Y', invoice_date) = ?",
        (uid, str(today.year)),
    )
    ca_annual = (await cursor.fetchone())[0]
    cursor = await db.execute(
        "SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE doctor_id = ? AND status != 'annulee' AND strftime('%Y-%m', invoice_date) = ?",
        (uid, today.strftime("%Y-%m")),
    )
    ca_monthly = (await cursor.fetchone())[0]

    return templates.TemplateResponse(
        "invoices/list.html",
        {
            "request": request, "user": user, "active": "invoices",
            "invoices": invoices, "selected_status": status,
            "total_ca": total_ca, "total_paid": total_paid, "total_unpaid": total_ca - total_paid,
            "ca_annual": ca_annual, "ca_monthly": ca_monthly,
            "date_from": date_from, "date_to": date_to,
            "page": page, "total_pages": total_pages, "total_count": total_count,
        },
    )


@router.get("/export.csv")
async def export_invoices_csv(
    request: Request,
    status: Optional[str] = None,
    date_from: str = "",
    date_to: str = "",
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = user["sub"]
    base_where = "WHERE i.doctor_id = ?"
    params: list = [uid]
    if status:
        base_where += " AND i.status = ?"
        params.append(status)
    if date_from:
        base_where += " AND i.invoice_date >= ?"
        params.append(date_from)
    if date_to:
        base_where += " AND i.invoice_date <= ?"
        params.append(date_to)

    query = f"""SELECT i.invoice_number, p.first_name || ' ' || p.last_name AS patient_name,
                       i.invoice_date, i.total_amount, i.paid_amount, i.status
                FROM invoices i JOIN patients p ON i.patient_id = p.id
                {base_where} ORDER BY i.invoice_date DESC"""
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Numéro", "Patient", "Date", "Montant", "Payé", "Statut"])
    status_labels = {
        "brouillon": "Brouillon", "emise": "Émise", "payee": "Payée",
        "partiellement_payee": "Partiellement payée", "annulee": "Annulée",
    }
    for row in rows:
        writer.writerow([row[0], row[1], row[2], row[3], row[4], status_labels.get(row[5], row[5])])

    await log_audit(db, user, "factures_export_csv", ip=client_ip(request))
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=factures.csv"},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_invoice_form(
    request: Request,
    patient_id: Optional[int] = None,
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    uid = user["sub"]
    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name", (uid,))
    patients = [dict(r) for r in await cursor.fetchall()]
    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]
    cursor = await db.execute("SELECT * FROM medical_acts ORDER BY code")
    acts = [dict(r) for r in await cursor.fetchall()]
    return templates.TemplateResponse(
        "invoices/form.html",
        {"request": request, "user": user, "active": "invoices", "patients": patients, "doctors": doctors, "acts": acts, "selected_patient_id": patient_id},
    )


@router.post("/new")
async def create_invoice(request: Request, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    form = await request.form()
    patient_id = int(form["patient_id"])
    notes = form.get("notes", "")
    tiers_payant = form.get("tiers_payant") == "on"

    cursor = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cursor.fetchone():
        return RedirectResponse(url="/invoices/factures", status_code=302)
    doctor_id = user["sub"]
    today = date.today()

    total = 0.0
    items = []
    idx = 0
    while f"item_desc_{idx}" in form:
        desc = form[f"item_desc_{idx}"]
        if desc.strip():
            qty = int(form.get(f"item_qty_{idx}", "1") or "1")
            price = float(form.get(f"item_price_{idx}", "0") or "0")
            act_id = form.get(f"item_act_id_{idx}")
            item_total = qty * price
            total += item_total
            items.append((desc, qty, price, item_total, int(act_id) if act_id else None))
        idx += 1

    from aiosqlite import IntegrityError
    invoice_id = None
    for attempt in range(3):
        cursor = await db.execute("SELECT COUNT(*) FROM invoices WHERE strftime('%Y', invoice_date) = ?", (str(today.year),))
        count = (await cursor.fetchone())[0] + attempt
        invoice_number = _generate_invoice_number(today.year, count)
        try:
            cursor = await db.execute(
                "INSERT INTO invoices (invoice_number, patient_id, doctor_id, total_amount, tiers_payant, notes) VALUES (?, ?, ?, ?, ?, ?)",
                (invoice_number, patient_id, doctor_id, total, tiers_payant, notes or None),
            )
            invoice_id = cursor.lastrowid
            break
        except IntegrityError:
            continue
    if invoice_id is None:
        return HTMLResponse("Erreur: impossible de générer un numéro de facture unique.", status_code=500)

    for desc, qty, price, item_total, act_id in items:
        await db.execute(
            "INSERT INTO invoice_items (invoice_id, medical_act_id, description, quantity, unit_price, total_price) VALUES (?, ?, ?, ?, ?, ?)",
            (invoice_id, act_id, desc, qty, price, item_total),
        )
    await db.commit()
    await log_audit(db, user, "facture_creee", entity_type="invoice", entity_id=invoice_id, patient_id=patient_id, ip=client_ip(request))
    resp = RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)
    set_flash(resp, "Facture créée")
    return resp


# ─────────────────────────────────────────────────────────────
# Devis / plans de traitement (item 21) — routes AVANT /{invoice_id}
# ─────────────────────────────────────────────────────────────
_DEVIS_STATUS_LABELS = {"propose": "Proposé", "accepte": "Accepté", "refuse": "Refusé", "converti": "Converti"}
# Transitions autorisées
_DEVIS_TRANSITIONS = {
    "propose": {"accepte", "refuse"},
    "accepte": {"refuse", "propose"},
    "refuse": {"propose"},
    "converti": set(),
}


@router.get("/devis", response_class=HTMLResponse)
async def list_devis(request: Request, status: Optional[str] = None, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    uid = user["sub"]
    where = "WHERE d.doctor_id = ?"
    params: list = [uid]
    if status:
        where += " AND d.status = ?"
        params.append(status)
    cursor = await db.execute(
        f"""SELECT d.*, p.first_name || ' ' || p.last_name AS patient_name
            FROM devis d JOIN patients p ON d.patient_id = p.id
            {where} ORDER BY d.created_at DESC""",
        params,
    )
    devis = [dict(r) for r in await cursor.fetchall()]
    return templates.TemplateResponse(
        "invoices/devis_list.html",
        {"request": request, "user": user, "active": "invoices", "devis": devis, "selected_status": status, "status_labels": _DEVIS_STATUS_LABELS},
    )


async def _ngap_acts(db) -> list:
    """Catalogue NGAP (identique à la mutuelle) : code, libellé, montant calculé."""
    cur = await db.execute(
        "SELECT code, categorie, libelle, lettre, cotation, cotation_bis, valeure_lettre, remarques "
        "FROM ngap_acts ORDER BY categorie, code"
    )
    return [
        {
            "code": r["code"], "categorie": r["categorie"], "libelle": r["libelle"],
            "lettre": r["lettre"], "cotation": r["cotation"], "valeure_lettre": r["valeure_lettre"],
            "montant": round((r["cotation"] or 0) * (r["valeure_lettre"] or 0), 2),
        }
        for r in await cur.fetchall()
    ]


@router.get("/devis/new", response_class=HTMLResponse)
async def new_devis_form(request: Request, patient_id: Optional[int] = None, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    uid = user["sub"]
    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE doctor_id = ? AND is_active = 1 ORDER BY last_name", (uid,))
    patients = [dict(r) for r in await cursor.fetchall()]
    acts = await _ngap_acts(db)
    categories = sorted(set(a["categorie"] for a in acts if a["categorie"]))
    default_valid = (date.today() + timedelta(days=30)).isoformat()
    return templates.TemplateResponse(
        "invoices/devis_form.html",
        {
            "request": request, "user": user, "active": "invoices", "patients": patients,
            "acts_json": json.dumps(acts, ensure_ascii=False), "categories": categories,
            "total_acts": len(acts), "selected_patient_id": patient_id, "default_valid": default_valid,
        },
    )


@router.post("/devis/acts/new")
async def add_custom_act(request: Request, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    """Ajoute un acte personnalisé au catalogue NGAP pour réutilisation ultérieure."""
    data = await request.json()
    code = (data.get("code") or "").strip().upper()
    libelle = (data.get("libelle") or "").strip()
    try:
        montant = round(float(data.get("montant") or 0), 2)
    except (TypeError, ValueError):
        montant = 0.0
    lettre = (data.get("lettre") or "D").strip()[:3] or "D"
    if not code or not libelle:
        return JSONResponse(status_code=400, content={"error": "Code et libellé obligatoires"})

    cur = await db.execute("SELECT 1 FROM ngap_acts WHERE code = ?", (code,))
    if await cur.fetchone():
        return JSONResponse(status_code=409, content={"error": "Ce code existe déjà"})

    # Stocké comme un acte NGAP : montant = cotation × 1 (valeure_lettre=1)
    await db.execute(
        "INSERT INTO ngap_acts (code, categorie, libelle, lettre, cotation, cotation_bis, valeure_lettre, remarques) "
        "VALUES (?, 'Actes personnalisés', ?, ?, ?, 0, 1, 'Ajouté par le praticien')",
        (code, libelle, lettre, montant),
    )
    await db.commit()
    await log_audit(db, user, "acte_personnalise_ajoute", entity_type="ngap_act", ip=client_ip(request), details=f"{code} — {libelle}")
    return JSONResponse(content={
        "code": code, "categorie": "Actes personnalisés", "libelle": libelle,
        "lettre": lettre, "cotation": montant, "valeure_lettre": 1, "montant": montant,
    })


@router.post("/devis/new")
async def create_devis(request: Request, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    form = await request.form()
    patient_id = int(form["patient_id"])
    notes = form.get("notes", "")
    valid_until = form.get("valid_until", "") or None

    cursor = await db.execute("SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, user["sub"]))
    if not await cursor.fetchone():
        return RedirectResponse(url="/invoices/devis", status_code=302)
    doctor_id = user["sub"]
    today = date.today()

    total = 0.0
    items = []
    idx = 0
    while f"item_desc_{idx}" in form:
        desc = form[f"item_desc_{idx}"]
        if desc.strip():
            qty = int(form.get(f"item_qty_{idx}", "1") or "1")
            price = float(form.get(f"item_price_{idx}", "0") or "0")
            code = (form.get(f"item_code_{idx}", "") or "").strip() or None
            teeth = form.get(f"item_teeth_{idx}", "") or None
            item_total = qty * price
            total += item_total
            items.append((desc, qty, price, item_total, code, teeth))
        idx += 1

    from aiosqlite import IntegrityError
    devis_id = None
    for attempt in range(4):
        number = await _next_devis_number(db, doctor_id, today.year)
        if attempt:
            base, n = number.rsplit("-", 1)
            number = f"{base}-{int(n) + attempt:03d}"
        try:
            cursor = await db.execute(
                "INSERT INTO devis (devis_number, patient_id, doctor_id, total_amount, status, notes, valid_until) VALUES (?, ?, ?, ?, 'propose', ?, ?)",
                (number, patient_id, doctor_id, total, notes or None, valid_until),
            )
            devis_id = cursor.lastrowid
            break
        except IntegrityError:
            continue
    if devis_id is None:
        return HTMLResponse("Erreur: impossible de générer un numéro de devis unique.", status_code=500)

    for desc, qty, price, item_total, code, teeth in items:
        await db.execute(
            "INSERT INTO devis_items (devis_id, medical_act_id, description, quantity, unit_price, total_price, tooth_numbers, code) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (devis_id, None, desc, qty, price, item_total, teeth, code),
        )
    await db.commit()
    await log_audit(db, user, "devis_cree", entity_type="devis", entity_id=devis_id, patient_id=patient_id, ip=client_ip(request))
    resp = RedirectResponse(url=f"/invoices/devis/{devis_id}", status_code=302)
    set_flash(resp, "Devis créé")
    return resp


async def _load_devis(db, devis_id, doctor_id):
    cursor = await db.execute(
        """SELECT d.*, p.first_name || ' ' || p.last_name AS patient_name
           FROM devis d JOIN patients p ON d.patient_id = p.id
           WHERE d.id = ? AND d.doctor_id = ?""",
        (devis_id, doctor_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


@router.get("/devis/{devis_id}", response_class=HTMLResponse)
async def view_devis(request: Request, devis_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    devis = await _load_devis(db, devis_id, user["sub"])
    if not devis:
        return RedirectResponse(url="/invoices/devis", status_code=302)
    cursor = await db.execute("SELECT * FROM devis_items WHERE devis_id = ?", (devis_id,))
    items = [dict(r) for r in await cursor.fetchall()]
    await log_audit(db, user, "devis_consulte", entity_type="devis", entity_id=devis_id, patient_id=devis["patient_id"], ip=client_ip(request))
    return templates.TemplateResponse(
        "invoices/devis_detail.html",
        {"request": request, "user": user, "active": "invoices", "devis": devis, "items": items, "status_labels": _DEVIS_STATUS_LABELS},
    )


@router.post("/devis/{devis_id}/status")
async def devis_status(request: Request, devis_id: int, status: str = Form(...), user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    devis = await _load_devis(db, devis_id, user["sub"])
    if not devis:
        return RedirectResponse(url="/invoices/devis", status_code=302)
    allowed = _DEVIS_TRANSITIONS.get(devis["status"], set())
    if status not in allowed:
        resp = RedirectResponse(url=f"/invoices/devis/{devis_id}", status_code=302)
        set_flash(resp, "Transition de statut non autorisée", "error")
        return resp
    await db.execute("UPDATE devis SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, devis_id))
    await db.commit()
    await log_audit(db, user, "devis_statut", entity_type="devis", entity_id=devis_id, patient_id=devis["patient_id"], ip=client_ip(request), details=f"status={status}")
    resp = RedirectResponse(url=f"/invoices/devis/{devis_id}", status_code=302)
    set_flash(resp, f"Devis marqué « {_DEVIS_STATUS_LABELS.get(status, status)} »")
    return resp


@router.post("/devis/{devis_id}/convert")
async def convert_devis(request: Request, devis_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    devis = await _load_devis(db, devis_id, user["sub"])
    if not devis:
        return RedirectResponse(url="/invoices/devis", status_code=302)
    if devis["status"] != "accepte":
        resp = RedirectResponse(url=f"/invoices/devis/{devis_id}", status_code=302)
        set_flash(resp, "Seul un devis accepté peut être converti en facture", "error")
        return resp

    cursor = await db.execute("SELECT * FROM devis_items WHERE devis_id = ?", (devis_id,))
    ditems = [dict(r) for r in await cursor.fetchall()]
    doctor_id = user["sub"]
    today = date.today()

    from aiosqlite import IntegrityError
    invoice_id = None
    for attempt in range(3):
        cursor = await db.execute("SELECT COUNT(*) FROM invoices WHERE strftime('%Y', invoice_date) = ?", (str(today.year),))
        count = (await cursor.fetchone())[0] + attempt
        number = _generate_invoice_number(today.year, count)
        try:
            cursor = await db.execute(
                "INSERT INTO invoices (invoice_number, patient_id, doctor_id, total_amount, status, notes) VALUES (?, ?, ?, ?, 'emise', ?)",
                (number, devis["patient_id"], doctor_id, devis["total_amount"], f"Établie depuis le devis {devis['devis_number']}"),
            )
            invoice_id = cursor.lastrowid
            break
        except IntegrityError:
            continue
    if invoice_id is None:
        return HTMLResponse("Erreur: impossible de générer un numéro de facture unique.", status_code=500)

    for it in ditems:
        desc = it["description"]
        if it.get("code"):
            desc = f"{it['code']} — {desc}"
        if it.get("tooth_numbers"):
            desc += f" (dents {it['tooth_numbers']})"
        await db.execute(
            "INSERT INTO invoice_items (invoice_id, medical_act_id, description, quantity, unit_price, total_price) VALUES (?, ?, ?, ?, ?, ?)",
            (invoice_id, it.get("medical_act_id"), desc, it["quantity"], it["unit_price"], it["total_price"]),
        )
    await db.execute("UPDATE devis SET status = 'converti', converted_invoice_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (invoice_id, devis_id))
    await db.commit()
    await log_audit(db, user, "devis_converti", entity_type="devis", entity_id=devis_id, patient_id=devis["patient_id"], ip=client_ip(request), details=f"facture={invoice_id}")
    await log_audit(db, user, "facture_creee", entity_type="invoice", entity_id=invoice_id, patient_id=devis["patient_id"], ip=client_ip(request))
    resp = RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)
    set_flash(resp, "Devis converti en facture")
    return resp


@router.get("/devis/{devis_id}/pdf")
async def devis_pdf(request: Request, devis_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    devis = await _load_devis(db, devis_id, user["sub"])
    if not devis:
        return RedirectResponse(url="/invoices/devis", status_code=302)
    cursor = await db.execute("SELECT * FROM devis_items WHERE devis_id = ?", (devis_id,))
    items = [dict(r) for r in await cursor.fetchall()]
    doctor_name, specialty, template_path = await _doctor_pdf_ctx(db, user["sub"])
    from services.pdf_service import generate_devis_pdf
    await log_audit(db, user, "devis_pdf_exporte", entity_type="devis", entity_id=devis_id, patient_id=devis["patient_id"], ip=client_ip(request))
    pdf_bytes = generate_devis_pdf(devis, items, doctor_name, specialty, template_path)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="devis_{devis["devis_number"]}.pdf"'})


# ─────────────────────────────────────────────────────────────
# Facture : PDF (suffixe → sûr) + détail + actions
# ─────────────────────────────────────────────────────────────
@router.get("/{invoice_id}/pdf")
async def invoice_pdf(request: Request, invoice_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        """SELECT i.*, p.first_name || ' ' || p.last_name AS patient_name
           FROM invoices i JOIN patients p ON i.patient_id = p.id
           WHERE i.id = ? AND i.doctor_id = ?""",
        (invoice_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/invoices/factures", status_code=302)
    invoice = dict(row)
    cursor = await db.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
    items = [dict(r) for r in await cursor.fetchall()]
    cursor = await db.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date", (invoice_id,))
    payments = [dict(r) for r in await cursor.fetchall()]
    doctor_name, specialty, template_path = await _doctor_pdf_ctx(db, user["sub"])
    from services.pdf_service import generate_invoice_pdf
    await log_audit(db, user, "facture_pdf_exportee", entity_type="invoice", entity_id=invoice_id, patient_id=invoice["patient_id"], ip=client_ip(request))
    pdf_bytes = generate_invoice_pdf(invoice, items, payments, doctor_name, specialty, template_path)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="facture_{invoice["invoice_number"]}.pdf"'})


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def view_invoice(request: Request, invoice_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        """SELECT i.*, p.first_name || ' ' || p.last_name AS patient_name, p.address, p.city, p.postal_code, p.social_security_number, u.first_name || ' ' || u.last_name AS doctor_name, u.specialty FROM invoices i JOIN patients p ON i.patient_id = p.id JOIN users u ON i.doctor_id = u.id WHERE i.id = ? AND i.doctor_id = ? """,
        (invoice_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/invoices/factures", status_code=302)
    invoice = dict(row)
    cursor = await db.execute("SELECT * FROM invoice_items WHERE invoice_id = ? ", (invoice_id,))
    items = [dict(r) for r in await cursor.fetchall()]
    cursor = await db.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date", (invoice_id,))
    payments = [dict(r) for r in await cursor.fetchall()]
    await log_audit(db, user, "facture_consultee", entity_type="invoice", entity_id=invoice_id, patient_id=invoice["patient_id"], ip=client_ip(request))
    return templates.TemplateResponse(
        "invoices/detail.html",
        {"request": request, "user": user, "active": "invoices", "invoice": invoice, "items": items, "payments": payments},
    )


@router.post("/{invoice_id}/cancel")
async def cancel_invoice(request: Request, invoice_id: int, user: dict = Depends(require_login), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id, patient_id FROM invoices WHERE id = ? AND doctor_id = ?", (invoice_id, user["sub"]))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/invoices/factures", status_code=302)
    await db.execute("UPDATE invoices SET status = 'annulee', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (invoice_id,))
    await db.commit()
    await log_audit(db, user, "facture_annulee", entity_type="invoice", entity_id=invoice_id, patient_id=row[1], ip=client_ip(request))
    resp = RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)
    set_flash(resp, "Facture annulée")
    return resp


@router.post("/{invoice_id}/pay")
async def add_payment(
    request: Request,
    invoice_id: int,
    amount: float = Form(...),
    payment_method: str = Form(...),
    reference: str = Form(""),
    user: dict = Depends(require_login),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT total_amount, patient_id FROM invoices WHERE id = ? AND doctor_id = ?", (invoice_id, user["sub"]))
    inv = await cursor.fetchone()
    if not inv:
        return RedirectResponse(url="/invoices/factures", status_code=302)
    total_amount = inv[0]

    await db.execute(
        "INSERT INTO payments (invoice_id, amount, payment_method, reference) VALUES (?, ?, ?, ?)",
        (invoice_id, amount, payment_method, reference or None),
    )
    cursor = await db.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE invoice_id = ? ", (invoice_id,))
    total_paid = (await cursor.fetchone())[0]

    if total_paid >= total_amount:
        status = "payee"
    elif total_paid > 0:
        status = "partiellement_payee"
    else:
        status = "emise"

    await db.execute(
        "UPDATE invoices SET paid_amount = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND doctor_id = ? ",
        (total_paid, status, invoice_id, user["sub"]),
    )
    await db.commit()
    await log_audit(db, user, "paiement_enregistre", entity_type="invoice", entity_id=invoice_id, patient_id=inv[1], ip=client_ip(request), details=f"montant={amount}")
    resp = RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)
    set_flash(resp, "Paiement enregistré")
    return resp
