import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

from config import TEMPLATES_DIR
from database.connection import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/mutuelle")
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
        "FROM patients WHERE is_active = 1 ORDER BY last_name, first_name"
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
