"""Onglet « Modèle 3D » de la fiche patient : modèles .ply de la bouche.

Le dentiste importe le fichier .ply produit par son scanner (empreinte optique)
avec la date de l'acquisition ; la fiche patient affiche l'historique sur une
frise chronologique (la même que l'odontogramme) et rend le modèle dans le
navigateur (three.js, static/js/model3d/). Le serveur ne fait que stocker et
servir les fichiers.

Couleurs : beaucoup de scanners ne les mettent pas dans le .ply mais dans une
image à part, nommée dans l'en-tête (« comment TextureFile xxx.png ») et
plaquée grâce aux coordonnées UV des faces. Le rattachement est automatique,
quel que soit l'ordre d'import :
- .ply et image envoyés ensemble → image du modèle ;
- image envoyée seule (POST …/images) → rattachée aux modèles du patient dont
  l'en-tête la nomme, sinon gardée en attente ;
- .ply envoyé seul → reprend l'image en attente, ou celle d'un modèle déjà
  importé qui nomme la même image (doublons « LowerJaw (1).ply »).

Préfixe /modele-3d/{patient_id}/… — réservé aux praticiens (pas de secrétaire),
chaque appel vérifie que le patient appartient au médecin connecté.
"""
import hashlib
import os
import re
import shutil
import uuid
from datetime import date

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from config import UPLOAD_DIR
from database.connection import get_db
from routers.dental import _owns_patient
from routers.deps import deny_secretaire
from services.audit import client_ip, log_audit

router = APIRouter(prefix="/modele-3d", dependencies=[Depends(deny_secretaire)])

