from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import TEMPLATES_DIR
from routers.auth import get_current_user
from routers.learning_content import COURSE_CONTENT

router = APIRouter(prefix="/learning")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

COURSES = [
    {"id": 1,  "title": "Traitement Endodontique",              "description": "Canaux radiculaires, mise en forme, irrigation et obturation. Taux de succès > 85 % à long terme.", "category": "Endodontie",              "level": "intermediaire", "duration_hours": 4, "color": "#e05260", "icon": "🦷"},
    {"id": 2,  "title": "Traumatismes Dentaires",               "description": "Protocoles IADT 2020 : fractures, luxations, avulsion et réimplantation d'urgence.",              "category": "Urgences Dentaires",      "level": "intermediaire", "duration_hours": 3, "color": "#e07020", "icon": "🚨"},
    {"id": 3,  "title": "Parodontologie Clinique",              "description": "Classification 2017, staging & grading, thérapeutique non chirurgicale et chirurgicale.",        "category": "Parodontologie",          "level": "avance",        "duration_hours": 5, "color": "#20a060", "icon": "🔬"},
    {"id": 4,  "title": "Implantologie Dentaire",               "description": "Ostéo-intégration, bilan pré-implantaire, protocoles chirurgicaux et gestion des complications.", "category": "Chirurgie Orale",         "level": "avance",        "duration_hours": 8, "color": "#5050d0", "icon": "⚙️"},
    {"id": 5,  "title": "Radiologie et Imagerie Dentaire",      "description": "Rétroalvéolaires, panoramique, CBCT, lecture systématique et radioprotection.",                 "category": "Radiologie",              "level": "debutant",      "duration_hours": 3, "color": "#0090b0", "icon": "🩻"},
    {"id": 6,  "title": "Prothèses Fixes: Couronnes & Bridges", "description": "Préparations, empreintes optiques, choix des matériaux (zircone, e.max) et scellement.",        "category": "Prothèse",                "level": "intermediaire", "duration_hours": 5, "color": "#c0780a", "icon": "👑"},
    {"id": 7,  "title": "Dentisterie Pédiatrique",              "description": "Gestion comportementale, CPE, thérapeutiques pulpaires sur dents temporaires et fluor.",        "category": "Pédiatrique",             "level": "intermediaire", "duration_hours": 4, "color": "#e040b0", "icon": "🧒"},
    {"id": 8,  "title": "Composites & Dentisterie Esthétique",  "description": "Préparations minimalistes, systèmes adhésifs, stratification, polissage et blanchiment.",       "category": "Dentisterie Restauratrice","level": "intermediaire", "duration_hours": 4, "color": "#309080", "icon": "✨"},
    {"id": 9,  "title": "Chirurgie des Dents de Sagesse",       "description": "Classifications de Pell & Gregory, technique d'odontectomie et gestion des complications.",     "category": "Chirurgie Orale",         "level": "avance",        "duration_hours": 4, "color": "#7030c0", "icon": "🔪"},
    {"id": 10, "title": "Orthodontie par Gouttières",           "description": "Indications des aligneurs, biomécanique, attachements, IPR et protocoles de contention.",       "category": "Orthodontie",             "level": "avance",        "duration_hours": 6, "color": "#1870d0", "icon": "😁"},
    {"id": 11, "title": "Hygiène & Prévention",                 "description": "Fluor, scellements de sillons, hygiène interdentaire, alimentation et sevrage tabagique.",      "category": "Prévention",              "level": "debutant",      "duration_hours": 2, "color": "#10a090", "icon": "🪥"},
    {"id": 12, "title": "Urgences Médicales au Cabinet",        "description": "Syncope, anaphylaxie, hypoglycémie, épilepsie et arrêt cardiorespiratoire : protocoles.",       "category": "Urgences Médicales",      "level": "avance",        "duration_hours": 3, "color": "#d02020", "icon": "🚑"},
]

CATEGORIES = sorted({c["category"] for c in COURSES})

LEVEL_LABELS = {
    "debutant":      "Débutant",
    "intermediaire": "Intermédiaire",
    "avance":        "Avancé",
}


@router.get("/", response_class=HTMLResponse)
async def learning_index(request: Request, q: str = "", category: str = "", level: str = ""):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    courses = COURSES
    if q:
        ql = q.lower()
        courses = [c for c in courses if ql in c["title"].lower() or ql in c["description"].lower() or ql in c["category"].lower()]
    if category:
        courses = [c for c in courses if c["category"] == category]
    if level:
        courses = [c for c in courses if c["level"] == level]

    return templates.TemplateResponse("learning/index.html", {
        "request": request, "user": user, "active": "learning",
        "courses": courses, "categories": CATEGORIES, "level_labels": LEVEL_LABELS,
        "q": q, "selected_category": category, "selected_level": level,
        "total_count": len(courses),
    })


@router.get("/{course_id}", response_class=HTMLResponse)
async def course_detail(request: Request, course_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    course = next((c for c in COURSES if c["id"] == course_id), None)
    if not course:
        return RedirectResponse(url="/learning", status_code=302)

    content = COURSE_CONTENT.get(course_id)

    return templates.TemplateResponse("learning/detail.html", {
        "request": request, "user": user, "active": "learning",
        "course": course, "level_labels": LEVEL_LABELS, "wiki_content": content,
    })
