# Doctivo — Daily Log

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