MODELS_DIR = os.path.join(UPLOAD_DIR, "models3d")
# Pas de limite de taille (demande explicite) : les fichiers sont écrits sur
# disque par blocs de 1 Mo, jamais chargés entièrement en mémoire.
# Extension -> signature attendue en tête de fichier.
TEXTURE_EXT = {".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
_TEXTURE_REF = re.compile(rb"^comment\s+TextureFile\s+(.+?)\s*$", re.MULTILINE)


def _row(r) -> dict:
    return {
        "id": r["id"],
        "scan_date": r["scan_date"],
        "original_name": r["original_name"] or f"modele-{r['id']}.ply",
        "file_size": r["file_size"] or 0,
        "created_at": r["created_at"],
        "url": f"/modele-3d/{r['patient_id']}/{r['id']}/fichier",
        "texture_ref": r["texture_ref"] or None,
        "texture_name": r["texture_name"],
        # ?v= : l'URL change quand l'image est remplacée (caches navigateur et visionneuse).
        "texture_url": (f"/modele-3d/{r['patient_id']}/{r['id']}/texture"
                        f"?v={os.path.basename(r['texture_path'])[:8]}") if r["texture_path"] else None,
    }


async def _owned_model(db: aiosqlite.Connection, patient_id: int, model_id: int, uid: int):
    cur = await db.execute(
        "SELECT * FROM dental_models_3d WHERE id = ? AND patient_id = ? AND doctor_id = ?",
        (model_id, patient_id, uid),
    )
    return await cur.fetchone()


def _patient_dir(patient_id: int) -> str:
    path = os.path.join(MODELS_DIR, f"patient_{patient_id}")
    os.makedirs(path, exist_ok=True)
    return path


async def _save_texture(upload: UploadFile, patient_id: int):
    """Enregistre l'image de texture. Renvoie (chemin, nom d'origine) ou (None, message d'erreur)."""
    name = os.path.basename(upload.filename or "").strip() or "texture.png"
    ext = os.path.splitext(name)[1].lower()
    if ext not in TEXTURE_EXT:
        return None, f"« {name} » : la texture doit être une image PNG ou JPEG"
    path = os.path.join(_patient_dir(patient_id), f"{uuid.uuid4().hex}{ext}")
    size, error = 0, None
    with open(path, "wb") as f:
        while chunk := await upload.read(1024 * 1024):
            if size == 0 and not chunk.startswith(TEXTURE_EXT[ext]):
                error = f"« {name} » n'est pas une image {ext[1:].upper()} valide"
                break
            size += len(chunk)
            f.write(chunk)
    if not error and size == 0:
        error = f"« {name} » est vide"
    if error:
        os.remove(path)
        return None, error
    return path, name


def _copy_texture(src: str, patient_id: int) -> str:
    """Copie propre à chaque modèle : supprimer un modèle ne doit pas priver les autres de leur image."""
    dst = os.path.join(_patient_dir(patient_id), f"{uuid.uuid4().hex}{os.path.splitext(src)[1]}")
    shutil.copyfile(src, dst)
    return dst


async def _find_texture(db: aiosqlite.Connection, patient_id: int, uid: int, ref: str):
    """Image déjà connue pour ce nom : en attente (importée avant le .ply), sinon celle d'un
    autre modèle du patient qui nomme la même image. Renvoie (chemin, nom) ou (None, None)."""
    cur = await db.execute(
        """SELECT id, name, path FROM dental_model_pending_textures
           WHERE patient_id = ? AND doctor_id = ? AND lower(name) = lower(?) ORDER BY id DESC""",
        (patient_id, uid, ref),
    )
    pending = await cur.fetchone()
    if pending and os.path.exists(pending["path"]):
        await db.execute("DELETE FROM dental_model_pending_textures WHERE id = ?", (pending["id"],))
        return pending["path"], pending["name"]
    cur = await db.execute(
        """SELECT texture_path, texture_name FROM dental_models_3d
           WHERE patient_id = ? AND doctor_id = ? AND lower(texture_ref) = lower(?) AND texture_path IS NOT NULL
           ORDER BY id DESC""",
        (patient_id, uid, ref),
    )
    for sibling in await cur.fetchall():
        if os.path.exists(sibling["texture_path"]):
            return _copy_texture(sibling["texture_path"], patient_id), sibling["texture_name"]
    return None, None


@router.get("/{patient_id}")
async def list_models(patient_id: int, user: dict = Depends(deny_secretaire),
                      db: aiosqlite.Connection = Depends(get_db)):
    if not await _owns_patient(db, patient_id, user["sub"]):
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})
    cur = await db.execute(
        """SELECT * FROM dental_models_3d WHERE patient_id = ? AND doctor_id = ?
           ORDER BY scan_date, id""",
        (patient_id, user["sub"]),
    )
    return JSONResponse(content={"models": [_row(r) for r in await cur.fetchall()]})


