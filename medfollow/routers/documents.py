import os
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite

from config import TEMPLATES_DIR, UPLOAD_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/documents")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    patient_id: Optional[int] = None,
    category: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = """SELECT d.*, p.first_name || ' ' || p.last_name AS patient_name FROM documents d JOIN patients p ON d.patient_id = p.id WHERE 1=1"""
    params = []

    if patient_id:
        query += " AND d.patient_id = ?"
        params.append(patient_id)
    if category:
        query += " AND d.category = ?"
        params.append(category)

    query += " ORDER BY d.created_at DESC LIMIT 50"
    cursor = await db.execute(query, params)
    documents = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name")
    patients = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "documents/list.html",
        {
            "request": request, "user": user, "active": "documents",
            "documents": documents, "patients": patients,
            "selected_patient_id": patient_id, "selected_category": category,
        },
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_form(
    request: Request,
    patient_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT id, first_name, last_name FROM patients WHERE is_active = 1 ORDER BY last_name")
    patients = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "documents/upload.html",
        {"request": request, "user": user, "active": "documents", "patients": patients, "selected_patient_id": patient_id},
    )


@router.post("/upload")
async def upload_document(
    request: Request,
    patient_id: int = Form(...),
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Create patient upload directory
    patient_dir = os.path.join(UPLOAD_DIR, f"patient_{patient_id}")
    os.makedirs(patient_dir, exist_ok=True)

    # Save file
    safe_filename = file.filename.replace(" ", "_")
    file_path = os.path.join(patient_dir, safe_filename)

    # Handle duplicate filenames
    counter = 1
    base, ext = os.path.splitext(safe_filename)
    while os.path.exists(file_path):
        file_path = os.path.join(patient_dir, f"{base}_{counter}{ext}")
        counter += 1

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    await db.execute(
        """INSERT INTO documents (patient_id, title, category, file_path, file_type, file_size, description, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, title, category, file_path, file.content_type, len(content),
         description or None, user["sub"]),
    )
    await db.commit()

    return RedirectResponse(url="/documents", status_code=302)


@router.get("/{document_id}/download")
async def download_document(request: Request, document_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT * FROM documents WHERE id = ? ", (document_id,))
    row = await cursor.fetchone()
    if not row:
        return RedirectResponse(url="/documents", status_code=302)
    doc = dict(row)

    if not os.path.exists(doc["file_path"]):
        return RedirectResponse(url="/documents", status_code=302)

    return FileResponse(doc["file_path"], filename=os.path.basename(doc["file_path"]), media_type=doc.get("file_type"))


@router.post("/{document_id}/delete")
async def delete_document(request: Request, document_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute("SELECT file_path FROM documents WHERE id = ? ", (document_id,))
    row = await cursor.fetchone()
    if row:
        file_path = row[0]
        if os.path.exists(file_path):
            os.remove(file_path)
        await db.execute("DELETE FROM documents WHERE id = ? ", (document_id,))
        await db.commit()

    return RedirectResponse(url="/documents", status_code=302)
