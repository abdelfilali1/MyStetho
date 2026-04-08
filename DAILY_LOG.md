# Doctivo — Daily Log

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
