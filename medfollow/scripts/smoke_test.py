"""Smoke test : exerce les principaux endpoints en écriture contre une base
fraîchement initialisée, et vérifie qu'aucun ne renvoie 500.

Usage :
    cd medfollow && py scripts/smoke_test.py

Utilise une base SQLite temporaire (MEDFOLLOW_DATABASE_PATH) et le TestClient
Starlette (pas de serveur à lancer). Gère le jeton CSRF double-submit.
"""
import os
import sys
import tempfile

# Base temporaire + email admin déterministe AVANT l'import de l'app
_TMP_DB = os.path.join(tempfile.gettempdir(), "medfollow_smoke.db")
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP_DB + suffix)
    except OSError:
        pass
os.environ["MEDFOLLOW_DATABASE_PATH"] = _TMP_DB
os.environ["MEDFOLLOW_ADMIN_EMAIL"] = "admin@smoke.test"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

failures = []
# Le "with" déclenche le lifespan (init_db + seed_db) — indispensable.
_ctx = TestClient(app)
client = _ctx.__enter__()


def csrf():
    # GET une page pour (re)poser le cookie csrf_token, puis le renvoyer
    client.get("/login")
    return client.cookies.get("csrf_token", "")


def post(path, data=None, files=None, expect=(200, 302, 303), label=None):
    token = csrf()
    headers = {"X-CSRF-Token": token}
    payload = dict(data or {})
    payload["csrf_token"] = token
    if files:
        r = client.post(path, data=payload, files=files, headers=headers, follow_redirects=False)
    else:
        r = client.post(path, data=payload, headers=headers, follow_redirects=False)
    ok = r.status_code in expect
    tag = label or path
    print(f"  {'OK ' if ok else 'XX '} POST {tag} -> {r.status_code}")
    if not ok:
        failures.append(f"POST {tag} -> {r.status_code} (attendu {expect})")
    return r


def get(path, expect=(200, 302, 303), label=None):
    r = client.get(path, follow_redirects=False)
    ok = r.status_code in expect
    tag = label or path
    print(f"  {'OK ' if ok else 'XX '} GET  {tag} -> {r.status_code}")
    if not ok:
        failures.append(f"GET {tag} -> {r.status_code} (attendu {expect})")
    return r


print("== Setup ==")
post("/setup", {
    "email": "admin@smoke.test", "password": "Password123!", "password_confirm": "Password123!",
    "first_name": "Smoke", "last_name": "Admin", "specialty": "Dentiste",
})

print("== Patients ==")
post("/patients/quick", {"first_name": "Jean", "last_name": "Test", "date_of_birth": "1990-01-01", "gender": "M"})
get("/patients/?sort_by=last_visit&sort_order=desc", label="/patients (sort last_visit)")
get("/patients/1")
post("/patients/1/history", {"type": "allergy", "description": "Pénicilline", "date_recorded": ""})
post("/patients/1/history/1/edit", {"type": "allergy", "description": "Pénicilline (grave)"})

print("== Consultations (item 23/28) ==")
post("/consultations/new", {"patient_id": "1", "doctor_id": "1", "consultation_date": "2026-02-10", "reason": "Controle", "dental_medical_history": "Diabète"})
get("/consultations/1")

print("== Prescriptions (item 27) ==")
get("/prescriptions/patient/1/alerts")
post("/prescriptions/new", {"patient_id": "1", "doctor_id": "1", "notes": "Test", "med_name_0": "Amoxicilline", "med_dosage_0": "1g", "med_frequency_0": "2x/j", "med_duration_0": "7 jours", "med_quantity_0": "1"})

print("== Appointments (item 30) ==")
post("/appointments/new", {"patient_id": "1", "doctor_id": "1", "title": "RDV", "appointment_type": "consultation", "status": "planifie", "start_datetime": "2026-03-01T09:00", "end_datetime": "2026-03-01T09:30"})

print("== Invoices (item 14) ==")
post("/invoices/new", {"patient_id": "1", "doctor_id": "1", "notes": "", "item_desc_0": "Consultation", "item_qty_0": "1", "item_price_0": "300"})
get("/invoices/1")
get("/invoices/1/pdf", label="/invoices/1/pdf")
post("/invoices/1/pay", {"amount": "300", "payment_method": "especes", "reference": ""})

