"""Tests ciblés de re-audit v3 (lecture seule sur le dépôt, base temporaire).
Chaque test imprime PASS/FAIL + une note. Un FAIL = le constat/la faille est confirmé(e)
ou une régression existe ; on lit le libellé pour savoir dans quel sens.
"""
import os, sys, tempfile, re, sqlite3

APP = r"c:\Users\abdel\Documents\PlatformIO\Projects\Learn CC\medfollow"
_TMP_DB = os.path.join(tempfile.gettempdir(), "medfollow_audit_v3.db")
for suffix in ("", "-wal", "-shm"):
    try: os.remove(_TMP_DB + suffix)
    except OSError: pass
os.environ["MEDFOLLOW_DATABASE_PATH"] = _TMP_DB
os.environ["MEDFOLLOW_ADMIN_EMAIL"] = "admin@audit.test"
os.chdir(APP)
sys.path.insert(0, APP)

from fastapi.testclient import TestClient  # noqa
from main import app  # noqa

results = []
def report(name, ok, note=""):
    results.append((name, ok, note))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {('— ' + note) if note else ''}")

def mk():
    return TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

def csrf(c):
    c.get("/login")
    return c.cookies.get("csrf_token", "")

def post(c, path, data=None, files=None, json=None, headers=None):
    t = csrf(c)
    h = {"X-CSRF-Token": t}
    if headers: h.update(headers)
    if json is not None:
        return c.post(path, json=json, headers=h, follow_redirects=False)
    d = dict(data or {}); d["csrf_token"] = t
    return c.post(path, data=d, files=files, headers=h, follow_redirects=False)

def login(c, email, pw):
    return post(c, "/login", {"email": email, "password": pw})

ctx = TestClient(app, raise_server_exceptions=False); admin = ctx.__enter__()

# ---------- Setup admin (dentiste) ----------
post(admin, "/setup", {"email": "admin@audit.test", "password": "Password123!", "password_confirm": "Password123!",
                       "first_name": "Ad", "last_name": "Min", "specialty": "Dentiste"})
r = admin.get("/", follow_redirects=False)
report("setup admin + login", r.status_code == 200, f"GET / -> {r.status_code}")

# Create doctor B and secretary S (linked to admin=1)
r = post(admin, "/admin/users/new", {"email": "docb@audit.test", "password": "Password123!", "password_confirm": "Password123!",
                                     "first_name": "Doc", "last_name": "B", "role": "medecin", "specialty": "Dentiste"})
r2 = post(admin, "/admin/users/new", {"email": "sec@audit.test", "password": "Password123!", "password_confirm": "Password123!",
                                      "first_name": "Sec", "last_name": "S", "role": "secretaire", "linked_doctor_id": "1"})
report("création médecin B + secrétaire S", r.status_code in (302, 303) and r2.status_code in (302, 303), f"{r.status_code}/{r2.status_code}")

# Admin creates a patient, consultation, prescription, invoice, appointment, dental treatment
post(admin, "/patients/quick", {"first_name": "Jean", "last_name": "Test", "date_of_birth": "1990-01-01", "gender": "M"})
post(admin, "/consultations/new", {"patient_id": "1", "doctor_id": "1", "consultation_date": "2026-02-10", "reason": "Controle"})
post(admin, "/prescriptions/new", {"patient_id": "1", "doctor_id": "1", "notes": "", "med_name_0": "Amoxicilline", "med_dosage_0": "1g", "med_frequency_0": "2x/j", "med_duration_0": "7 jours", "med_quantity_0": "1"})
post(admin, "/invoices/new", {"patient_id": "1", "doctor_id": "1", "notes": "", "item_desc_0": "Consultation", "item_qty_0": "1", "item_price_0": "300"})
post(admin, "/appointments/new", {"patient_id": "1", "doctor_id": "1", "title": "RDV", "appointment_type": "consultation", "status": "planifie", "start_datetime": "2026-03-01T09:00", "end_datetime": "2026-03-01T09:30"})

# ---------- T1: RBAC admin ----------
docb = mk(); login(docb, "docb@audit.test", "Password123!")
r = docb.get("/admin/users", follow_redirects=False)
report("T1 RBAC: médecin -> /admin/users refusé", r.status_code == 403, f"-> {r.status_code}")
r = post(docb, "/admin/users/1/reset-password-link")
report("T1 RBAC: médecin -> reset-link admin refusé", r.status_code == 403, f"-> {r.status_code}")

