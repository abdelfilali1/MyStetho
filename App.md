# Doctivo — Application Overview

> Medical practice management system built with FastAPI + SQLite + Jinja2.
> Branded **Doctivo** · Slogan: *"La santé, mieux organisée"*

---

## 1. Technology Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115.0 |
| Server | Uvicorn 0.30.6 |
| Database | SQLite via aiosqlite 0.20.0 |
| Templating | Jinja2 3.1.4 |
| Auth | JWT (PyJWT 2.9.0) + bcrypt 4.2.0 |
| PDF | ReportLab 4.2.2 |
| Validation | Pydantic 2.9.0 |
| Dental UI | odontogram-view.iife.js (React, mounted via `window.OdontoNpm.mountOdontogram`) |

---

## 2. Project Structure

```
medfollow/
├── main.py                  # App entry point, router registration, lifespan
├── config.py                # DB path, JWT secret, upload dir, template dir
├── database/
│   └── connection.py        # init_db(), seed_db(), get_db() dependency
├── routers/
│   ├── auth.py              # Login, logout, setup, admin user management
│   ├── dashboard.py         # Home stats, global search API
│   ├── patients.py          # Patient CRUD, medical history, dental data fetch
│   ├── appointments.py      # Calendar agenda, event API
│   ├── consultations.py     # Consultation CRUD, vitals, PDF
│   ├── prescriptions.py     # Prescription CRUD, medication search, PDF
│   ├── documents.py         # File upload/download
│   ├── messages.py          # Internal messaging with threading
│   ├── invoices.py          # Invoicing, payments, revenue stats
│   └── dental.py            # Tooth condition, treatments, endodontic canals
├── services/
│   └── auth_service.py      # hash_password, verify_password, create_token, decode_token
├── templates/               # Jinja2 HTML templates (see §5)
├── static/
│   ├── css/style.css        # Global stylesheet
│   ├── img/logo4.png        # Current app logo
│   └── js/
│       ├── odontogram-view.iife.js   # Dental chart library
│       └── odontogram-view.iife.css
├── data/
│   ├── medfollow.db         # SQLite database
│   └── .secret_key          # Persisted JWT secret
└── uploads/
    └── patient_{id}/        # Per-patient uploaded documents
```

---

## 3. Authentication

- **Method:** JWT stored in an `httponly` cookie (`access_token`)
- **Expiry:** 8 hours
- **Roles:** `medecin`, `secretaire`, `admin`
- **Specialty gate:** features conditionally enabled when `"dent" in user["specialty"].lower()` — dentists get the full dental UI (Disposition, Odontogramme, Endodontie tabs)
- `get_current_user(request)` decodes the cookie on every request; returns `None` if missing/expired → redirect to `/login`

---

## 4. Data Model

### UML Object Graph

```
users ─────────────────────────────────────────────────────┐
  │ 1                                                       │
  │ doctor_id FK                                            │
  ├──< patients                                             │
  │       │ patient_id FK                                   │
  │       ├──< medical_history                              │
  │       ├──< appointments >──────────────────── doctor_id─┤
  │       │       │ appointment_id FK                       │
  │       │       └──< consultations >────────── doctor_id─┤
  │       │               │ consultation_id FK              │
  │       │               ├──< vitals                       │
  │       │               ├──< prescriptions >─── doctor_id┤
  │       │               │       └──< prescription_items   │
  │       │               └──< documents                    │
  │       │                                                 │
  │       ├──< dental_teeth                                 │
  │       ├──< dental_treatments >── appointment_id         │
  │       ├──< endo_canals                                  │
  │       ├──< endo_history                                 │
  │       ├──< endo_notes                                   │
  │       ├──< documents                                    │
  │       └──< invoices >──────────────────────── doctor_id─┤
  │               └──< invoice_items                        │
  │               └──< payments                             │
  │                                                         │
  ├──< messages (sender_id) ──────── recipient_id ──────────┤
  └──< consultation_templates                               │
                                                           ─┘
medications (standalone lookup table, specialty-filtered)
medical_acts (standalone lookup table for invoice line items)
questionnaires / questionnaire_responses (standalone)
```

### Tables

#### `users`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| email | TEXT UNIQUE | |
| password_hash | TEXT | bcrypt |
| first_name, last_name | TEXT | |
| role | TEXT | medecin / secretaire / admin |
| specialty | TEXT | "dent" triggers dental features |
| phone | TEXT | |
| is_active | INT | 1/0 |
| created_at, updated_at | DATETIME | |

#### `patients`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| doctor_id | FK → users | |
| first_name, last_name | TEXT | |
| date_of_birth | TEXT | YYYY-MM-DD |
| gender | TEXT | |
| social_security_number | TEXT UNIQUE | |
| email, phone | TEXT | |
| address, city, postal_code | TEXT | |
| blood_type | TEXT | |
| referring_doctor | TEXT | |
| insurance_name, insurance_number | TEXT | |
| emergency_contact_name, emergency_contact_phone | TEXT | |
| notes | TEXT | |
| is_active | INT | soft delete |

