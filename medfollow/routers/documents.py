import os
import re
import uuid
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import aiosqlite

from config import TEMPLATES_DIR, UPLOAD_DIR, MAX_UPLOAD_SIZE_MB
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/documents")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Upload hardening: only known-safe document/image types, a hard size cap, and a
# server-generated on-disk name (never the client filename — which can carry
# path traversal like '../../evil' or backslashes).
ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".rtf", ".odt", ".dcm",
}
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB


def _sanitize_basename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe base name: strip directory
    components (handles '/', '\\' and '..') and replace unsafe characters."""
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return name or "fichier"


@router.get("/", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    patient_id: Optional[int] = None,
    category: Optional[str] = None,
    page: int = 1,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    per_page = 20
    offset = (page - 1) * per_page

    base_where = "WHERE p.doctor_id = ?"
    params: list = [user["sub"]]

    if patient_id:
        base_where += " AND d.patient_id = ?"
        params.append(patient_id)
    if category:
        base_where += " AND d.category = ?"
        params.append(category)

    count_cursor = await db.execute(
        f"SELECT COUNT(*) FROM documents d JOIN patients p ON d.patient_id = p.id {base_where}",
        params,
    )
    total_count = (await count_cursor.fetchone())[0]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    query = f"""SELECT d.*, p.first_name || ' ' || p.last_name AS patient_name
                FROM documents d JOIN patients p ON d.patient_id = p.id
                {base_where} ORDER BY d.created_at DESC LIMIT ? OFFSET ?"""
    cursor = await db.execute(query, params + [per_page, offset])
    documents = []
    for r in await cursor.fetchall():
        doc = dict(r)
        # Extract file_name from file_path for preview detection
        fp = doc.get("file_path", "")
        doc["file_name"] = os.path.basename(fp) if fp else ""
        documents.append(doc)

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE is_active = 1 AND doctor_id = ? ORDER BY last_name",
        (user["sub"],),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "documents/list.html",
        {
            "request": request, "user": user, "active": "documents",
            "documents": documents, "patients": patients,
            "selected_patient_id": patient_id, "selected_category": category,
            "page": page, "total_pages": total_pages, "total_count": total_count,
        },
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_form(
    request: Request,
    patient_id: Optional[int] = None,
    consultation_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE is_active = 1 AND doctor_id = ? ORDER BY last_name",
        (user["sub"],),
    )
    patients = [dict(r) for r in await cursor.fetchall()]

    return templates.TemplateResponse(
        "documents/upload.html",
        {
            "request": request, "user": user, "active": "documents",
            "patients": patients, "selected_patient_id": patient_id,
            "selected_consultation_id": consultation_id,
        },
    )


@router.post("/upload")
async def upload_document(
    request: Request,
    patient_id: int = Form(...),
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    consultation_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Verify patient belongs to current doctor
    cur = await db.execute(
        "SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?",
        (patient_id, user["sub"]),
    )
    if not await cur.fetchone():
        return RedirectResponse(url="/documents", status_code=302)

    # Validate the upload type by extension (blocks executables / HTML / scripts).
    safe_base = _sanitize_basename(file.filename)
    ext = os.path.splitext(safe_base)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return HTMLResponse(
            "<h2>Type de fichier non autorisé.</h2>"
            "<p><a href='/documents/upload'>Retour</a></p>",
            status_code=400,
        )

    # Create patient upload directory
    patient_dir = os.path.join(UPLOAD_DIR, f"patient_{patient_id}")
    os.makedirs(patient_dir, exist_ok=True)

    # Store under a server-generated random name (keep the sanitized stem for
    # readability). This is confined to patient_dir regardless of the input name.
    stem = os.path.splitext(safe_base)[0][:60] or "fichier"
    stored_name = f"{uuid.uuid4().hex}_{stem}{ext}"
    file_path = os.path.join(patient_dir, stored_name)

    # Stream to disk with a hard byte cap so an oversized upload can't exhaust memory.
    size = 0
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    f.close()
                    os.remove(file_path)
                    return HTMLResponse(
                        f"<h2>Fichier trop volumineux (max {MAX_UPLOAD_SIZE_MB} Mo).</h2>"
                        "<p><a href='/documents/upload'>Retour</a></p>",
                        status_code=413,
                    )
                f.write(chunk)
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    if size == 0:
        os.remove(file_path)
        return HTMLResponse(
            "<h2>Fichier vide.</h2><p><a href='/documents/upload'>Retour</a></p>",
            status_code=400,
        )

    await db.execute(
        """INSERT INTO documents (patient_id, consultation_id, title, category, file_path, file_type, file_size, description, uploaded_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, consultation_id, title, category, file_path, file.content_type, size,
         description or None, user["sub"]),
    )
    await db.commit()

    return RedirectResponse(url="/documents", status_code=302)


@router.get("/{document_id}/download")
async def download_document(request: Request, document_id: int, db: aiosqlite.Connection = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cursor = await db.execute(
        """SELECT d.* FROM documents d JOIN patients p ON d.patient_id = p.id
           WHERE d.id = ? AND p.doctor_id = ?""",
        (document_id, user["sub"]),
    )
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

    cursor = await db.execute(
        """SELECT d.file_path FROM documents d JOIN patients p ON d.patient_id = p.id
           WHERE d.id = ? AND p.doctor_id = ?""",
        (document_id, user["sub"]),
    )
    row = await cursor.fetchone()
    if row:
        file_path = row[0]
        if os.path.exists(file_path):
            os.remove(file_path)
        await db.execute("DELETE FROM documents WHERE id = ? ", (document_id,))
        await db.commit()

    return RedirectResponse(url="/documents", status_code=302)