# ---------- T2: IDOR cross-doctor ----------
codes = {}
for p in ["/patients/1", "/consultations/1", "/prescriptions/1", "/prescriptions/1/pdf", "/invoices/1", "/invoices/1/pdf", "/dental/1", "/patients/1/brochure.pdf"]:
    r = docb.get(p, follow_redirects=False)
    codes[p] = r.status_code
ok = all(v in (302, 303, 403, 404) for v in codes.values())
report("T2 IDOR: médecin B ne voit rien du médecin A", ok, str(codes))
r = post(docb, "/invoices/1/pay", {"amount": "300", "payment_method": "especes", "reference": ""})
report("T2 IDOR: B ne peut pas encaisser la facture de A", r.status_code in (302, 303, 403, 404), f"-> {r.status_code}")
r = post(docb, "/appointments/1/status", {"status": "annule"})
report("T2 IDOR: B ne peut pas changer le statut RDV de A", r.status_code in (302, 303, 403, 404), f"-> {r.status_code}")

# ---------- T3: secrétaire ----------
sec = mk(); login(sec, "sec@audit.test", "Password123!")
r = sec.get("/consultations/", follow_redirects=False)
r2 = sec.get("/appointments/api/events?start=2026-01-01&end=2026-12-31", follow_redirects=False)
r3 = sec.get("/patients/", follow_redirects=False)
r4 = sec.get("/patients/1", follow_redirects=False)
r5 = sec.get("/invoices/factures", follow_redirects=False)
report("T3 secrétaire: clinique interdit (consultations 403)", r.status_code == 403, f"-> {r.status_code}")
report("T3 secrétaire: agenda du médecin lié visible", r2.status_code == 200 and "Jean" in r2.text, f"-> {r2.status_code}")
report("T3 secrétaire: liste patients visible / fiche interdite", r3.status_code == 200 and r4.status_code == 403, f"{r3.status_code}/{r4.status_code}")
report("T3 secrétaire: facturation interdite", r5.status_code == 403, f"-> {r5.status_code}")

# ---------- T4: Escalade via invitation role=admin ----------
r = post(admin, "/admin/invite", {"role": "admin", "email": "", "specialty": ""})
m = re.search(r"/register/([A-Za-z0-9_\-]+)", r.text)
tok = m.group(1) if m else None
esc_ok = None
if tok:
    evil = mk()
    r = post(evil, f"/register/{tok}", {"email": "evil@x.test", "password": "Password123!", "password_confirm": "Password123!", "first_name": "E", "last_name": "V", "specialty": ""})
    r2 = evil.get("/admin/users", follow_redirects=False)
    esc_ok = r2.status_code == 200
report("T4 escalade: invitation role=admin crée un admin (faille si FAIL)", esc_ok is False, f"register->{r.status_code}, /admin/users->{r2.status_code if tok else 'n/a'}")

# ---------- T5: invitation avec email liée — un tiers peut la consommer ? ----------
r = post(admin, "/admin/invite", {"role": "medecin", "email": "cible@x.test", "specialty": ""})
m = re.search(r"/register/([A-Za-z0-9_\-]+)", r.text); tok = m.group(1) if m else None
other = mk()
r = post(other, f"/register/{tok}", {"email": "autre@x.test", "password": "Password123!", "password_confirm": "Password123!", "first_name": "A", "last_name": "B", "specialty": ""})
report("T5 invitation: email non lié serveur (faille si FAIL)", r.status_code not in (302, 303), f"register avec autre email -> {r.status_code}")

# ---------- T6: suppression RDV avec acte dentaire lié (IntegrityError latent ?) ----------
r = post(admin, "/dental/1/tooth/26/treatment", {"treatment_type": "extraction", "description": "", "treatment_date": "2026-04-01", "start_time": "10:00"})
con = sqlite3.connect(_TMP_DB); cur = con.execute("SELECT id, appointment_id FROM dental_treatments ORDER BY id DESC LIMIT 1"); row = cur.fetchone(); con.close()
apt_id = row[1] if row else None
r = post(admin, f"/appointments/{apt_id}/delete") if apt_id else None
report("T6 suppression RDV lié à un acte dentaire (bug v2 si FAIL)", bool(r) and r.status_code in (302, 303), f"treatment appt={apt_id} -> delete {r.status_code if r else 'n/a'}")