print("== Devis workflow (item 21) ==")
post("/invoices/devis/new", {"patient_id": "1", "valid_until": "2026-08-01", "notes": "", "item_desc_0": "Couronne", "item_teeth_0": "26", "item_qty_0": "1", "item_price_0": "2000"})
get("/invoices/devis/1")
get("/invoices/devis/1/pdf", label="/invoices/devis/1/pdf")
# Modification apres creation : prix change, ligne ajoutee, ligne supprimee.
get("/invoices/devis/1/edit", label="/invoices/devis/1/edit")
post("/invoices/devis/1/edit", {
    "valid_until": "2026-09-01", "notes": "revise",
    "item_desc_0": "Couronne", "item_teeth_0": "26", "item_qty_0": "1", "item_price_0": "1800",
    "item_desc_1": "Extraction", "item_teeth_1": "38", "item_qty_1": "1", "item_price_1": "400",
})
# Remise : le devis 1 ci-dessus n'envoie aucun champ de remise (non-regression du
# cas « sans remise »). Celui-ci verifie la conversion du pourcentage, l'ecretage
# a hauteur du sous-total, et le report de la remise sur la facture.
post("/invoices/devis/new", {
    "patient_id": "1", "valid_until": "2026-08-01", "notes": "",
    "item_desc_0": "Couronne", "item_qty_0": "2", "item_price_0": "1000",
    "discount_type": "pourcent", "discount_value": "10",
}, label="/invoices/devis/new (remise 10 %)")
get("/invoices/devis/2", label="/invoices/devis/2 (remise)")
get("/invoices/devis/2/pdf", label="/invoices/devis/2/pdf (remise)")
post("/invoices/devis/2/edit", {
    "valid_until": "2026-09-01", "notes": "",
    "item_desc_0": "Couronne", "item_qty_0": "2", "item_price_0": "1000",
    "discount_type": "montant", "discount_value": "99999",
}, label="/invoices/devis/2/edit (remise ecretee)")

post("/invoices/devis/1/status", {"status": "accepte"})
post("/invoices/devis/1/convert")
# Un devis converti n'est plus modifiable : redirection, pas d'erreur serveur.
get("/invoices/devis/1/edit", expect=(302, 303), label="/invoices/devis/1/edit (converti -> refuse)")

print("== Fiche patient : onglets Devis & Factures + Analyses ==")
_r = get("/patients/1", label="/patients/1 (onglets)")
for _needle, _label in (
    ('id="view-facturation"', "onglet Devis & Factures"),
    ('id="view-analyses"', "onglet Analyses"),
    ("'facturation','analyses'", "onglets declares cote JS"),
):
    _ok = _needle in _r.text
    print(f"  {'OK ' if _ok else 'XX '} {_label}")
    if not _ok:
        failures.append(f"fiche patient : {_label} absent")

print("== Dental (item 24) ==")
post("/dental/1/tooth/26/condition", {"condition": "carie"})
post("/dental/1/tooth/26/condition", {"condition": "obturation", "surface": "occlusal"}, label="/dental tooth surface")
post("/dental/1/tooth/18/condition", {"condition": "extraction"}, label="/dental tooth 18 extraction")


def json_call(method, path, body=None, expect=(200,), label=None):
    """Appel JSON (X-Requested-With + CSRF) vers les API /odonto et /perio."""
    token = csrf()
    headers = {"X-CSRF-Token": token, "X-Requested-With": "fetch"}
    r = client.request(method, path, json=body, headers=headers)
    ok = r.status_code in expect
    tag = label or path
    print(f"  {'OK ' if ok else 'XX '} {method} {tag} -> {r.status_code}")
    if not ok:
        failures.append(f"{method} {tag} -> {r.status_code} (attendu {expect}) {r.text[:200]}")
    try:
        return r.json()
    except Exception:
        return None


def check(cond, label):
    print(f"  {'OK ' if cond else 'XX '} {label}")
    if not cond:
        failures.append(label)


print("== Odontogramme (modele dentalpin) ==")
# Migration unique des anciennes conditions -> nouveau modele (normalement au demarrage).
import asyncio  # noqa: E402
import aiosqlite  # noqa: E402
from services.odonto_service import migrate_legacy_odontogram  # noqa: E402


