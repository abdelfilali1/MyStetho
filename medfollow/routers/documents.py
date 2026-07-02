import mimetypes
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
from routers.deps import require_login, effective_doctor_id, set_flash, deny_secretaire
from services.audit import log_audit, client_ip

router = APIRouter(prefix="/documents", dependencies=[Depends(deny_secretaire)])
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
# Les BMP non compressés plus lourds que ce seuil sont convertis en PNG.
_BMP_TO_PNG_THRESHOLD_BYTES = 2 * 1024 * 1024

DOCUMENT_CATEGORIES = [
    ("radio", "Radiologie"),
    ("photo_extra_orale", "Photo Extra Orale"),
    ("photo_intra_orale", "Photo Intra Orale"),
    ("labo", "Laboratoire"),
    ("courrier", "Courrier"),
    ("compte_rendu", "Compte-rendu"),
    ("ordonnance", "Ordonnance"),
    ("autre", "Autre"),
]


def _sanitize_basename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe base name: strip directory
    components (handles '/', '\\' and '..') and replace unsafe characters."""
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return name or "fichier"


async def _get_owned_document(
    db: aiosqlite.Connection, document_id: int, doctor_id: int
) -> Optional[dict]:
    """Charge un document en vérifiant qu'il appartient bien au médecin (anti-IDOR)."""
    cursor = await db.execute(
        """SELECT d.*, p.first_name || ' ' || p.last_name AS patient_name
           FROM documents d JOIN patients p ON d.patient_id = p.id
           WHERE d.id = ? AND p.doctor_id = ?""",
        (document_id, doctor_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _save_one_file(
    db: aiosqlite.Connection,
    file: UploadFile,
    patient_id: int,
    consultation_id: Optional[int],
    title: str,
    category: str,
    description: str,
    uploaded_by: int,
) -> tuple[Optional[int], Optional[str]]:
    """Valide, écrit sur disque et insère UN fichier importé.

    Retourne (document_id, None) en cas de succès, (None, message d'erreur) sinon.
    Le commit est laissé à l'appelant.
    """
    original_name = (file.filename or "").strip()

    # Validate the upload type by extension (blocks executables / HTML / scripts).
    safe_base = _sanitize_basename(original_name)
    ext = os.path.splitext(safe_base)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return None, f"« {original_name or 'fichier'} » : type de fichier non autorisé"

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
                    return None, (
                        f"« {original_name} » : fichier trop volumineux (max {MAX_UPLOAD_SIZE_MB} Mo)"
                    )
                f.write(chunk)
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        return None, f"« {original_name or 'fichier'} » : échec de l'enregistrement"

    if size == 0:
        os.remove(file_path)
        return None, f"« {original_name or 'fichier'} » : fichier vide"

    file_type = file.content_type

    # Les BMP volumineux (format non compressé) sont convertis en PNG pour
    # économiser l'espace disque. En cas d'échec, le BMP d'origine est conservé.
    if ext == ".bmp" and size > _BMP_TO_PNG_THRESHOLD_BYTES:
        png_path = os.path.splitext(file_path)[0] + ".png"
        try:
            from PIL import Image

            with Image.open(file_path) as im:
                im.save(png_path, format="PNG")
            os.remove(file_path)
            file_path = png_path
            file_type = "image/png"
            size = os.path.getsize(png_path)
        except Exception:
            # Conversion ratée : on nettoie l'éventuel PNG partiel, le BMP reste.
            if file_path != png_path and os.path.exists(png_path):
                try:
                    os.remove(png_path)
                except OSError:
                    pass

    cursor = await db.execute(
        """INSERT INTO documents (patient_id, consultation_id, title, category, file_path, file_type, file_size, description, uploaded_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, consultation_id, title, category, file_path, file_type, size,
         description or None, uploaded_by),
    )
    return cursor.lastrowid, None


@router.get("/", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    patient_id: Optional[int] = None,
    category: Optional[str] = None,
    page: int = 1,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    doctor_id = effective_doctor_id(user)

    per_page = 20
    offset = (page - 1) * per_page

    base_where = "WHERE p.doctor_id = ?"
    params: list = [doctor_id]

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
        (doctor_id,),
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
    user: dict = Depends(require_login),
):
    cursor = await db.execute(
        "SELECT id, first_name, last_name FROM patients WHERE is_active = 1 AND doctor_id = ? ORDER BY last_name",
        (effective_doctor_id(user),),
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
    files: list[UploadFile] = File(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    # Verify patient belongs to current doctor
    cur = await db.execute(
        "SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?",
        (patient_id, effective_doctor_id(user)),
    )
    if not await cur.fetchone():
        response = RedirectResponse(url="/documents", status_code=302)
        set_flash(response, "Patient introuvable.", type_="error")
        return response

    saved_count = 0
    saved_ids: list[int] = []
    errors: list[str] = []
    for idx, upload in enumerate(files):
        # Premier fichier : titre saisi ; suivants : « Titre — 2 », « Titre — 3 »…
        item_title = title if idx == 0 else f"{title} — {idx + 1}"
        doc_id, error = await _save_one_file(
            db, upload, patient_id, consultation_id,
            item_title, category, description, user["sub"],
        )
        if error:
            errors.append(error)
            continue
        saved_count += 1
        saved_ids.append(doc_id)
    # Un seul commit pour l'ensemble des fichiers (l'audit, qui commit lui-même,
    # est émis APRÈS pour ne pas casser l'atomicité du lot).
    await db.commit()
    for doc_id in saved_ids:
        await log_audit(
            db, user, "document_importe",
            entity_type="document", entity_id=doc_id, patient_id=patient_id,
            ip=client_ip(request),
        )

    # Retour vers l'onglet Documents du patient : meilleur enchaînement quand
    # l'import vient de la fiche patient.
    redirect_url = f"/patients/{patient_id}?tab=documents" if patient_id else "/documents"
    response = RedirectResponse(url=redirect_url, status_code=302)
    message = f"{saved_count} document(s) importé(s)"
    if errors:
        message += ". Erreur(s) : " + " ; ".join(errors)
        set_flash(response, message, type_="error" if saved_count == 0 else "info")
    else:
        set_flash(response, message)
    return response


@router.get("/{document_id}/view")
async def view_document(
    request: Request,
    document_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    """Sert le fichier en inline (aperçu iframe/img), contrairement à /download."""
    doc = await _get_owned_document(db, document_id, effective_doctor_id(user))
    if not doc or not os.path.exists(doc["file_path"]):
        response = RedirectResponse(url="/documents", status_code=302)
        set_flash(response, "Document introuvable.", type_="error")
        return response

    media_type = (
        doc.get("file_type")
        or mimetypes.guess_type(doc["file_path"])[0]
        or "application/octet-stream"
    )

    await log_audit(
        db, user, "document_apercu",
        entity_type="document", entity_id=document_id, patient_id=doc["patient_id"],
        ip=client_ip(request),
    )

    response = FileResponse(
        doc["file_path"],
        media_type=media_type,
        filename=os.path.basename(doc["file_path"]),
        content_disposition_type="inline",
    )
    # Le middleware global pose X-Frame-Options: DENY et frame-ancestors 'none'
    # via headers.setdefault : on pré-remplit ici pour autoriser l'affichage
    # dans une iframe same-origin (aperçu), sans ouvrir aux autres origines.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return response


@router.get("/{document_id}/download")
async def download_document(
    request: Request,
    document_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    doc = await _get_owned_document(db, document_id, effective_doctor_id(user))
    if not doc or not os.path.exists(doc["file_path"]):
        response = RedirectResponse(url="/documents", status_code=302)
        set_flash(response, "Document introuvable.", type_="error")
        return response

    await log_audit(
        db, user, "document_telecharge",
        entity_type="document", entity_id=document_id, patient_id=doc["patient_id"],
        ip=client_ip(request),
    )

    return FileResponse(doc["file_path"], filename=os.path.basename(doc["file_path"]), media_type=doc.get("file_type"))


@router.get("/{document_id}/edit", response_class=HTMLResponse)
async def edit_document_form(
    request: Request,
    document_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    doc = await _get_owned_document(db, document_id, effective_doctor_id(user))
    if not doc:
        response = RedirectResponse(url="/documents", status_code=302)
        set_flash(response, "Document introuvable.", type_="error")
        return response

    fp = doc.get("file_path") or ""
    doc["file_name"] = os.path.basename(fp) if fp else ""

    return templates.TemplateResponse(
        "documents/edit.html",
        {
            "request": request, "user": user, "active": "documents",
            "doc": doc, "categories": DOCUMENT_CATEGORIES,
            "from_page": request.query_params.get("from", ""),
        },
    )


@router.post("/{document_id}/edit")
async def update_document(
    request: Request,
    document_id: int,
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    from_page: str = Form(""),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    doc = await _get_owned_document(db, document_id, effective_doctor_id(user))
    if not doc:
        response = RedirectResponse(url="/documents", status_code=302)
        set_flash(response, "Document introuvable.", type_="error")
        return response

    await db.execute(
        "UPDATE documents SET title = ?, category = ?, description = ? WHERE id = ?",
        (title, category, description or None, document_id),
    )
    await db.commit()

    await log_audit(
        db, user, "document_modifie",
        entity_type="document", entity_id=document_id, patient_id=doc["patient_id"],
        ip=client_ip(request),
    )

    redirect_url = (
        f"/patients/{doc['patient_id']}?tab=documents" if from_page == "patient" else "/documents"
    )
    response = RedirectResponse(url=redirect_url, status_code=302)
    set_flash(response, "Document modifié")
    return response


@router.post("/{document_id}/delete")
async def delete_document(
    request: Request,
    document_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(require_login),
):
    cursor = await db.execute(
        """SELECT d.file_path, d.patient_id FROM documents d JOIN patients p ON d.patient_id = p.id
           WHERE d.id = ? AND p.doctor_id = ?""",
        (document_id, effective_doctor_id(user)),
    )
    row = await cursor.fetchone()

    response = RedirectResponse(url="/documents", status_code=302)
    if row:
        file_path, doc_patient_id = row[0], row[1]
        if os.path.exists(file_path):
            os.remove(file_path)
        await db.execute("DELETE FROM documents WHERE id = ? ", (document_id,))
        await db.commit()
        await log_audit(
            db, user, "document_supprime",
            entity_type="document", entity_id=document_id, patient_id=doc_patient_id,
            ip=client_ip(request),
        )
        set_flash(response, "Document supprimé")
    else:
        set_flash(response, "Document introuvable.", type_="error")
    return response