# ---------- T7: /docs exposé ----------
anon = mk()
r = anon.get("/openapi.json"); r2 = anon.get("/docs")
report("T7 /openapi.json & /docs non exposés (exposé si FAIL)", r.status_code == 404 and r2.status_code == 404, f"{r.status_code}/{r2.status_code}")

# ---------- T8: Cache-Control & gzip statiques ----------
r = admin.get("/static/css/style.css", headers={"Accept-Encoding": "gzip"})
cc = r.headers.get("cache-control"); ce = r.headers.get("content-encoding")
report("T8 Cache-Control sur /static (absent si FAIL)", bool(cc), f"cache-control={cc}, content-encoding={ce}")

# ---------- T9: en-têtes sécurité ----------
r = admin.get("/", follow_redirects=False)
h = {k: r.headers.get(k) for k in ["content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy", "strict-transport-security"]}
report("T9 en-têtes CSP/XFO/nosniff/Referrer présents", all(h[k] for k in list(h)[:4]), f"HSTS={h['strict-transport-security']} (HTTPS_ENABLED=0 attendu None)")
report("T9 CSP sans 'unsafe-inline' script (dette si FAIL)", "'unsafe-inline'" not in (h["content-security-policy"] or "").split("script-src")[1].split(";")[0], "")

# ---------- T10: CSRF ----------
r = admin.post("/patients/quick", data={"first_name": "X", "last_name": "Y", "date_of_birth": "1990-01-01", "gender": "M"}, follow_redirects=False)
report("T10 CSRF: POST sans jeton -> 403", r.status_code == 403, f"-> {r.status_code}")

# ---------- T11: révocation de session (désactivation) ----------
docb2 = mk(); login(docb2, "docb@audit.test", "Password123!")
tokcookie = docb2.cookies.get("access_token")
post(admin, "/admin/users/2/toggle-active")
r = docb2.get("/", follow_redirects=False)
report("T11 compte désactivé: jeton vivant toujours accepté (faille si FAIL)", r.status_code in (302, 401, 403), f"GET / après désactivation -> {r.status_code}")
post(admin, "/admin/users/2/toggle-active")  # re-activate
# logout then reuse cookie
docb3 = mk(); login(docb3, "docb@audit.test", "Password123!"); saved = docb3.cookies.get("access_token")
docb3.get("/logout", follow_redirects=False)
reuse = mk(); reuse.cookies.set("access_token", saved)
r = reuse.get("/", follow_redirects=False)
report("T11 logout: cookie copié rejeté après logout (faille si FAIL)", r.status_code != 200, f"-> {r.status_code}")

# ---------- T12: auto-désactivation admin / dernier admin ----------
r = post(admin, "/admin/users/1/toggle-active")
r2 = admin.get("/admin/users", follow_redirects=False)
con = sqlite3.connect(_TMP_DB); active = con.execute("SELECT is_active FROM users WHERE id=1").fetchone()[0]; con.close()
if active == 0:
    con = sqlite3.connect(_TMP_DB); con.execute("UPDATE users SET is_active=1 WHERE id=1"); con.commit(); con.close()
report("T12 garde-fou auto-désactivation du dernier admin (absent si FAIL)", active == 1, f"is_active admin après toggle sur soi-même = {active}")

# ---------- T13: XSS stocké via json|safe (</script> dans un nom patient) ----------
post(admin, "/patients/quick", {"first_name": "Evil", "last_name": "</script><img src=x onerror=alert(1)>", "date_of_birth": "1990-01-01", "gender": "M"})
r = admin.get("/mutuelle/", follow_redirects=False)
raw = "</script><img src=x onerror=alert(1)>" in r.text
report("T13 XSS: '</script>' brut injecté dans <script> (mutuelle) (faille si FAIL)", not raw, f"mutuelle -> {r.status_code}, brut={raw}")
r = admin.get("/invoices/devis/new", follow_redirects=False)
report("T13 XSS: devis_form n'injecte pas de '</script>' brut", "</script><img src=x" not in r.text, f"-> {r.status_code}")
r = admin.get("/patients/2", follow_redirects=False)
report("T13 XSS: fiche patient (teeth_data_json) sans '</script>' brut", "</script><img src=x" not in r.text, f"-> {r.status_code}")