async def _migrate():
    db = await aiosqlite.connect(_TMP_DB)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        return await migrate_legacy_odontogram(db)
    finally:
        await db.close()


print("  migration legacy :", asyncio.run(_migrate()))
_odo = json_call("GET", "/odonto/1") or {}
_types = {(t["clinical_type"], tuple(x["tooth_number"] for x in t["teeth"])): t for t in _odo.get("treatments", [])}
check(("caries", (26,)) in _types, "migration : carie sur 26")
_fc = _types.get(("filling_composite", (26,)))
check(bool(_fc) and _fc["teeth"][0]["surfaces"] == ["O"], "migration : obturation composite face O sur 26")
check(("missing", (18,)) in _types, "migration : dent 18 absente")
_t1 = json_call("POST", "/odonto/1/treatments", {"clinical_type": "crown", "tooth_numbers": [16], "status": "performed"}, expect=(201,), label="/odonto couronne 16") or {}
_t2 = json_call("POST", "/odonto/1/treatments", {"clinical_type": "bridge", "status": "planned", "teeth": [
    {"tooth_number": 14, "role": "pillar"}, {"tooth_number": 15, "role": "pontic"}, {"tooth_number": 16, "role": "pillar"}]},
    expect=(201,), label="/odonto bridge 14-16") or {}
check([x.get("role") for x in _t2.get("teeth", [])] == ["pillar", "pontic", "pillar"], "bridge : roles pilier/pont")
json_call("POST", "/odonto/1/treatments", {"clinical_type": "bridge", "tooth_numbers": [11]}, expect=(400,), label="/odonto bridge 1 dent (refuse)")
_t3 = json_call("POST", "/odonto/1/treatments", {"clinical_type": "filling_composite", "tooth_numbers": [36], "surfaces": ["M", "O"], "status": "planned"}, expect=(201,), label="/odonto composite 36 M-O") or {}
json_call("PATCH", f"/odonto/1/treatments/{_t3.get('id')}/perform", {}, label="/odonto perform")
json_call("PUT", f"/odonto/1/treatments/{_t3.get('id')}", {"surfaces": ["M", "O", "D"]}, label="/odonto update surfaces")
json_call("GET", "/odonto/1/timeline")
_at = json_call("GET", "/odonto/1/at?date=2020-01-01") or {}
check(_at.get("treatments") == [], "/odonto at 2020 : vide")
json_call("GET", "/odonto/1/history")
json_call("PUT", "/odonto/1/teeth/18", {"general_condition": "healthy"}, label="/odonto tooth 18 healthy")
json_call("DELETE", f"/odonto/1/treatments/{_t1.get('id')}", expect=(204,), label="/odonto delete couronne")

print("== Odontogramme : catalogue d'actes ==")
_cat = _odo.get("catalog") or []
_cats = [c["key"] for c in (_odo.get("catalog_categories") or [])]
check(len(_cat) == 60, f"catalogue : 60 actes mappes ({len(_cat)})")
check(_cats == ["diagnostico", "restauradora", "cirugia", "endodoncia", "ortodoncia", "preventivo", "periodoncia", "pediatrica"],
      f"catalogue : 8 categories dans l'ordre dentalpin ({_cats})")
check(sum(1 for c in _cat if c["category"] == "restauradora") == 29, "catalogue : 29 actes en Restauration")
check(sum(1 for c in _cat if c["category"] == "cirugia") == 9, "catalogue : 9 actes en Chirurgie")
_c1 = json_call("POST", "/odonto/1/treatments", {"catalog_code": "REST-CROWN-ZIR", "tooth_numbers": [27], "status": "performed"},
                expect=(201,), label="/odonto acte catalogue Couronne zircone 27") or {}
check(_c1.get("clinical_type") == "crown" and _c1.get("catalog_label") == "Couronne zircone", "acte catalogue : type crown + libelle")
json_call("POST", "/odonto/1/treatments", {"catalog_code": "NOPE-1", "tooth_numbers": [27]}, expect=(400,), label="/odonto code inconnu (400)")
json_call("POST", "/odonto/1/treatments", {"catalog_code": "REST-CROWN-ZIR", "clinical_type": "bridge", "tooth_numbers": [27]},
          expect=(400,), label="/odonto code/type incompatibles (400)")
