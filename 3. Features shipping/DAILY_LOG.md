# Doctivo — Daily Log

---

## 2026-04-25 (scheduled run)

### B8 — Ownership RDV (Sécurité Majeure)
- `medfollow/routers/appointments.py` — `update_status`: added ownership check (SELECT id WHERE id=? AND doctor_id=?) before UPDATE; returns 403 if not found
- `medfollow/routers/appointments.py` — `delete_appointment`: added same ownership check before DELETE; redirects to /appointments if not found

### U1 — Vues liste agenda
- `medfollow/templates/appointments/index.html` — Added `listWeek` and `listMonth` to FullCalendar `headerToolbar` (desktop + mobile); added button labels "Liste sem." / "Liste mois" to `buttonText`

### U2 — Annulation facture
- `medfollow/routers/invoices.py` — Added `POST /invoices/{invoice_id}/cancel` route: verifies doctor_id ownership, sets status to `annulee`
- `medfollow/templates/invoices/detail.html` — Added "Annuler la facture" button (danger style, with confirm dialog) visible when status != `annulee`

### U3 — Colonne "Dernière visite"
- `medfollow/routers/patients.py` — Modified both SELECT queries (with/without search) to include subquery `(SELECT MAX(consultation_date) FROM consultations WHERE patient_id = p.id) AS last_visit`
- `medfollow/templates/patients/list.html` — Added "Dernière visite" column header and `{{ p.last_visit or '—' }}` cell

### U4 — Export CSV factures
- `medfollow/routers/invoices.py` — Added `GET /invoices/export.csv` route: respects status/date_from/date_to filters, returns UTF-8-BOM CSV (Excel-compatible)
- `medfollow/templates/invoices/list.html` — Added "↓ Export CSV" button next to "+ Nouvelle facture", passes current filter params

---

## 2026-04-08 (do-prompt run)

### B1 — Calcul d'âge précis
- `medfollow/main.py` — Added `_calc_age()` function and registered as Jinja2 filter `calc_age` on all template envs
- `medfollow/templates/patients/list.html` — Replaced manual birth year arithmetic with `{{ p.date_of_birth | calc_age }} ans`

### B2 — Statut facture lisible
- `medfollow/templates/invoices/detail.html` — Replaced `{{ invoice.status | upper }}` with dict mapping to human-readable French labels

### B3 — Clé JWT Railway
- `medfollow/config.py` — Added warning log when key cannot be persisted to file (ephemeral FS on Railway)
- `medfollow/.env.example` — Created with `MEDFOLLOW_SECRET_KEY` documented as required for production

### B4 — Race condition numéro de facture
- `medfollow/routers/invoices.py` — Replaced single INSERT with retry loop (up to 3 attempts) catching IntegrityError on `invoice_number` uniqueness

### B5 — Posologie & fréquence libres
- `medfollow/templates/prescriptions/form.html` — Replaced `<select>` for dosage and frequency with `<input type="text" list="...">` + `<datalist>` in all 3 locations (existing items loop, default item, JS addMedication())

### B6 — Nom praticien dans la sidebar
- `medfollow/services/auth_service.py` — Added `first_name` and `last_name` params to `create_token()`
- `medfollow/routers/auth.py` — Updated both `create_token()` calls to pass first_name/last_name
- `medfollow/templates/base.html` — Sidebar footer now shows "Dr. Prénom NOM" instead of email; email moved to subtitle

### B7 — Tri colonnes liste patients
- `medfollow/routers/patients.py` — Added `sort_by` and `sort_order` query params with whitelist validation; injected into template context
- `medfollow/templates/patients/list.html` — Column headers (Patient, Date naissance, Ville) are now sort links with ↑/↓ indicators

### S1 — Brochures PDF patients
- `medfollow/services/pdf_service.py` — Added `generate_patient_brochure_pdf()` with identity, antécédents, prochains RDV, traitements en cours sections
- `medfollow/routers/patients.py` — Added `GET /patients/{id}/brochure.pdf` route fetching all patient data and streaming the PDF
- `medfollow/templates/patients/detail.html` — Added "📄 Brochure PDF" button in action bar

---

## 2026-04-08

### A1 — Conflit créneau
Already fully implemented (backend + frontend). No changes needed.