# ---------- T14: document uploadé avec Content-Type text/html servi inline en HTML ----------
html = b"<html><script>alert('xss')</script></html>"
r = post(admin, "/documents/upload", data={"patient_id": "1", "category": "autre", "title": "x", "description": ""},
         files={"files": ("x.png", html, "text/html")})
con = sqlite3.connect(_TMP_DB); row = con.execute("SELECT id, file_type FROM documents ORDER BY id DESC LIMIT 1").fetchone(); con.close()
if row:
    r2 = admin.get(f"/documents/{row[0]}/view", follow_redirects=False)
    ct = r2.headers.get("content-type", ""); csp = r2.headers.get("content-security-policy", "")
    report("T14 upload x.png avec Content-Type text/html servi en HTML (faille si FAIL)", "text/html" not in ct, f"upload->{r.status_code}, file_type en base={row[1]}, view content-type={ct}")
    report("T14 /view remplace la CSP globale (script-src perdu si FAIL)", "script-src" in csp, f"CSP={csp[:60]}")
else:
    report("T14 upload document", False, f"upload -> {r.status_code}, aucun document en base (magic-bytes ?)")

# ---------- T15: feuille de soins HTML brut servi tel quel ----------
r = post(admin, "/mutuelle/feuille/save", json={"patient_id": 1, "mutuelle": "CNSS", "type_feuille": "soins", "nom_beneficiaire": "Jean", "actes": [], "html_content": "<html><script>alert('x')</script></html>", "total_montant": 0})
fid = None
try: fid = r.json().get("id") or r.json().get("feuille_id")
except Exception: pass
if fid is None:
    con = sqlite3.connect(_TMP_DB); rr = con.execute("SELECT id FROM feuilles_soin ORDER BY id DESC LIMIT 1").fetchone(); con.close(); fid = rr[0] if rr else None
r2 = admin.get(f"/mutuelle/feuille/{fid}/view") if fid else None
report("T15 feuille: HTML client persisté et servi brut (self-XSS/gadget si FAIL)", bool(r2) and "<script>alert('x')" not in r2.text, f"save->{r.status_code}, view->{r2.status_code if r2 else 'n/a'}")

# ---------- T16: open redirect next_url ----------
r = post(admin, "/patients/new", {"first_name": "Red", "last_name": "Ir", "date_of_birth": "1990-01-01", "gender": "M", "id_type": "cin", "next_url": "https://evil.example/phish"})
loc = r.headers.get("location", "")
report("T16 open redirect via next_url (faille si FAIL)", not loc.startswith("https://evil.example"), f"-> {r.status_code} Location={loc}")

# ---------- T17: rate limiting login + contournement X-Forwarded-For ----------
rl = mk()
codes = []
for i in range(7):
    r = post(rl, "/login", {"email": "docb@audit.test", "password": "wrong"}); codes.append(r.status_code)
report("T17 rate-limit: 6e tentative échouée -> 429", 429 in codes, str(codes))
rl2 = mk(); codes2 = []
for i in range(25):
    r = post(rl2, "/login", {"email": f"u{i}@x.test", "password": "wrong"}, headers={"X-Forwarded-For": f"10.0.0.{i}"}); codes2.append(r.status_code)
report("T17 rate-limit IP contournable via X-Forwarded-For (faille si FAIL)", 429 in codes2, f"25 tentatives IP spoofées, 429 vu: {429 in codes2}")

# ---------- T18: écran salle d'attente public : noms complets si name_mode=full ----------
post(admin, "/appointments/new", {"patient_id": "1", "doctor_id": "1", "title": "RDV", "appointment_type": "consultation", "status": "planifie", "start_datetime": __import__('datetime').date.today().isoformat() + "T15:00", "end_datetime": __import__('datetime').date.today().isoformat() + "T15:30"})
con = sqlite3.connect(_TMP_DB); aid = con.execute("SELECT id FROM appointments ORDER BY id DESC LIMIT 1").fetchone()[0]; con.close()
post(admin, "/salle-attente/checkin", {"appointment_id": str(aid)})
r = post(admin, "/salle-attente/reglages", {"name_mode": "full", "clinic_name": "Cab", "show_times": "1", "sound_enabled": "1", "auto_checkin_on_confirm": "1", "call_banner_seconds": "20", "ticker": ""})
url = r.json().get("screen_url") if r.status_code == 200 else None
r2 = anon.get(url + "?x=1" if url else "/salle-attente/ecran/none")
report("T18 écran TV public: nom complet du patient exposé avec name_mode=full (à noter si FAIL)", "TEST" not in r2.text.upper() or "Jean" not in r2.text, f"{url} -> {r2.status_code}")
r3 = anon.get("/salle-attente/api/ecran/invalidtoken")
report("T18 écran TV: jeton invalide -> 404", r3.status_code == 404, f"-> {r3.status_code}")

