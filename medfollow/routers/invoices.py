from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import date
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/invoices")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _generate_invoice_number(year: int, count: int) -> str:
    return f"F{year}-{count + 1:04d}"


@router.get("/", response_class=HTMLResponse)
async def list_invoices(
    request: Request,
    status: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = """SELECT i.*, p.first_name || ' ' || p.last_name AS patient_name, u.first_name || ' ' || u.last_name AS doctor_name FROM invoices i JOIN patients p ON i.patient_id = p.id JOIN users u ON i.doctor_id = u.id"""
    params = []
    if status:
        query += " WHERE i.status = ? "
        params.append(status)
    query += " ORDER BY i.invoice_date DESC LIMIT 50"

    cursor = await db.execute(query, params)
    invoices = [dict(r) for r in await cursor.fetchall()]

    # Summary stats
    cursor = await db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE status != 'annulee'")
    total_ca = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COALESCE(SUM(paid_amount), 0) FROM invoices WHERE status != 'annulee'")
    total_paid = (await cursor.fetchone())[0]

    return templates.TemplateResponse(
        "invoices/list.html",
        {
            "request": request, "user": user, "active": "invoices",
            "invoices": invoices, "selected_status": status,
            "total_ca": total_ca, "total_paid": total_paid, "total_unpaid": total_ca - total_paid,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_invoice_form(
    request: Request,
    patient_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name")
    patients = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM users WHERE role IN ('medecin', 'admin') ORDER BY last_name")
    doctors = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT * FROM medical_acts ORDER BY code")
    acts = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "invoices/form.html",
        {
            "request": request, "user": user, "active": "invoices",
            "patients": patients, "doctors": doctors, "acts": acts,
            "selected_patient_id": patient_id,
        },
    )


@router.post("/new")
async def create_invoice(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    patient_id = int(form["patient_id"])
    doctor_id = int(form["doctor_id"])
    notes = form.get("notes", "")
    tiers_payant = form.get("tiers_payant") == "on"

    today = date.today()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM invoices WHERE strftime('%Y', invoice_date) = ? ", (str(today.year),)
    )
    count = (await cursor.fetchone())[0]
    invoice_number = _generate_invoice_number(today.year, count)

    # Calculate total from items
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

    cursor = await db.execute(
        """INSERT INTO invoices (invoice_number, patient_id, doctor_id, total_amount, tiers_payant, notes) VALUES (?, ?, ?, ?, ?, ?)""",
        (invoice_number, patient_id, doctor_id, total, tiers_payant, notes or None),
    )
    invoice_id = cursor.lastrowid

    for desc, qty, price, item_total, act_id in items:
        await db.execute(
            """INSERT INTO invoice_items (invoice_id, medical_act_id, description, quantity, unit_price, total_price) VALUES (?, ?, ?, ?, ?, ?)""",
            (invoice_id, act_id, desc, qty, price, item_total),
        )

    await db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def view_invoice(request: Request, invoice_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT i.*, p.first_name || ' ' || p.last_name AS patient_name, p.address, p.city, p.postal_code, p.social_security_number, u.first_name || ' ' || u.last_name AS doctor_name, u.specialty FROM invoices i JOIN patients p ON i.patient_id = p.id JOIN users u ON i.doctor_id = u.id WHERE i.id = ? """,
        (invoice_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/invoices", status_code=302)
    invoice = dict(row)

    cursor = await db.execute("SELECT * FROM invoice_items WHERE invoice_id = ? ", (invoice_id,))
    items = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date", (invoice_id,))
    payments = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "invoices/detail.html",
        {"request": request, "user": user, "active": "invoices", "invoice": invoice, "items": items, "payments": payments},
    )


@router.post("/{invoice_id}/pay")
async def add_payment(
    request: Request,
    invoice_id: int,
    amount: float = Form(...),
    payment_method: str = Form(...),
    reference: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    await db.execute(
        "INSERT INTO payments (invoice_id, amount, payment_method, reference) VALUES (?, ?, ?, ?)",
        (invoice_id, amount, payment_method, reference or None),
    )

    # Update invoice paid_amount and status
    cursor = await db.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE invoice_id = ? ", (invoice_id,))
    total_paid = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT total_amount FROM invoices WHERE id = ? ", (invoice_id,))
    total_amount = (await cursor.fetchone())[0]

    if total_paid >= total_amount:
        status = "payee"
    elif total_paid > 0:
        status = "partiellement_payee"
    else:
        status = "emise"

    await db.execute(
        "UPDATE invoices SET paid_amount = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? ",
        (total_paid, status, invoice_id),
    )
    await db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)