#### `medical_history`
| Column | Notes |
|---|---|
| patient_id FK | |
| type | medical / surgical / family / allergy |
| description, date_recorded | |

#### `appointments`
| Column | Notes |
|---|---|
| patient_id, doctor_id FK | |
| title, appointment_type | consultation / suivi / intervention / urgence |
| start_datetime, end_datetime | ISO datetime |
| status | planifie / confirme / en_cours / termine / annule / absent |
| room, notes | |

#### `consultations`
| Column | Notes |
|---|---|
| patient_id, doctor_id, appointment_id FK | |
| consultation_date | |
| reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes | |

#### `vitals`
| Column | Notes |
|---|---|
| consultation_id, patient_id FK | |
| weight, height | kg / cm |
| blood_pressure_sys, blood_pressure_dia | mmHg |
| heart_rate, temperature, spo2 | |
| notes | JSON: `{dental_medical_history, dental_allergies}` |

#### `prescriptions`
| Column | Notes |
|---|---|
| consultation_id, patient_id, doctor_id FK | |
| prescription_date | |
| is_renewable, renewal_count | |
| status | active / terminee / annulee |

#### `prescription_items`
| Column | Notes |
|---|---|
| prescription_id FK | |
| medication_name, dosage, frequency, duration, instructions, quantity | |

#### `medications`
| Column | Notes |
|---|---|
| name, active_ingredient, category | |
| common_dosages | comma-separated suggestions |
| specialty | general / dentiste |
| form, lab | |

#### `documents`
| Column | Notes |
|---|---|
| patient_id, consultation_id FK | |
| title, category | radio / labo / courrier / compte_rendu / ordonnance / autre |
| file_path, file_type, file_size | stored under `uploads/patient_{id}/` |
| uploaded_by FK → users | |

#### `messages`
| Column | Notes |
|---|---|
| sender_id, recipient_id FK → users | |
| patient_id FK (optional) | |
| subject, body | |
| is_read | 0/1 |
| parent_message_id FK → messages | threading |

#### `invoices`
| Column | Notes |
|---|---|
| invoice_number | F{YEAR}-{SEQ} auto-generated |
| patient_id, consultation_id, doctor_id FK | |
| total_amount, paid_amount | |
| status | brouillon / emise / payee / partiellement_payee / annulee |
| tiers_payant | 0/1 |

#### `invoice_items`
| Column | Notes |
|---|---|
| invoice_id, medical_act_id FK | |
| description, quantity, unit_price, total_price | |

#### `payments`
| Column | Notes |
|---|---|
| invoice_id FK | |
| amount, payment_date | |
| payment_method | especes / carte / cheque / virement / tiers_payant |
| reference, notes | |

#### `dental_teeth`
| Column | Notes |
|---|---|
| patient_id, tooth_number | UNIQUE pair — FDI numbering 11–48 |
| condition | sain / carie / obturation / obturation_amalgame / couronne / couronne_provisoire / extraction / implant / devitalise / bridge / fracture |
| notes | |

#### `dental_treatments`
| Column | Notes |
|---|---|
| patient_id, tooth_number, doctor_id FK | |
| treatment_type | Examen / Détartrage / Extraction / Obturation composite / … |
| description, treatment_date | |
| appointment_id FK | auto-created appointment |

#### `endo_canals`
| Column | Notes |
|---|---|
| patient_id, tooth_number, canal_name | UNIQUE triplet |
| estimated_length, working_length, final_length | mm (nullable) |
| status | non_localise → localise → mesure → prepare → obture |
| notes | |

#### `endo_history`
| Column | Notes |
|---|---|
| patient_id, tooth_number, canal_name FK | |
| field | estimated_length / working_length / final_length / status |
| old_value, new_value, corrected_value | |
| changed_by FK → users | |
| changed_at | |

#### `endo_notes`
| Column | Notes |
|---|---|
| patient_id, tooth_number | UNIQUE pair |
| general_notes | |

---

## 5. Pages & Templates

