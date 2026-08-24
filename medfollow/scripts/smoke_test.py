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
post("/salle-attente/reglages", {"name_mode": "initial", "clinic_name": "Cabinet test",
                                 "show_times": "1", "sound_enabled": "1",
                                 "auto_checkin_on_confirm": "1", "call_banner_seconds": "20",
                                 "ticker": "Bienvenue"}, expect=(200,))
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
