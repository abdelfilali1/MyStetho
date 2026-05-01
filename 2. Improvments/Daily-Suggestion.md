# Doctivo — Daily Suggestions

---

## 2026-04-25

Source: Audit statique du codebase (Chrome non disponible — le serveur local répond bien sur http://localhost:8000 mais l'extension Chrome MCP est déconnectée). Focus sur les modules ajoutés/modifiés depuis le 2026-04-24 : `routers/dental.py`, `routers/prescriptions.py`, et nouvelles routes drag-drop d'agenda. Les BUG-11/12/13/14 et UX-12 à UX-18 du 2026-04-24 restent ouverts — non re-listés ici.

---

### BUGS IDENTIFIÉS

**BUG-15 — Pas de vérification d'ownership sur view/edit/PDF d'ordonnance (Sécurité Majeure)**
`routers/prescriptions.py` lignes 179, 205, 235, 285–293 — Les routes `view_prescription`, `prescription_pdf`, `edit_prescription_form` et `update_prescription` récupèrent l'ordonnance par `id` seul, sans filtrer par `doctor_id`. Un utilisateur authentifié peut lire, télécharger en PDF et modifier les ordonnances de tout autre praticien.
Claude Code Prompt:
```
In medfollow/routers/prescriptions.py:
1. In view_prescription() (GET /{prescription_id}), change the SELECT to:
     ... WHERE pr.id = ? AND pr.doctor_id = ?
   Add user["sub"] as parameter.
2. In prescription_pdf() (GET /{prescription_id}/pdf), apply the same WHERE filter.
3. In edit_prescription_form() (GET /{prescription_id}/edit), change:
     "SELECT pr.* FROM prescriptions pr WHERE pr.id = ?"
   To:
     "SELECT pr.* FROM prescriptions pr WHERE pr.id = ? AND pr.doctor_id = ?"
   Pass (prescription_id, user["sub"]). If not found, redirect to /prescriptions.
4. In update_prescription() (POST /{prescription_id}/edit), change the UPDATE to also filter:
     ... WHERE id = ? AND doctor_id = ?
   Pass user["sub"] at the end of the params tuple. Same for the DELETE on prescription_items —
   first verify ownership before deleting items.
```

**BUG-16 — Endpoints odontogramme sans vérification d'ownership patient (Sécurité Majeure)**
`routers/dental.py` lignes 93–145, 154–173, 183–243, 246–290, 294–412 — Seul `dental_chart` (ligne 59) vérifie que `patients.doctor_id = user.sub`. Tous les autres endpoints (`/tooth/{n}/data`, `/tooth/{n}/condition`, `/tooth/{n}/condition-history`, `/tooth/{n}/treatment`, `/tooth/{n}/treatment/{id}/delete`, `/bulk-treatment`, `/endo/{n}`, `/endo/{n}/save`, `/endo/history/{id}/correct`) reçoivent `patient_id` en paramètre sans valider l'ownership. Conséquence : un utilisateur authentifié peut lire et **modifier** l'historique dentaire et endo de tout patient du système — y compris créer des RDV/traitements falsifiés au nom d'un autre praticien.
Claude Code Prompt:
```
In medfollow/routers/dental.py, add a helper at the top of the file:
  async def _verify_patient_ownership(db, patient_id: int, doctor_id: int) -> bool:
      cursor = await db.execute(
          "SELECT 1 FROM patients WHERE id = ? AND doctor_id = ?",
          (patient_id, doctor_id)
      )
      return await cursor.fetchone() is not None

Then at the start of every route that takes patient_id (ALL routes except dental_chart
which already does this inline), after get_current_user(), insert:
  if not await _verify_patient_ownership(db, patient_id, user["sub"]):
      return JSONResponse(status_code=403, content={"error": "Accès refusé"})

Routes to update: get_tooth_data, save_tooth_condition, get_tooth_condition_history,
record_treatment, delete_treatment, bulk_treatment, get_endo_data, save_endo_data,
correct_endo_history (and any other route taking patient_id).

For routes that return HTML rather than JSON, redirect to /patients instead of 403 JSON.
```

**BUG-17 — `doctor_id` ordonnance accepté depuis le formulaire (Sécurité Moyenne)**
`routers/prescriptions.py` lignes 138 et 285 — Dans `create_prescription()` et `update_prescription()`, le code lit `doctor_id = int(form["doctor_id"])` sans vérifier qu'il correspond à `user["sub"]`. Un utilisateur peut créer/modifier une ordonnance au nom d'un autre praticien (similaire à BUG-13 sur les factures).
Claude Code Prompt:
```
In medfollow/routers/prescriptions.py, in both create_prescription() (POST /new)
and update_prescription() (POST /{prescription_id}/edit):
Replace:
  doctor_id = int(form["doctor_id"])
With:
  doctor_id = user["sub"]
The form's doctor_id field is purely cosmetic (display only) — the persisted owner
must always be the authenticated user. Optionally remove the hidden/select doctor_id
input from prescriptions/form.html since multi-doctor prescription writing isn't a
real workflow in this app.
```

**BUG-18 — Pas d'endpoint de suppression d'ordonnance (Fonctionnalité manquante / Mineure)**
`routers/prescriptions.py` — Aucune route DELETE n'existe pour les ordonnances. Si un praticien crée une ordonnance par erreur, il peut seulement l'éditer mais pas la supprimer. Les autres entités (patients, RDV, factures via cancel) ont toutes un mécanisme de retrait.
Claude Code Prompt:
```
In medfollow/routers/prescriptions.py, add:
  @router.post("/{prescription_id}/delete")
  async def delete_prescription(request: Request, prescription_id: int,
                                 db: aiosqlite.Connection = Depends(get_db)):
      user = get_current_user(request)
      if not user: return RedirectResponse("/login", 302)
      cursor = await db.execute(
          "SELECT id FROM prescriptions WHERE id = ? AND doctor_id = ?",
          (prescription_id, user["sub"])
      )
      if not await cursor.fetchone():
          return RedirectResponse("/prescriptions", 302)
      await db.execute("DELETE FROM prescription_items WHERE prescription_id = ?", (prescription_id,))
      await db.execute("DELETE FROM prescriptions WHERE id = ? AND doctor_id = ?",
                       (prescription_id, user["sub"]))
      await db.commit()
      return RedirectResponse("/prescriptions", 302)

In medfollow/templates/prescriptions/detail.html, add a delete button in the action bar:
  <form method="POST" action="/prescriptions/{{ prescription.id }}/delete"
        onsubmit="return confirm('Supprimer cette ordonnance ? Cette action est irréversible.')"
        style="display:inline;">
    <button type="submit" class="btn btn-danger-outline">Supprimer</button>
  </form>
```

---

### PROBLÈMES UX

**UX-19 — Pas de bouton "Nouvelle ordonnance" depuis la consultation (Moyenne)**
`templates/consultations/detail.html` — Lorsqu'un praticien finit une consultation, le workflow naturel est de prescrire un traitement. Or il n'existe aucun lien direct depuis la fiche consultation vers la création d'ordonnance pré-remplie avec le `patient_id` et `consultation_id`. Le praticien doit aller dans Ordonnances > Nouvelle puis re-chercher le patient (même friction que UX-17 sur la fiche patient).
Claude Code Prompt:
```
In medfollow/templates/consultations/detail.html, in the action bar at the top,
add a button:
  <a href="/prescriptions/new?patient_id={{ consultation.pid }}&consultation_id={{ consultation.id }}"
     class="btn btn-primary btn-sm">+ Nouvelle ordonnance</a>

In medfollow/routers/prescriptions.py, in new_prescription_form() (GET /new),
read both patient_id and consultation_id query params and pass them to the template
as selected_patient_id and selected_consultation_id. In templates/prescriptions/form.html,
pre-select the patient option and pre-fill the consultation_id hidden input.
```

**UX-20 — Pas de résumé financier sur la fiche patient (Basse)**
`templates/patients/detail.html`, onglet "Factures" — La fiche patient unifiée montre les 7 onglets mais l'onglet Factures n'affiche qu'une liste brute. Il manque les totaux : CA total avec ce patient, montant payé, et reste dû — informations cruciales avant une nouvelle consultation ou un rappel de paiement.
Claude Code Prompt:
```
In medfollow/routers/patients.py, in patient_detail() (GET /{patient_id}),
after fetching the patient, add:
  cursor = await db.execute(
      "SELECT COALESCE(SUM(total_amount),0), COALESCE(SUM(paid_amount),0) "
      "FROM invoices WHERE patient_id = ? AND doctor_id = ? AND status != 'annulee'",
      (patient_id, user["sub"])
  )
  row = await cursor.fetchone()
  finance = {"ca_total": row[0], "paid_total": row[1], "unpaid_total": row[0] - row[1]}
Pass finance to the template context.

In medfollow/templates/patients/detail.html, in the Factures tab section, above
the invoices list, add:
  <div class="finance-summary" style="display:flex;gap:24px;margin-bottom:16px;
       padding:12px 16px;background:var(--surface-2);border-radius:8px;">
    <div><small>CA total</small><br><strong>{{ finance.ca_total | round(2) }} DH</strong></div>
    <div><small>Payé</small><br><strong>{{ finance.paid_total | round(2) }} DH</strong></div>
    <div><small>Reste dû</small><br>
      <strong style="color:{% if finance.unpaid_total > 0 %}#ef4444{% else %}#059669{% endif %};">
        {{ finance.unpaid_total | round(2) }} DH
      </strong>
    </div>
  </div>
```

**UX-21 — Onglet "Messagerie" sans filtre lu/non lu ni recherche (Basse)**
`templates/messages/list.html` (et la requête dans `routers/messages.py`) — La liste messagerie affiche tous les messages sans filtre par statut (lu/non lu) ni recherche par expéditeur ou objet. Pour un praticien recevant des notifications de RDV, demandes patients, etc., retrouver un message ancien devient pénible.
Claude Code Prompt:
```
In medfollow/routers/messages.py, in inbox() (GET /), add optional query params:
  filter: str = "all"   # 'all' | 'unread' | 'read'
  q: str = ""           # search term

Build the WHERE clause:
  where = "(m.recipient_id = ? OR m.sender_id = ?)"
  params = [user["sub"], user["sub"]]
  if filter == "unread":
      where += " AND m.recipient_id = ? AND m.is_read = 0"
      params.append(user["sub"])
  elif filter == "read":
      where += " AND (m.is_read = 1 OR m.sender_id = ?)"
      params.append(user["sub"])
  if q:
      where += " AND (m.subject LIKE ? OR m.body LIKE ?)"
      params.extend([f"%{q}%", f"%{q}%"])

In medfollow/templates/messages/list.html, add filter pills (Tous / Non lus / Lus)
and a search input above the list. Same pattern as patients/list.html.
```

---

### FONCTIONNALITÉS MANQUANTES (priorité)

1. **Audit ownership systématique** — Pattern récurrent BUG-11→18 : à chaque nouvelle route, l'ownership doctor_id n'est pas vérifié. Envisager un middleware/decorator `@requires_patient_ownership` pour éviter ces oublis. (Critique)
2. **Suppression d'ordonnance** — Fonctionnalité de base manquante (BUG-18) (Moyenne)
3. **Résumé financier patient** — Vue agrégée par patient absente (UX-20) (Basse)
4. **Filtres messagerie** — Tri lu/non lu et recherche absents (UX-21) (Basse)

---

### ÉVALUATION GLOBALE : 7.0 / 10 (en baisse de 0,5)

L'ajout récent du module dentaire (commits b4b992d et 55ec824) a élargi la surface d'attaque sans audit de sécurité : 9 nouveaux endpoints `routers/dental.py` mutent des données patient sans vérifier l'ownership. Combiné aux BUG-11/12/13 toujours ouverts du 2026-04-24, l'app n'est pas prête pour un déploiement multi-praticien. Recommandation : avant tout nouveau ship, dédier 1 sprint à un audit ownership systématique (BUG-11 à BUG-18) avec ajout d'un decorator FastAPI pour rendre l'oubli impossible à l'avenir.

---

## 2026-04-24

Source: Audit statique complet du codebase (Chrome non disponible) — analyse de tous les routers, templates et modèles.

---

### BUGS IDENTIFIÉS

**BUG-11 — Pas de vérification d'ownership sur delete/status d'un RDV (Sécurité Majeure)** validated
`routers/appointments.py` lignes 311–351 — `delete_appointment` supprime par `id` seul sans filtrer par `doctor_id`. Un utilisateur authentifié peut supprimer ou changer le statut de n'importe quel RDV du système.
Claude Code Prompt:
```
In medfollow/routers/appointments.py:
1. In delete_appointment (POST /{appointment_id}/delete), replace:
     await db.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
   With:
     cursor = await db.execute("SELECT id FROM appointments WHERE id = ? AND doctor_id = ?", (appointment_id, user["sub"]))
     if not await cursor.fetchone():
         return JSONResponse(status_code=403, content={"error": "Accès non autorisé"})
     await db.execute("DELETE FROM appointments WHERE id = ? AND doctor_id = ?", (appointment_id, user["sub"]))
   Also apply doctor_id filter to the two preceding UPDATE statements (consultations and questionnaire_responses can stay as-is since they reference appointment_id not doctor).

2. In update_status (POST /{appointment_id}/status), add a doctor_id ownership check before the UPDATE:
     cursor = await db.execute("SELECT id FROM appointments WHERE id = ? AND doctor_id = ?", (appointment_id, user["sub"]))
     if not await cursor.fetchone():
         return JSONResponse(status_code=403, content={"error": "Accès non autorisé"})
   Then change the UPDATE to also filter: WHERE id = ? AND doctor_id = ?
```

**BUG-12 — Édition de consultation sans vérification d'ownership (Sécurité Majeure)**
`routers/consultations.py` lignes 476–607 — Le GET `/consultations/{id}/edit` récupère la consultation par `id` seul (`SELECT * FROM consultations WHERE id = ?`), sans vérifier que `doctor_id = user["sub"]`. Idem pour le POST.
Claude Code Prompt:
```
In medfollow/routers/consultations.py:
In edit_consultation_form() (GET /{consultation_id}/edit), change the query to:
  cursor = await db.execute(
      "SELECT * FROM consultations WHERE id = ? AND doctor_id = ?",
      (consultation_id, user["sub"])
  )
In update_consultation() (POST /{consultation_id}/edit), change the UPDATE query to:
  WHERE id = ? AND doctor_id = ?
And add the user["sub"] parameter at the end of the params tuple.
Also fix view_consultation() (GET /{consultation_id}) for the same reason — add AND c.doctor_id = ? to the JOIN query.
```

**BUG-13 — doctor_id facture non validé contre l'utilisateur connecté (Sécurité Moyenne)**
`routers/invoices.py` ligne 139 — `doctor_id = int(form["doctor_id"])` prend la valeur du formulaire sans vérifier qu'elle correspond à `user["sub"]`. Un utilisateur malveillant peut créer des factures au nom d'un autre praticien.
Claude Code Prompt:
```
In medfollow/routers/invoices.py, in create_invoice() (POST /new):
Replace:
  doctor_id = int(form["doctor_id"])
With:
  doctor_id = user["sub"]
The doctor_id in the form is cosmetic (used for display) — the actual owner should always be the authenticated user.
If multi-doctor invoicing is needed, at minimum validate:
  cursor = await db.execute("SELECT id FROM users WHERE id = ? AND role IN ('medecin','admin')", (int(form["doctor_id"]),))
  if not await cursor.fetchone(): doctor_id = user["sub"]
```

**BUG-14 — date_of_birth non validée côté serveur (Mineure)**
`routers/patients.py` lignes 146–159 — `date_of_birth` est insérée en base sans validation de format côté serveur. Une valeur invalide comme "abc" ne crashe pas l'insert SQLite (colonne TEXT) mais casse `calc_age` et toute logique de tri par date.
Claude Code Prompt:
```
In medfollow/routers/patients.py, add a validation helper at the top of the file:
  from datetime import date as _date
  def _validate_date(s: str) -> bool:
      try:
          _date.fromisoformat(s)
          return True
      except (ValueError, TypeError):
          return False

In create_patient() and update_patient(), after receiving date_of_birth from form:
  if not _validate_date(date_of_birth):
      return templates.TemplateResponse("patients/form.html", {
          ..., "error": "Format de date invalide (AAAA-MM-JJ requis)."
      })
```

---

### PROBLÈMES UX

**UX-12 — Vue liste manquante dans l'agenda (Haute)** validated
L'agenda n'a qu'une vue calendrier (FullCalendar). Pour les exports, les suivis et les praticiens qui préfèrent une vue tabulaire, il manque une vue "liste" des RDV (date, patient, type, statut) avec filtres par période/statut.
Claude Code Prompt:
```
In medfollow/templates/appointments/index.html, in the FullCalendar config, add to the headerToolbar buttons:
  'listWeek,listMonth'
And add to the views object:
  listWeek: { buttonText: 'Liste semaine' },
  listMonth: { buttonText: 'Liste mois' }
Also add to the calendar config:
  views: {
      listWeek: { noEventsText: 'Aucun rendez-vous cette semaine' },
      listMonth: { noEventsText: 'Aucun rendez-vous ce mois' }
  }
This uses FullCalendar's built-in list plugin (already bundled in most CDN builds).
If the list plugin is not available, add it to the FullCalendar CDN import.
```

**UX-13 — Pas de bouton pour annuler une facture (Moyenne)** validated
Le statut `annulee` existe en base (`routers/invoices.py` ligne 68) mais aucun endpoint ni bouton dans l'UI ne permet de passer une facture en statut annulé.
Claude Code Prompt:
```
In medfollow/routers/invoices.py, add a new route:
  @router.post("/{invoice_id}/cancel")
  async def cancel_invoice(request, invoice_id, db=Depends(get_db)):
      user = get_current_user(request)
      if not user: return RedirectResponse("/login", 302)
      await db.execute(
          "UPDATE invoices SET status='annulee', updated_at=CURRENT_TIMESTAMP WHERE id=? AND doctor_id=?",
          (invoice_id, user["sub"])
      )
      await db.commit()
      return RedirectResponse(f"/invoices/{invoice_id}", 302)

In medfollow/templates/invoices/detail.html, add a cancel button in the action bar (only if status != 'annulee' and != 'payee'):
  {% if invoice.status not in ('annulee', 'payee') %}
  <form method="POST" action="/invoices/{{ invoice.id }}/cancel"
        onsubmit="return confirm('Annuler cette facture ? Cette action ne peut pas être annulée.')">
    <button type="submit" class="btn btn-danger-outline">Annuler la facture</button>
  </form>
  {% endif %}
```

**UX-14 — Métriques financières absentes du tableau de bord (Haute)**
Le dashboard affiche nb patients, RDV du jour, consultations du mois, messages non lus — mais aucune statistique financière. Or `ca_monthly` et `ca_annual` sont déjà calculés dans `routers/invoices.py` et pourraient simplement être ajoutés au dashboard.
Claude Code Prompt:
```
In medfollow/routers/dashboard.py, in the dashboard() function, add after the stats block:
  cursor = await db.execute(
      "SELECT COALESCE(SUM(total_amount),0), COALESCE(SUM(paid_amount),0) FROM invoices WHERE doctor_id=? AND status!='annulee' AND strftime('%Y-%m',invoice_date)=strftime('%Y-%m','now')",
      (uid,)
  )
  row = await cursor.fetchone()
  ca_month, paid_month = row[0], row[1]

  cursor = await db.execute(
      "SELECT COUNT(*) FROM invoices WHERE doctor_id=? AND status='emise'", (uid,)
  )
  pending_invoices = (await cursor.fetchone())[0]

  stats["ca_month"] = ca_month
  stats["paid_month"] = paid_month
  stats["pending_invoices"] = pending_invoices

In medfollow/templates/dashboard.html, add stat cards:
  - "CA ce mois": stats.ca_month formatted as "X DH" → link to /invoices
  - "Factures en attente": stats.pending_invoices → link to /invoices?status=emise
```

**UX-15 — Pas de date de dernière visite dans la liste patients (Moyenne)** validated 
La liste patients affiche nom, âge, téléphone, ville, n° sécu. Il n'y a pas de colonne "Dernière consultation" qui permettrait de repérer rapidement les patients perdus de vue.
Claude Code Prompt:
```
In medfollow/routers/patients.py, in list_patients(), change the SELECT query to include last visit:
  SELECT p.*, (
      SELECT MAX(c.consultation_date) FROM consultations c WHERE c.patient_id = p.id
  ) AS last_visit
  FROM patients p
  WHERE p.doctor_id = ? AND p.is_active = 1 ...

In medfollow/templates/patients/list.html, add a new column header "Dernière visite" and in the row:
  <td>{{ p.last_visit or '—' }}</td>
Style rows where last_visit < 6 months ago with a subtle highlight (class .patient-recent) and rows with no visit or visit > 1 year with a muted style (.patient-inactive) for quick visual scanning.
```

**UX-16 — Pas d'export CSV depuis la liste des factures (Haute)** validated
Les praticiens ont besoin d'exporter leurs factures pour leur comptable. Il n'y a aucun mécanisme d'export dans l'application.
Claude Code Prompt:
```
In medfollow/routers/invoices.py, add a CSV export endpoint:
  import csv, io
  @router.get("/export.csv")
  async def export_invoices_csv(request, status=None, date_from="", date_to="", db=Depends(get_db)):
      user = get_current_user(request)
      if not user: return RedirectResponse("/login", 302)
      # Same WHERE clause as list_invoices
      cursor = await db.execute(query, params)
      rows = await cursor.fetchall()
      
      output = io.StringIO()
      writer = csv.writer(output, delimiter=';')
      writer.writerow(["N° Facture","Patient","Date","Total (DH)","Payé (DH)","Reste","Statut","Mutuelle"])
      for r in rows:
          writer.writerow([r["invoice_number"], r["patient_name"], r["invoice_date"],
                           r["total_amount"], r["paid_amount"],
                           r["total_amount"]-r["paid_amount"], r["status"],
                           "Oui" if r["tiers_payant"] else "Non"])
      
      return Response(content=output.getvalue().encode("utf-8-sig"),
                      media_type="text/csv",
                      headers={"Content-Disposition": "attachment; filename=factures.csv"})

In medfollow/templates/invoices/list.html, add an "Exporter CSV" button next to the filters that links to /invoices/export.csv with current filter params.
```

**UX-17 — Pas de lien direct "Nouvelle ordonnance" depuis la fiche patient (Moyenne)**
La fiche patient montre un onglet Ordonnances avec la liste, mais n'a pas de bouton "Nouvelle ordonnance" qui pré-remplit le `patient_id`. Le praticien doit aller dans Ordonnances > Nouvelle et re-chercher le patient.
Claude Code Prompt:
```
In medfollow/templates/patients/detail.html, in the "Ordonnances" tab section, add a button:
  <a href="/prescriptions/new?patient_id={{ patient.id }}" class="btn btn-primary btn-sm">
    + Nouvelle ordonnance
  </a>

In medfollow/routers/prescriptions.py, in the new_prescription_form() GET route, read the
patient_id query param and pass it to the template as selected_patient_id (same pattern
as /consultations/new?patient_id=...).
```

**UX-18 — Formulaire patient : validation côté client manquante pour le téléphone (Basse)**
Le champ téléphone accepte n'importe quelle chaîne. Pour les praticiens marocains, un format +212/06/07 est attendu mais jamais suggéré ni validé.
Claude Code Prompt:
```
In medfollow/templates/patients/form.html, update the phone input:
  <input type="tel" name="phone" value="{{ patient.phone or '' }}"
         placeholder="06 12 34 56 78 ou +212 6 12 34 56 78"
         pattern="^(\+212|0)[5-7][0-9]{8}$"
         title="Format attendu : 06XXXXXXXX ou +212 6XXXXXXXX">
Add a small hint below: <small class="field-hint">Format Maroc : 06XXXXXXXX</small>
This is client-side only — no server change needed.
```

---

### FONCTIONNALITÉS MANQUANTES (priorité)

1. **Vue liste agenda** — FullCalendar listWeek/listMonth déjà disponible, juste à activer (UX-12) (Haute)
2. **Export CSV factures** — Pas de mécanisme d'export pour le comptable (UX-16) (Haute)
3. **Métriques financières dashboard** — CA mensuel/annuel pas visible depuis l'accueil (UX-14) (Haute)
4. **Annulation de facture** — Le statut existe en DB mais aucun bouton dans l'UI (UX-13) (Moyenne)
5. **Dernière visite dans liste patients** — Colonne manquante pour repérer patients perdus de vue (UX-15) (Moyenne)
6. **Autocomplete/validation téléphone** — Champ non guidé pour format marocain (UX-18) (Basse)

---

### ÉVALUATION GLOBALE : 7.5 / 10 (inchangée)

Même niveau qu'au 2026-04-08. Les bugs de sécurité BUG-11/12/13 sont nouveaux et critiques — un utilisateur malveillant authentifié peut supprimer les RDV d'autres praticiens et lire/modifier leurs consultations. À prioriser absolument sur toute autre amélioration UX.

---

## 2026-04-08

Source: https://doctivo.up.railway.app/ — Audit fonctionnel & UX complet

---

### BUGS IDENTIFIÉS

**BUG-01 — Calcul d'âge approximatif (Mineure)** Validated 
`templates/patients/list.html` — Le calcul `now_year - birth_year` ignore le mois/jour → âge incorrect jusqu'à l'anniversaire.
Claude Code Prompt:
```
In medfollow/templates/patients/list.html, the age calculation ignores month and day.
Add a custom Jinja2 filter called `calc_age` in medfollow/main.py that takes a date_of_birth
string (YYYY-MM-DD) and returns the exact age in years as an integer using Python's date arithmetic.
Register this filter on the templates environment. Update patients/list.html and any other
template displaying age to use: {{ p.date_of_birth | calc_age }} ans
```

**BUG-02 — Statut de facture affiché brut (Mineure UX)** Validated 
`templates/invoices/detail.html` — "partiellement_payee" s'affiche comme `PARTIELLEMENT_PAYEE`.
Claude Code Prompt:
```
In medfollow/templates/invoices/detail.html, replace {{ invoice.status | upper }} with
a human-readable label. Add a Jinja2 filter or a dict mapping in the template:
STATUS_LABELS = {'brouillon':'Brouillon','en_attente':'En attente','payee':'Payée',
'partiellement_payee':'Partiellement payée','annulee':'Annulée'}
Then use: {{ STATUS_LABELS.get(invoice.status, invoice.status) }}
```

**BUG-03 — Secret key JWT non persistée sur Railway (Majeure)** Validated 
`config.py` — Clé JWT régénérée à chaque redéploiement → tous les utilisateurs déconnectés.
Claude Code Prompt:
```
In medfollow/config.py, add a startup check: if MEDFOLLOW_SECRET_KEY env variable is not set,
print a prominent warning: "WARNING: MEDFOLLOW_SECRET_KEY not set. Sessions will be invalidated
on restart. Set this env variable in your Railway dashboard."
Also create a .env.example file documenting MEDFOLLOW_SECRET_KEY as required for production.
The secret should be read from: os.getenv("MEDFOLLOW_SECRET_KEY") first, then file fallback.
```

**BUG-04 — Race condition numéro de facture (Mineure)** Validated 
`routers/invoices.py` — Deux requêtes simultanées peuvent générer le même numéro de facture.
Claude Code Prompt:
```
In medfollow/routers/invoices.py, wrap the invoice number generation and INSERT in a
SQLite exclusive transaction using BEGIN EXCLUSIVE. Alternatively, use a UNIQUE constraint
with a retry loop (up to 3 attempts) if IntegrityError is raised on invoice_number.
```

**BUG-05 & BUG-06 — Posologie et fréquence ordonnance en select fixe (Moyenne — bloquant)** Validated 
`templates/prescriptions/form.html` — Impossible de prescrire "3 comprimés" ou fréquences non listées.
Claude Code Prompt:
```
In medfollow/templates/prescriptions/form.html, replace the <select> for "Posologie" and
"Fréquence" with <input type="text" list="..."> + <datalist> containing the same options.
This allows free text while still suggesting common values. Update the JavaScript that
dynamically adds medication rows to replicate the same pattern.
Example:
  <input type="text" name="med_dosage_N" list="dosage-list" placeholder="ex: 1 comprimé">
  <datalist id="dosage-list">
    <option value="1 comprimé"><option value="2 comprimés">...
  </datalist>
```

**BUG-07 — Accès non autorisé aux documents et messages (Sécurité)**
`routers/documents.py`, `routers/messages.py` — Tout utilisateur authentifié peut lire/télécharger n'importe quel document ou message.
Claude Code Prompt:
```
In medfollow/routers/documents.py, for GET /{document_id}/download and POST /{document_id}/delete,
add a JOIN with patients to verify patient.doctor_id = current_user["sub"].
If unauthorized, return 403 or redirect to /documents.

In medfollow/routers/messages.py, for GET /{message_id}, verify:
  if message["sender_id"] != user["sub"] and message["recipient_id"] != user["sub"]:
      return RedirectResponse("/messages", 302)

Also fix the patient list in the message compose form:
  Change: SELECT id, first_name, last_name FROM patients WHERE is_active = 1
  To:     SELECT id, first_name, last_name FROM patients WHERE is_active = 1 AND doctor_id = ?
```

**BUG-08 — Liste patients non filtrée par docteur dans messagerie (Sécurité)**
Inclus dans BUG-07 ci-dessus.

**BUG-09 — Suppression patient sans confirmation (UX Majeure)**
`templates/patients/detail.html` — Clic accidentel possible.
Claude Code Prompt:
```
In medfollow/templates/patients/detail.html, find the delete patient form and add:
  onsubmit="return confirm('Supprimer ce patient ? Cette action est irréversible.')"
Do the same in patients/list.html if a delete button exists there.
```

**BUG-10 — Noms de fichiers uploadés non sécurisés (Sécurité)**
`routers/documents.py` — Vulnérabilité path traversal possible.
Claude Code Prompt:
```
In medfollow/routers/documents.py, replace the basic filename sanitization with a
secure_filename() function that:
1. Normalizes unicode (unicodedata.normalize)
2. Strips path separators (/, \, ..)
3. Keeps only alphanumeric chars, hyphens, underscores, dots
4. Limits length to 200 characters
5. Falls back to a UUID-based name if result is empty
Replace: safe_filename = file.filename.replace(" ", "_")
With:    safe_filename = secure_filename(file.filename)
```

---

### PROBLÈMES UX

**UX-01 — Email affiché au lieu du nom du praticien dans la sidebar** Validated
Claude Code Prompt:
```
In medfollow/services/auth_service.py's create_token(), add first_name and last_name
to the JWT payload. Update login/setup routes in routers/auth.py to pass these values.
In templates/base.html, replace {{ user.email }} with:
  Dr. {{ user.first_name }} {{ user.last_name }}
  <small>{{ user.email }}</small>
```

**UX-02 — Stats dashboard non cliquables**
Claude Code Prompt:
```
In medfollow/templates/dashboard.html, wrap each stat card in an <a href="..."> tag:
- RDV aujourd'hui → /appointments
- Patients actifs → /patients
- Consultations du mois → /consultations
- Factures en attente → /invoices?status=en_attente
Add a subtle hover effect (slight elevation) on the stat cards via CSS.
```

**UX-03 — Agenda ne défile pas vers l'heure courante**
Claude Code Prompt:
```
In medfollow/templates/appointments/index.html, in the FullCalendar config, add:
  scrollTime: new Date().getHours() + ':00:00',
  initialView: isMobileView ? 'timeGridDay' : 'timeGridWeek',
This will open the calendar on the current week in time-grid view and scroll to now.
Add a "Aujourd'hui" button behavior that also scrolls to current time when clicked.
```

**UX-04 — Pas de constantes vitales précédentes visibles dans la consultation**
Claude Code Prompt:
```
In medfollow/routers/consultations.py's new_consultation_form() route, when patient_id
is provided, fetch the most recent vitals:
  SELECT v.* FROM vitals v JOIN consultations c ON v.consultation_id = c.id
  WHERE v.patient_id = ? ORDER BY c.consultation_date DESC LIMIT 1
Pass as previous_vitals to the template. In consultations/form.html, next to each vital
input show: <span class="prev-hint">Précédent: {{ previous_vitals.blood_pressure_sys }}</span>
Style with small gray text below each input.
```

**UX-05 — Pas de bouton renouvellement ordonnance**
Claude Code Prompt:
```
In medfollow/routers/prescriptions.py, add POST /{prescription_id}/renew route that:
1. Fetches original prescription + items
2. Creates new prescription with today's date, same patient/doctor/medications
3. Increments renewal_count on the original
4. Redirects to the new prescription

In medfollow/templates/prescriptions/detail.html, add in the action bar:
  <form method="POST" action="/prescriptions/{{ prescription.id }}/renew" style="display:inline;">
    <button type="submit" class="btn btn-outline">Renouveler l'ordonnance</button>
  </form>
```

**UX-06 — Pas de lien Consultation → Facture**
Claude Code Prompt:
```
In medfollow/templates/consultations/detail.html, add a "Facturer" button in the action bar:
  <a href="/invoices/new?patient_id={{ consultation.pid }}" class="btn btn-outline">Facturer</a>

In medfollow/routers/invoices.py's new_invoice_form GET route, read patient_id query param
and pre-select the patient in the template context.
```

**UX-07 — Pas de recherche patient dans la liste factures**
Claude Code Prompt:
```
In medfollow/routers/invoices.py, add optional query param q: str = "" to list_invoices().
When q is provided, filter: AND (lower(p.first_name) LIKE ? OR lower(p.last_name) LIKE ?)
In medfollow/templates/invoices/list.html, add a search input above the table (same pattern
as patients/list.html).
```

**UX-08 — Pas de badge messages non lus dans la sidebar**
Claude Code Prompt:
```
In medfollow/main.py or a middleware, inject unread_messages_count into all template contexts
for authenticated users:
  SELECT COUNT(*) FROM messages WHERE recipient_id = ? AND is_read = 0

In medfollow/templates/base.html, add a badge on the Messagerie nav item:
  {% if unread_messages_count > 0 %}
  <span class="nav-badge">{{ unread_messages_count }}</span>
  {% endif %}

Add CSS: .nav-badge { position:absolute; top:4px; right:4px; background:#ef4444; color:white;
border-radius:999px; font-size:10px; padding:1px 5px; font-weight:700; }
```

**UX-09 — Pas de tri des colonnes dans la liste patients** validated
Claude Code Prompt:
```
In medfollow/routers/patients.py's list_patients(), add sort_by (whitelist: last_name,
date_of_birth, city, created_at) and sort_order (asc/desc) query params.
In templates/patients/list.html, make column headers into sort links that toggle order:
  <a href="/patients?sort_by=last_name&sort_order={{ 'desc' if current_sort=='last_name,asc' else 'asc' }}">
    Patient {{ '↑' if ... else '↓' }}
  </a>
```

**UX-10 — Motif consultation non pré-rempli depuis le RDV**
Claude Code Prompt:
```
In medfollow/routers/consultations.py's new_consultation_form() GET route, when
appointment_id is provided, fetch the appointment title:
  cursor = await db.execute("SELECT title FROM appointments WHERE id = ?", (appointment_id,))
  prefill_reason = row["title"] if row else ""
Pass prefill_reason to template. In consultations/form.html update the Motif textarea:
  <textarea name="reason">{{ prefill_reason or (consultation.reason if consultation else '') }}</textarea>
```

**UX-11 — Session expirée sans message explicite**
Claude Code Prompt:
```
In medfollow/routers/auth.py, when redirecting due to token expiry (JWTError), use:
  return RedirectResponse("/login?reason=expired", 302)
In medfollow/templates/login.html, add:
  {% if request.query_params.get('reason') == 'expired' %}
  <div class="alert alert-warning" style="...">Votre session a expiré. Veuillez vous reconnecter.</div>
  {% endif %}
```

---

### FONCTIONNALITÉS MANQUANTES (priorité)

1. **Recherche globale accessible** — L'API /api/search existe mais aucun champ dans l'UI (Haute)
2. **Export CSV/Excel** patients et factures pour soumissions mutuelle (Moyenne)
3. **Blocage plages indisponibles** dans l'agenda (congés, pause déjeuner) (Moyenne)
4. **Statistiques revenus** avec graphiques dans le dashboard (Moyenne)
5. **Impression fiche patient** — seule la consultation a ce bouton (Moyenne)
6. **PWA / installation mobile** — viewport responsive présent mais pas d'icône d'install (Basse)

---

### ÉVALUATION GLOBALE : 7.5 / 10

Points forts : Odontogramme remarquable, détection de conflits RDV, contextualisation dentiste/médecin, localisation marocaine (mutuelles, médicaments).
Points faibles : 3 failles de sécurité (documents, messages, upload), workflow consultation→facturation cassé, posologie ordonnance bloquante.