json_call("POST", "/odonto/1/treatments", {"catalog_code": "REST-SPLINT-OCC", "status": "planned"}, expect=(400,), label="/odonto arcade manquante (400)")
_g1 = json_call("POST", "/odonto/1/treatments", {"catalog_code": "REST-SPLINT-OCC", "arch": "upper", "status": "planned"},
                expect=(201,), label="/odonto gouttiere d'occlusion arcade sup.") or {}
check(_g1.get("scope") == "global_arch" and _g1.get("arch") == "upper" and _g1.get("teeth") == [], "traitement global : scope/arch, sans dent")
_b1 = json_call("POST", "/odonto/1/treatments", {"catalog_code": "REST-BRIDGE-MARY", "status": "planned", "tooth_numbers": [21, 22, 23]},
                expect=(201,), label="/odonto Pont du Maryland 21-23") or {}
check(_b1.get("clinical_type") == "bridge" and [x.get("role") for x in _b1.get("teeth", [])] == ["pillar", "pontic", "pillar"], "pont catalogue : roles auto")
_all = json_call("GET", "/odonto/1") or {}
check(any(t.get("id") == _g1.get("id") for t in _all.get("treatments", [])), "traitement global renvoye par GET /odonto")
json_call("DELETE", f"/odonto/1/treatments/{_g1.get('id')}", expect=(204,), label="/odonto delete traitement global")
json_call("DELETE", f"/odonto/1/treatments/{_b1.get('id')}", expect=(204,), label="/odonto delete pont Maryland")

# Miroir legacy : les consultations / le PDF patient lisent toujours dental_teeth.
import sqlite3  # noqa: E402
_con = sqlite3.connect(_TMP_DB)
_rows = dict(_con.execute("SELECT tooth_number, condition FROM dental_teeth").fetchall())
_mirror = _con.execute("SELECT treatment_type FROM dental_treatments WHERE tooth_number = 27 AND odo_treatment_id = ?", (_c1.get("id"),)).fetchone()
_con.close()
check(_rows.get(36) == "obturation", "miroir legacy : dent 36 = obturation")
check(_rows.get(16) == "sain", "miroir legacy : dent 16 revenue a sain apres suppression")
check(_rows.get(27) == "couronne", "miroir legacy : dent 27 = couronne (acte catalogue)")
check(bool(_mirror) and _mirror[0] == "Couronne zircone", "miroir legacy : dental_treatments porte le libelle de l'acte")
get("/patients/1/brochure.pdf", label="/patients/1/brochure.pdf (etat bucco-dentaire)")

print("== Parodontogramme ==")
_d = json_call("POST", "/perio/1/draft") or {}
_sid = _d.get("id")
check(len(_d.get("teeth", [])) == 32, "brouillon : 32 dents permanentes")
json_call("PATCH", f"/perio/1/snapshots/{_sid}/teeth/16", {"mobility": 2, "prognosis": "fair"}, label="/perio tooth 16")
json_call("PATCH", f"/perio/1/snapshots/{_sid}/teeth/16/sites/MV", {"probing_depth_mm": 6, "bleeding_on_probing": True}, label="/perio site 16 MV")
json_call("PATCH", f"/perio/1/snapshots/{_sid}/teeth/16/sites/MV", {"probing_depth_mm": 99}, expect=(422,), label="/perio site hors plage (422)")
_ind = json_call("GET", f"/perio/1/snapshots/{_sid}/indices") or {}
check(_ind.get("deep_pockets_count") == 1, "indices : 1 poche >= 5 mm")
_closed = json_call("POST", f"/perio/1/snapshots/{_sid}/close", {}) or {}
check(_closed.get("status") == "closed", "session cloturee")
json_call("PATCH", f"/perio/1/snapshots/{_sid}/teeth/16", {"mobility": 1}, expect=(409,), label="/perio modif apres cloture (409)")
json_call("DELETE", f"/perio/1/snapshots/{_sid}", expect=(409,), label="/perio suppression session close (409)")
_tl = json_call("GET", "/perio/1/timeline") or {}
check(len(_tl.get("dates", [])) == 1 and _tl.get("draft") is None, "timeline : 1 date, pas de brouillon")
_d2 = json_call("POST", "/perio/1/draft") or {}
json_call("DELETE", f"/perio/1/snapshots/{_d2.get('id')}", expect=(204,), label="/perio abandon brouillon")