# ---------- T19: numérotation factures/devis ----------
con = sqlite3.connect(_TMP_DB)
idx = con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%'").fetchall()
uniq = con.execute("SELECT sql FROM sqlite_master WHERE name='devis'").fetchone()[0]
fk = con.execute("PRAGMA foreign_key_check").fetchall()
uv = con.execute("PRAGMA user_version").fetchone()[0]
con.close()
report("T19 index explicites en base", len(idx) > 0, f"{[i[0] for i in idx]}")
report("T19 devis UNIQUE(doctor_id, devis_number)", "doctor_id, devis_number" in uniq.replace("\n", " ") or "doctor_id,devis_number" in uniq, "")
report("T19 PRAGMA user_version (0 = pas de versioning)", uv > 0, f"user_version={uv}")
report("T19 foreign_key_check propre", len(fk) == 0, str(fk[:3]))

# ---------- T20: reset token stocké en clair ----------
r = post(admin, "/admin/users/2/reset-password-link")
m = re.search(r"/reset-password/([A-Za-z0-9_\-]+)", r.text); tok = m.group(1) if m else None
con = sqlite3.connect(_TMP_DB); row = con.execute("SELECT token FROM password_resets ORDER BY id DESC LIMIT 1").fetchone(); con.close()
report("T20 jeton de reset stocké en clair en base (à noter si FAIL)", not (tok and row and row[0] == tok), "")

# ---------- T21: patients/detail role=tab ; focus-visible ----------
r = admin.get("/patients/1")
report("T21 fiche patient: onglets avec role=tab/aria-selected", 'role="tab"' in r.text and "aria-selected" in r.text, "")

# ---------- T22: ordonnance édition: garde serveur statut ----------
# (no status route exists, informational)

# ---------- T23: 2e connexion middleware — check active consultation banner path works ----------
r = post(admin, "/consultations/start", {"patient_id": "1"})
r2 = admin.get("/patients/", follow_redirects=False)
report("T23 bandeau consultation en cours rendu", "Retour" in r2.text or "consultation" in r2.text.lower(), f"start->{r.status_code}")

# ---------- T24: str(e) brut renvoyé (patient CIN dupliqué -> message dédié) ----------
r = post(admin, "/patients/new", {"first_name": "Dup", "last_name": "One", "date_of_birth": "1990-01-01", "gender": "M", "id_type": "cin", "social_security_number": "AB1234"})
r2 = post(admin, "/patients/new", {"first_name": "Dup", "last_name": "Two", "date_of_birth": "1990-01-01", "gender": "M", "id_type": "cin", "social_security_number": "AB1234"})
report("T24 doublon CIN -> message dédié (200 avec erreur)", r2.status_code == 200 and "existe déjà" in r2.text, f"{r.status_code}/{r2.status_code}")

# ---------- T25: Mon compte: changement email vers un email existant ----------
r = post(docb, "/mon-compte", {"first_name": "Doc", "last_name": "B", "email": "admin@audit.test", "phone": "", "address": "", "specialty": "Dentiste"})
report("T25 Mon compte: usurpation d'email existant refusée", r.status_code == 200 and ("déjà" in r.text or "existe" in r.text), f"-> {r.status_code}")

# ---------- T26: health + 404 page brandée ----------
r = anon.get("/health"); r2 = admin.get("/nope-404")
report("T26 /health + page 404 brandée", r.status_code == 200 and r2.status_code == 404 and "Doctivo" in r2.text, f"{r.status_code}/{r2.status_code}")

# ---------- T27: WhatsApp webhook sans signature ignoré ----------
r = anon.post("/webhooks/whatsapp", json={"entry": []})
report("T27 webhook WhatsApp non signé rejeté/ignoré", r.status_code in (401, 403, 200, 404), f"-> {r.status_code}")

print("\n==== RÉSUMÉ ====")
for n, ok, note in results:
    if not ok: print(f"FAIL  {n}  {note}")
print(f"{sum(1 for _,ok,_ in results if ok)}/{len(results)} PASS")
ctx.__exit__(None, None, None)