### A2 — Déplacer RDV depuis l'agenda
- **File:** `medfollow/templates/appointments/index.html`
- Enabled `editable: true` on FullCalendar + added `eventDrop` callback calling `/appointments/{id}/reschedule`
- On conflict: reverts drag and shows toast with available slots

### A4 — Cohérence antécédents
Already fully implemented. No changes needed.

### A5 — Mutuelle & Assurance
Already fully implemented. No changes needed.

### A6 — Détartrage 32 dents en un clic
- **File:** `medfollow/templates/dental/chart.html`
- Added "🧹 Détartrage 32 dents" button in odontogram header
- Added `bulkDetartrage()` JS calling existing `/dental/{id}/bulk-treatment` endpoint

### A7 — Historique condition par dent
- **File:** `medfollow/templates/dental/chart.html`
- Added toggle button "▶ Historique de la condition" below condition save button
- Added `toggleConditionHistory()` JS fetching `/dental/{id}/tooth/{n}/condition-history`
- History loads lazily on first open, resets when panel closes

---

## 2026-03-23

### Session: Backlog run (top → bottom)

| Item | Status | Files changed |
|---|---|---|
| A1 — Conflit créneau | ✅ Done | `routers/appointments.py`, `templates/appointments/index.html` |
| A4 — Cohérence antécédents | ✅ Done | `routers/consultations.py` |
| A6 — Détartrage multi-dents | ✅ Done | `routers/dental.py`, `templates/patients/detail.html` |
| A5 — Mutuelle & Assurance | ✅ Done | `database/connection.py`, `routers/patients.py`, `templates/patients/form.html`, `templates/patients/detail.html` |
| A7 — Historique condition dent | ✅ Done | `database/connection.py`, `routers/dental.py`, `templates/patients/detail.html` |
| A2 — Déplacer RDV depuis agenda | ✅ Done | `routers/appointments.py`, `templates/appointments/index.html` |

### Detail

**A1 — Conflit créneau**
- Added `POST /appointments/api/new` JSON endpoint with overlap check (SQL: `start < new_end AND end > new_start`, excludes annulé/absent)
- On conflict → returns HTTP 409 + up to 4 suggested free slots for the same day
- Frontend: form now submits via fetch; shows red banner with clickable time suggestions
- Added `GET /appointments/api/free-slots` for standalone slot lookup

**A4 — Cohérence antécédents**
- `dental_allergies` entered in consultation is now saved to `medical_history` (type=`allergy`) via `_save_history_item_if_new`
- New consultation form pre-fills `dental_allergies` from `medical_history` (latest allergy entry) instead of empty
- Edit form falls back to `medical_history` if vitals JSON has no allergy

**A6 — Détartrage multi-dents**
- Added `POST /dental/{patient_id}/bulk-treatment` — creates ONE appointment + 32 treatment records (one per FDI tooth)
- Frontend: "Appliquer à toutes les dents (32)" button appears when Détartrage / Blanchiment / Radiographie is selected

**A5 — Mutuelle & Assurance**
- DB migration: `ALTER TABLE patients ADD COLUMN insurance_serial TEXT`
- `insurance_name` field changed from free text to dropdown: CNOPS, CNSS, AMO, MAMDA, MGPAP, RMA, Saham, Allianz, AXA, Autre
- Added `insurance_serial` field (N° Série carte mutuelle)
- Detail view: shows organisme · N° adhérent · N° série

**A7 — Historique condition dent**
- DB migration: new `dental_condition_history` table (patient_id, tooth_number, condition, notes, changed_by, changed_at)
- `update_tooth_condition` now logs to history **only when condition actually changes**
- New `GET /dental/{patient_id}/tooth/{tooth_number}/condition-history` endpoint
- Tooth panel: "Afficher / Masquer" toggle for chronological history; resets when switching teeth

**A2 — Déplacer RDV depuis agenda**
- Added `POST /appointments/{id}/reschedule` JSON endpoint with conflict check + suggestions
- Event detail modal: new "📅 Déplacer" button reveals inline date/time pickers
- On conflict: shows suggested slots (same UX as A1)
- On success: refetches calendar and closes modal

### Items skipped (A3 — notifications / S1 — brochures)
- A3 (SMS/email to patients) requires decision on channel (SMS cost, email vs WhatsApp) — see backlog D1
- S1 (brochures PDF) is a design task, not a code task