print("== Pages odontogramme / parodontogramme ==")
# Le jeton pose par /setup ne porte pas la specialite : on se reconnecte pour
# obtenir la vue dentiste (onglets Odontogramme / Endodontie).
post("/login", {"email": "admin@smoke.test", "password": "Password123!"}, label="/login (vue dentiste)")
_r = get("/patients/1?tab=odontogram", label="/patients/1?tab=odontogram")
for _needle, _label in (('id="odonto-root"', "racine odontogramme"), ('id="perio-root"', "racine parodontogramme"),
                        ("Parodontogramme", "slider Parodontogramme"), ("/static/js/odonto/index.js", "module odonto")):
    check(_needle in _r.text, f"fiche patient : {_label}")
_r = get("/dental/1", label="/dental/1")
for _needle, _label in (('id="btn-perio"', "bouton Parodontogramme"), ('id="btn-endo"', "bouton Endodontie"), ('id="perio-root"', "racine parodontogramme")):
    check(_needle in _r.text, f"/dental : {_label}")
get("/static/js/odonto/index.js", expect=(200,), label="/static/js/odonto/index.js")
get("/static/css/odonto.css", expect=(200,), label="/static/css/odonto.css")

print("== Rappels (item 31) ==")
post("/rappels/new", {"patient_id": "1", "description": "Détartrage", "due_date": "2026-09-01"})
post("/rappels/1/status", {"status": "contacte"})
post("/rappels/1/close")

print("== Messages (item 4) ==")
get("/messages/")
get("/messages/api/unread-count", label="/messages/api/unread-count")

print("== Salle d'attente ==")
get("/salle-attente/")
get("/salle-attente/api/board", label="/salle-attente/api/board")
get("/salle-attente/api/count", label="/salle-attente/api/count")
# RDV du jour -> pointage d'arrivee -> appel -> fin de passage
from datetime import date as _date  # noqa: E402
_today = _date.today().isoformat()
post("/appointments/new", {"patient_id": "1", "doctor_id": "1", "title": "RDV du jour",
                           "appointment_type": "consultation", "status": "planifie",
                           "start_datetime": f"{_today}T10:00", "end_datetime": f"{_today}T10:30"},
     label="/appointments/new (aujourd'hui)")
_r = post("/salle-attente/checkin", {"appointment_id": "2"}, expect=(200,))
_entry = (_r.json() or {}).get("id", 1)
post(f"/salle-attente/{_entry}/priority", {}, expect=(200,), label="/salle-attente/{id}/priority")
post(f"/salle-attente/{_entry}/move", {"direction": "down"}, expect=(200,), label="/salle-attente/{id}/move")
post(f"/salle-attente/{_entry}/call", {"room": "Salle 1"}, expect=(200,), label="/salle-attente/{id}/call")
post(f"/salle-attente/{_entry}/status", {"status": "termine"}, expect=(200,), label="/salle-attente/{id}/status")
# Creation d'une fiche patient au comptoir, puis rattachement d'une fiche a un
# patient arrive sous un simple nom (ce qui debloque « Consulter »).
post("/salle-attente/patients", {"first_name": "Sara", "last_name": "Idrissi",
                                 "date_of_birth": "1992-05-04", "gender": "F",
                                 "phone": "0600000000", "reason": "Controle"},
     expect=(200,), label="/salle-attente/patients (creation + file)")
post("/salle-attente/patients", {"first_name": "", "last_name": "X",
                                 "date_of_birth": "1990-01-01"},
     expect=(400,), label="/salle-attente/patients (champs manquants -> 400)")
_r = post("/salle-attente/checkin", {"name": "Karim Sans Dossier"}, expect=(200,),
          label="/salle-attente/checkin (nom libre)")
_walkin = (_r.json() or {}).get("id", 0)
post(f"/salle-attente/{_walkin}/call", {"room": "Salle 2"}, expect=(200,),
     label="/salle-attente/{id}/call (sans dossier)")