| URL Pattern | Template | Description |
|---|---|---|
| `/login` | `login.html` | Login page |
| `/setup` | `setup.html` | First-run admin creation |
| `/` | `dashboard.html` | Stats + today's appointments |
| `/patients` | `patients/list.html` | Paginated patient list + search |
| `/patients/new` | `patients/form.html` | Create patient |
| `/patients/{id}` | `patients/detail.html` | **Unified patient page (7 tabs)** |
| `/patients/{id}/edit` | `patients/form.html` | Edit patient |
| `/appointments` | `appointments/index.html` | FullCalendar agenda |
| `/consultations` | `consultations/list.html` | Consultation list |
| `/consultations/new` | `consultations/form.html` | New consultation |
| `/consultations/{id}` | `consultations/detail.html` | View consultation |
| `/prescriptions` | `prescriptions/list.html` | Prescription list |
| `/prescriptions/new` | `prescriptions/form.html` | New prescription |
| `/prescriptions/{id}` | `prescriptions/detail.html` | View prescription |
| `/documents` | `documents/list.html` | Document list |
| `/documents/upload` | `documents/upload.html` | Upload document |
| `/messages` | `messages/inbox.html` | Inbox / sent |
| `/messages/new` | `messages/compose.html` | Compose message |
| `/messages/{id}` | `messages/view.html` | Read message + replies |
| `/invoices` | `invoices/list.html` | Invoice list + revenue stats |
| `/invoices/new` | `invoices/form.html` | Create invoice |
| `/invoices/{id}` | `invoices/detail.html` | View invoice + payments |
| `/dental/{patient_id}` | `dental/chart.html` | Standalone dental chart |
| `/admin/users` | `admin/users.html` | User management |

### Patient Detail Page — 7 Tabs (`patients/detail.html`)

```
┌─────────────────────────────────────────────────────────────┐
│ HEADER: Patient name · Imprimer · Modifier · Supprimer      │
├─────────────────────────────────────────────────────────────┤
│ TAB BAR (single line, scrollable):                          │
│  Informations │ Antécédents │ Rendez-vous │ Consultations   │
│  ─── Ordonnances │ [dentists only:] Disposition │           │
│      Odontogramme │ Endodontie                              │
├─────────────────────────────────────────────────────────────┤
│  #view-info        → patient info card (full width)         │
│  #view-hist        → medical history list + add form        │
│  #view-appts       → last 10 appointments table             │
│  #view-consult     → last 10 consultations table            │
│  #view-ordonnance  → prescriptions list + add button        │
│  #view-layout      → React odontogram SQUARE + KPI + legend │
│  #view-odontogram  → React odontogram CIRCLE + KPI + legend │
│  #view-endo        → endo tooth grid + endo modal           │
└─────────────────────────────────────────────────────────────┘
```

**Dental tab lazy init:** views are only built when first clicked.
- `switchTab('layout')` → `mountReactOdontogram('react-odo-root-layout', 'square')`
- `switchTab('odontogram')` → `mountReactOdontogram('react-odo-root-odo', 'circle')`
- `switchTab('endo')` → `buildEndoGrid()`

---

## 6. Key Business Rules

- **Soft delete** for patients (`is_active = 0`) — records are never physically removed.
- **Doctor isolation** — every patient query filters by `doctor_id = user["sub"]`.
- **Specialty gate** — dental tabs/routes only appear when `"dent"` is in the user's specialty string (case-insensitive).
- **FDI tooth numbering** — upper right 18→11, upper left 21→28, lower left 31→38, lower right 41→48.
- **Canal status order** — `non_localise < localise < mesure < prepare < obture` (index in array = priority for summary display).
- **Endo history** — every change to canal lengths or status is logged with old/new value and `changed_by`.
- **Treatment → Appointment** — adding a dental treatment auto-creates a linked appointment.
- **Invoice numbers** — auto-generated as `F{YEAR}-{SEQ}` in `create_invoice`.
- **Medication search** — returns starts-with matches first, then contains; specialty-filtered; triggers at 1 character.
- **PDF generation** — ReportLab used for consultation and prescription PDFs.

---

## 7. Environment & Configuration

| Variable | Default | Description |
|---|---|---|
| `MEDFOLLOW_DATABASE_PATH` | `data/medfollow.db` | SQLite file path |
| `MEDFOLLOW_SECRET_KEY` | read from `data/.secret_key` | JWT signing key |
| `HOST` | `0.0.0.0` | Uvicorn bind host |
| `PORT` | `8000` | Uvicorn port |

---

## 8. Development Notes

- **No migration framework** — schema changes are done with `ALTER TABLE … ADD COLUMN` inside `try/except` blocks in `init_db()`.
- **All UI in French** — labels, field names, status values.
- **Jinja2 + JS template literal conflict** — never use `${{...}}` in `{% block scripts %}`. Extract JS object literals to named `const` variables first.
- **React odontogram bridge** — `window.OdontoNpm.mountOdontogram(root, opts)` returns a bridge object with `updateConditions()`, `updateSelectedTooth()`, `updateLayout()` methods.
- **Two separate React mounts** on patient detail page — `_odoBridges['react-odo-root-layout']` (square) and `_odoBridges['react-odo-root-odo']` (circle). Both are updated on `saveCondition()`.
- **The SVG custom chart has been removed** — do not re-add `buildChart()` or `svg-chart` references; use React odontogram exclusively.
- **`buildStats(targetId)`** — must be called with explicit ID (`'stats-row-layout'` or `'stats-row-odo'`).