@router.post("/{patient_id}")
async def upload_model(request: Request, patient_id: int, scan_date: str = Form(...),
                       file: UploadFile = File(...), texture: UploadFile | None = File(None),
                       user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    if not await _owns_patient(db, patient_id, user["sub"]):
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})

    try:
        day = date.fromisoformat((scan_date or "")[:10])
    except ValueError:
        return JSONResponse(status_code=422, content={"error": "Date de la radio invalide"})
    if day > date.today():
        return JSONResponse(status_code=422, content={"error": "La date de la radio ne peut pas être dans le futur"})

    original_name = os.path.basename(file.filename or "").strip() or "modele.ply"
    if os.path.splitext(original_name)[1].lower() != ".ply":
        return JSONResponse(status_code=422, content={"error": "Format non pris en charge : importez un fichier .ply"})

    # Nom de fichier généré côté serveur : le nom client peut porter un « ../ ».
    path = os.path.join(_patient_dir(patient_id), f"{uuid.uuid4().hex}.ply")

    size = 0
    error = None
    texture_ref = None
    digest = hashlib.sha256()
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            if size == 0:
                # Un PLY commence toujours par la ligne magique « ply ».
                if not chunk.lstrip(b"\xef\xbb\xbf").startswith(b"ply"):
                    error = "Ce fichier n'est pas un modèle PLY valide"
                    break
                header = chunk.split(b"end_header", 1)[0]
                if (m := _TEXTURE_REF.search(header)):
                    texture_ref = os.path.basename(m.group(1).decode("utf-8", "replace"))[:255]
            size += len(chunk)
            digest.update(chunk)
            f.write(chunk)
    if not error and size == 0:
        error = "Le fichier est vide"
    if error:
        os.remove(path)
        return JSONResponse(status_code=422, content={"error": error})
    sha = digest.hexdigest()

    # Même fichier déjà importé à cette date (ex. « LowerJaw (1).ply » re-téléchargé) : pas de
    # doublon — deux maillages superposés se masqueraient l'un l'autre. Une image envoyée avec
    # lui est rattachée au modèle existant.
    cur = await db.execute(
        "SELECT * FROM dental_models_3d WHERE patient_id = ? AND doctor_id = ? AND scan_date = ? AND file_sha256 = ? "
        "ORDER BY id LIMIT 1",
        (patient_id, user["sub"], day.isoformat(), sha),
    )
    existing = await cur.fetchone()
    if existing:
        os.remove(path)
        if texture is not None and texture.filename:
            texture_path, texture_name = await _save_texture(texture, patient_id)
            if not texture_path:
                return JSONResponse(status_code=422, content={"error": texture_name})
            await db.execute("UPDATE dental_models_3d SET texture_path = ?, texture_name = ? WHERE id = ?",
                             (texture_path, texture_name, existing["id"]))
            await db.commit()
            if existing["texture_path"]:
                try:
                    os.remove(existing["texture_path"])
                except OSError:
                    pass
        row = await _owned_model(db, patient_id, existing["id"], user["sub"])
        return JSONResponse(content={**_row(row), "duplicate": True})

    texture_path = texture_name = None
    if texture is not None and texture.filename:
        texture_path, texture_name = await _save_texture(texture, patient_id)
        if not texture_path:
            os.remove(path)
            return JSONResponse(status_code=422, content={"error": texture_name})
    elif texture_ref:
        texture_path, texture_name = await _find_texture(db, patient_id, user["sub"], texture_ref)

    cur = await db.execute(
        """INSERT INTO dental_models_3d (patient_id, doctor_id, scan_date, file_path, original_name, file_size,
                                         texture_ref, texture_path, texture_name, file_sha256)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, user["sub"], day.isoformat(), path, original_name, size, texture_ref, texture_path, texture_name,
         sha),
    )
    await db.commit()
    model_id = cur.lastrowid
    await log_audit(db, user, "modele3d_importe", entity_type="dental_model_3d", entity_id=model_id,
                    patient_id=patient_id, ip=client_ip(request), details=f"{original_name} ({day.isoformat()})")

    row = await _owned_model(db, patient_id, model_id, user["sub"])
    return JSONResponse(status_code=201, content=_row(row))


@router.post("/{patient_id}/images")
async def upload_images(request: Request, patient_id: int, images: list[UploadFile] = File(...),
                        user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    """Images de couleurs envoyées sans leur .ply : rattachées aux modèles du patient dont
    l'en-tête les nomme (en remplaçant l'éventuelle ancienne image), sinon mises en attente."""
    if not await _owns_patient(db, patient_id, user["sub"]):
        return JSONResponse(status_code=404, content={"error": "Patient introuvable"})
    attached, pending, errors = [], [], []
    for image in images:
        path, name = await _save_texture(image, patient_id)
        if not path:
            errors.append(name)
            continue
        cur = await db.execute(
            """SELECT id, texture_path FROM dental_models_3d
               WHERE patient_id = ? AND doctor_id = ? AND lower(texture_ref) = lower(?)""",
            (patient_id, user["sub"], name),
        )
        targets = await cur.fetchall()
        if not targets:
            # Le .ply viendra plus tard : on remplace une éventuelle attente du même nom.
            cur = await db.execute(
                "SELECT id, path FROM dental_model_pending_textures WHERE patient_id = ? AND doctor_id = ? AND lower(name) = lower(?)",
                (patient_id, user["sub"], name),
            )
            for old in await cur.fetchall():
                await db.execute("DELETE FROM dental_model_pending_textures WHERE id = ?", (old["id"],))
                try:
                    os.remove(old["path"])
                except OSError:
                    pass
            await db.execute(
                "INSERT INTO dental_model_pending_textures (patient_id, doctor_id, name, path) VALUES (?, ?, ?, ?)",
                (patient_id, user["sub"], name, path),
            )
            pending.append(name)
            continue
        for i, t in enumerate(targets):
            model_path = path if i == 0 else _copy_texture(path, patient_id)
            await db.execute("UPDATE dental_models_3d SET texture_path = ?, texture_name = ? WHERE id = ?",
                             (model_path, name, t["id"]))
            if t["texture_path"]:
                try:
                    os.remove(t["texture_path"])
                except OSError:
                    pass
        attached.append({"name": name, "models": [t["id"] for t in targets]})
        await log_audit(db, user, "modele3d_texture", entity_type="dental_model_3d", entity_id=targets[0]["id"],
                        patient_id=patient_id, ip=client_ip(request), details=name)
    await db.commit()
    return JSONResponse(content={"attached": attached, "pending": pending, "errors": errors})


@router.get("/{patient_id}/{model_id}/fichier")
async def model_file(patient_id: int, model_id: int, download: bool = False,
                     user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    row = await _owned_model(db, patient_id, model_id, user["sub"])
    if not row or not os.path.exists(row["file_path"]):
        return JSONResponse(status_code=404, content={"error": "Modèle introuvable"})
    return FileResponse(
        row["file_path"], media_type="application/octet-stream",
        filename=row["original_name"] or f"modele-{model_id}.ply",
        content_disposition_type="attachment" if download else "inline",
    )


@router.post("/{patient_id}/{model_id}/texture")
async def upload_texture(request: Request, patient_id: int, model_id: int, texture: UploadFile = File(...),
                         user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    """Ajoute (ou remplace) l'image de couleurs d'un modèle déjà importé."""
    row = await _owned_model(db, patient_id, model_id, user["sub"])
    if not row:
        return JSONResponse(status_code=404, content={"error": "Modèle introuvable"})
    path, name = await _save_texture(texture, patient_id)
    if not path:
        return JSONResponse(status_code=422, content={"error": name})
    await db.execute("UPDATE dental_models_3d SET texture_path = ?, texture_name = ? WHERE id = ?",
                     (path, name, model_id))
    await db.commit()
    if row["texture_path"]:
        try:
            os.remove(row["texture_path"])
        except OSError:
            pass
    await log_audit(db, user, "modele3d_texture", entity_type="dental_model_3d", entity_id=model_id,
                    patient_id=patient_id, ip=client_ip(request), details=name)
    return JSONResponse(content=_row(await _owned_model(db, patient_id, model_id, user["sub"])))


@router.get("/{patient_id}/{model_id}/texture")
async def texture_file(patient_id: int, model_id: int,
                       user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    row = await _owned_model(db, patient_id, model_id, user["sub"])
    if not row or not row["texture_path"] or not os.path.exists(row["texture_path"]):
        return JSONResponse(status_code=404, content={"error": "Texture introuvable"})
    return FileResponse(row["texture_path"])


@router.delete("/{patient_id}/{model_id}")
async def delete_model(request: Request, patient_id: int, model_id: int,
                       user: dict = Depends(deny_secretaire), db: aiosqlite.Connection = Depends(get_db)):
    row = await _owned_model(db, patient_id, model_id, user["sub"])
    if not row:
        return JSONResponse(status_code=404, content={"error": "Modèle introuvable"})
    await db.execute("DELETE FROM dental_models_3d WHERE id = ?", (model_id,))
    await db.commit()
    for p in (row["file_path"], row["texture_path"]):
        if not p:
            continue
        try:
            os.remove(p)
        except OSError:
            pass
    await log_audit(db, user, "modele3d_supprime", entity_type="dental_model_3d", entity_id=model_id,
                    patient_id=patient_id, ip=client_ip(request), details=row["original_name"])
    return Response(status_code=204)