post("/salle-attente/patients", {"entry_id": str(_walkin), "first_name": "Karim",
                                 "last_name": "Sans Dossier", "date_of_birth": "1980-03-03"},
     expect=(200,), label="/salle-attente/patients (rattachement)")
post("/salle-attente/patients", {"entry_id": str(_walkin), "first_name": "Karim",
                                 "last_name": "Sans Dossier", "date_of_birth": "1980-03-03"},
     expect=(409,), label="/salle-attente/patients (deja rattache -> 409)")

post("/salle-attente/reglages", {"name_mode": "initial", "clinic_name": "Cabinet test",
                                 "show_times": "1", "sound_enabled": "1",
                                 "auto_checkin_on_confirm": "1", "call_banner_seconds": "20",
                                 "ticker": "Bienvenue",
                                 "music_enabled": "1", "music_volume": "30",
                                 "music_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
     expect=(200,))
post("/salle-attente/reglages", {"name_mode": "initial", "music_enabled": "1",
                                 "music_url": "https://vimeo.com/1"},
     expect=(400,), label="/salle-attente/reglages (lien non YouTube -> 400)")
_r = post("/salle-attente/reglages/token", {}, expect=(200,))
_screen = (_r.json() or {}).get("screen_url", "")
get(_screen, expect=(200,), label="/salle-attente/ecran/{token}")
get("/salle-attente/api/ecran/" + _screen.rsplit("/", 1)[-1], expect=(200,), label="/salle-attente/api/ecran/{token}")
get("/salle-attente/ecran/jeton-invalide", expect=(404,), label="/salle-attente/ecran/{jeton invalide}")

print("== Mon compte ==")
get("/mon-compte")
post("/mon-compte", {"first_name": "Smoke", "last_name": "Admin",
                     "email": "admin@smoke.test", "phone": "0522000000",
                     "address": "12 rue des Écoles, Casablanca", "specialty": "Dentiste"})
# L'e-mail de l'admin principal est figé par la configuration : toute autre
# adresse doit être refusée (200 = formulaire re-rendu avec l'erreur).
_r = post("/mon-compte", {"first_name": "Smoke", "last_name": "Admin",
                          "email": "pirate@example.com", "specialty": "Dentiste"},
          expect=(200,), label="/mon-compte (e-mail admin verrouillé)")
if "configuration" not in _r.text:
    print("  XX  changement d'e-mail admin non refusé")
    failures.append("/mon-compte : e-mail admin modifiable")
else:
    print("  OK  changement d'e-mail admin refusé")
# Le bouton ouvre DIRECTEMENT le lien magique : 303 vers /reset-password/{jeton}.
_r = post("/mon-compte/mot-de-passe", {}, expect=(303,))
_loc = _r.headers.get("location", "")
if not _loc.startswith("/reset-password/"):
    print("  XX  le bouton ne redirige pas vers la page de mot de passe")
    failures.append("/mon-compte/mot-de-passe : redirection " + _loc)
else:
    print("  OK  ouverture directe du lien de mot de passe")
    get(_loc, expect=(200,), label="/reset-password/{jeton}")
    _r = post(_loc, {"password": "NouveauPass123!", "password_confirm": "NouveauPass123!"},
              expect=(200,), label="/reset-password/{jeton} (enregistrement)")
    if "Mot de passe modifi" not in _r.text:
        print("  XX  pas de page de confirmation")
        failures.append("/reset-password : pas de confirmation")
    else:
        print("  OK  page de confirmation (fermer la fenetre / revenir a Doctivo)")
get("/mon-compte/papier-en-tete", expect=(404,), label="/mon-compte/papier-en-tete (aucun)")

print("== CSRF négatif (POST sans jeton -> 403) ==")
r = client.post("/rappels/new", data={"patient_id": "1", "description": "x"}, follow_redirects=False)
if r.status_code == 403:
    print("  OK  POST sans CSRF -> 403")
else:
    print(f"  XX  POST sans CSRF -> {r.status_code} (attendu 403)")
    failures.append(f"CSRF négatif -> {r.status_code}")

print("\n" + ("=" * 50))
if failures:
    print(f"ÉCHECS ({len(failures)}) :")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("Tous les endpoints testés OK (aucun 500).")
