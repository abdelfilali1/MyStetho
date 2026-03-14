# PRD — MedFollow : Logiciel de Gestion de Cabinet Médical

**Version** : 1.0
**Date** : 2026-03-14
**Statut** : Brouillon — En attente de validation

---

## 1. Vision du Produit

**MedFollow** est un logiciel de gestion de cabinet médical destiné aux praticiens (chirurgiens, spécialistes, médecins généralistes). Il centralise la gestion des dossiers patients, la planification des rendez-vous, la messagerie sécurisée, la prescription, la facturation et le suivi médical — le tout en local avec une base SQLite.

**Inspiré de** : [Follow.fr](https://www.follow.fr/) — plateforme cloud utilisée par 5 000+ professionnels de santé en France.

**Stack technique** :
- **Backend** : Python (FastAPI)
- **Frontend** : Interface web (HTML/CSS/JS) servie par le backend Python
- **Base de données** : SQLite (locale)
- **Architecture** : Application de bureau servie localement (localhost)

---

## 2. Utilisateurs Cibles

| Persona | Description |
|---------|-------------|
| **Médecin / Spécialiste** | Utilisateur principal. Gère ses patients, consultations, prescriptions et documents |
| **Secrétaire / Assistant(e)** | Gère l'agenda, l'accueil des patients, la facturation. Accès limité aux données médicales |
| **Patient** (futur) | Accès aux questionnaires pré-consultation via un lien partagé (phase ultérieure) |

---

## 3. Modules Fonctionnels

### 3.1 — Authentification & Gestion des Utilisateurs

**Description** : Système de connexion sécurisé avec gestion des rôles.

| Fonctionnalité | Détails |
|----------------|---------|
| Connexion | Login par email + mot de passe hashé (bcrypt) |
| Rôles | `médecin`, `secrétaire`, `admin` |
| Permissions | Accès granulaire par rôle (ex: secrétaire ne voit pas les notes médicales confidentielles) |
| Session | Token JWT avec expiration configurable |
| Premier lancement | Assistant de configuration initiale (création du compte admin) |

**Schéma SQLite** :
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    role TEXT CHECK(role IN ('medecin', 'secretaire', 'admin')) NOT NULL,
    specialty TEXT,
    phone TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

### 3.2 — Gestion des Dossiers Patients

**Description** : Module central. Chaque patient possède un dossier complet avec historique médical.

| Fonctionnalité | Détails |
|----------------|---------|
| Fiche patient | Identité, coordonnées, numéro de sécurité sociale, médecin traitant, mutuelle |
| Antécédents | Médicaux, chirurgicaux, familiaux, allergies |
| Historique | Timeline chronologique de toutes les consultations et interventions |
| Recherche | Recherche rapide par nom, prénom, date de naissance, n° sécu |
| Import/Export | Export CSV/PDF d'un dossier patient |
| Notes médicales | Notes libres attachées au dossier, visibles uniquement par le médecin |

**Schéma SQLite** :
```sql
CREATE TABLE patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    date_of_birth DATE NOT NULL,
    gender TEXT CHECK(gender IN ('M', 'F', 'Autre')),
    social_security_number TEXT UNIQUE,
    email TEXT,
    phone TEXT,
    address TEXT,
    city TEXT,
    postal_code TEXT,
    blood_type TEXT,
    referring_doctor TEXT,
    insurance_name TEXT,
    insurance_number TEXT,
    emergency_contact_name TEXT,
    emergency_contact_phone TEXT,
    notes TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE medical_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    type TEXT CHECK(type IN ('medical', 'surgical', 'family', 'allergy')) NOT NULL,
    description TEXT NOT NULL,
    date_recorded DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id)
);
```

---

### 3.3 — Agenda / Calendrier

**Description** : Gestion des rendez-vous avec vue jour/semaine/mois.

| Fonctionnalité | Détails |
|----------------|---------|
| Vues | Jour, semaine, mois |
| Création RDV | Patient, motif, durée, praticien, salle |
| Types de RDV | Consultation, suivi, intervention, urgence (code couleur) |
| Récurrence | RDV récurrents (suivi mensuel, etc.) |
| Recherche | Trouver le prochain créneau disponible |
| Conflits | Détection automatique des chevauchements |
| Statistiques | Nombre de RDV par jour/semaine/mois |

**Schéma SQLite** :
```sql
CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    appointment_type TEXT CHECK(appointment_type IN ('consultation', 'suivi', 'intervention', 'urgence')) DEFAULT 'consultation',
    start_datetime DATETIME NOT NULL,
    end_datetime DATETIME NOT NULL,
    room TEXT,
    status TEXT CHECK(status IN ('planifie', 'confirme', 'en_cours', 'termine', 'annule', 'absent')) DEFAULT 'planifie',
    notes TEXT,
    is_recurring BOOLEAN DEFAULT 0,
    recurrence_rule TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES users(id)
);
```

---

### 3.4 — Consultations & Comptes-Rendus

**Description** : Saisie structurée des consultations avec génération de comptes-rendus.

| Fonctionnalité | Détails |
|----------------|---------|
| Formulaire | Motif, examen clinique, diagnostic, plan de traitement |
| Templates | Modèles de consultation par spécialité (personnalisables) |
| Comptes-rendus | Génération automatique en PDF |
| Mesures | Saisie de constantes (poids, taille, tension, température, etc.) |
| Historique | Accès rapide aux consultations précédentes du même patient |
| Liaison | Lien direct vers la prescription et les documents |

**Schéma SQLite** :
```sql
CREATE TABLE consultations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    appointment_id INTEGER,
    consultation_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    symptoms TEXT,
    clinical_exam TEXT,
    diagnosis TEXT,
    treatment_plan TEXT,
    notes TEXT,
    template_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES users(id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(id)
);

CREATE TABLE vitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consultation_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    weight REAL,           -- kg
    height REAL,           -- cm
    blood_pressure_sys INTEGER,
    blood_pressure_dia INTEGER,
    heart_rate INTEGER,
    temperature REAL,      -- °C
    spo2 REAL,             -- %
    notes TEXT,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (consultation_id) REFERENCES consultations(id),
    FOREIGN KEY (patient_id) REFERENCES patients(id)
);

CREATE TABLE consultation_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    specialty TEXT,
    structure TEXT NOT NULL,  -- JSON: champs du formulaire
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);
```

---

### 3.5 — Prescriptions / Ordonnances

**Description** : Création et gestion des ordonnances médicales.

| Fonctionnalité | Détails |
|----------------|---------|
| Saisie | Médicament, posologie, durée, renouvellement |
| Base médicaments | Base locale de médicaments couramment prescrits (extensible) |
| Interactions | Alertes basiques sur les interactions connues et allergies patient |
| Historique | Toutes les ordonnances d'un patient accessibles |
| Impression/PDF | Génération d'ordonnance formatée en PDF |
| Ordonnances types | Modèles de prescription réutilisables |

**Schéma SQLite** :
```sql
CREATE TABLE prescriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consultation_id INTEGER,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    prescription_date DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    is_renewable BOOLEAN DEFAULT 0,
    renewal_count INTEGER DEFAULT 0,
    status TEXT CHECK(status IN ('active', 'terminee', 'annulee')) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (consultation_id) REFERENCES consultations(id),
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES users(id)
);

CREATE TABLE prescription_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL,
    medication_name TEXT NOT NULL,
    dosage TEXT NOT NULL,
    frequency TEXT NOT NULL,
    duration TEXT,
    instructions TEXT,
    quantity INTEGER,
    FOREIGN KEY (prescription_id) REFERENCES prescriptions(id)
);

CREATE TABLE medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active_ingredient TEXT,
    category TEXT,
    contraindications TEXT,
    common_dosages TEXT,  -- JSON
    notes TEXT
);
```

---

### 3.6 — Gestion des Documents

**Description** : Stockage et organisation des documents médicaux.

| Fonctionnalité | Détails |
|----------------|---------|
| Upload | Import de fichiers (PDF, images, DICOM simplifié) |
| Catégories | Radio, labo, courrier, compte-rendu opératoire, autre |
| Association | Lié au patient et optionnellement à une consultation |
| Prévisualisation | Affichage intégré des PDF et images |
| Recherche | Par patient, date, type, nom de fichier |
| Stockage | Dossier local organisé par patient |

**Schéma SQLite** :
```sql
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    consultation_id INTEGER,
    title TEXT NOT NULL,
    category TEXT CHECK(category IN ('radio', 'labo', 'courrier', 'compte_rendu', 'ordonnance', 'autre')) NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    description TEXT,
    uploaded_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (consultation_id) REFERENCES consultations(id),
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
);
```

---

### 3.7 — Messagerie Interne Sécurisée

**Description** : Communication entre praticiens et secrétaires au sein du cabinet.

| Fonctionnalité | Détails |
|----------------|---------|
| Messages | Envoi/réception entre utilisateurs du système |
| Pièces jointes | Possibilité d'attacher des documents |
| Lien patient | Associer un message à un dossier patient |
| Notifications | Badge de messages non lus |
| Recherche | Par expéditeur, patient, contenu |

**Schéma SQLite** :
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    patient_id INTEGER,
    subject TEXT,
    body TEXT NOT NULL,
    is_read BOOLEAN DEFAULT 0,
    parent_message_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (recipient_id) REFERENCES users(id),
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (parent_message_id) REFERENCES messages(id)
);

CREATE TABLE message_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);
```

---

### 3.8 — Facturation & Paiements

**Description** : Gestion des actes, factures et paiements.

| Fonctionnalité | Détails |
|----------------|---------|
| Actes médicaux | Catalogue d'actes avec tarifs (CCAM/NGAP simplifié) |
| Facturation | Création de factures liées aux consultations |
| Paiements | Enregistrement des paiements (espèces, carte, chèque, virement) |
| Tiers payant | Marquage des actes en tiers payant |
| Suivi | Tableau de bord des impayés et encaissements |
| Export | Export comptable CSV pour le comptable |

**Schéma SQLite** :
```sql
CREATE TABLE medical_acts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    base_price REAL NOT NULL,
    description TEXT
);

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    patient_id INTEGER NOT NULL,
    consultation_id INTEGER,
    doctor_id INTEGER NOT NULL,
    invoice_date DATE DEFAULT CURRENT_DATE,
    total_amount REAL NOT NULL,
    paid_amount REAL DEFAULT 0,
    status TEXT CHECK(status IN ('brouillon', 'emise', 'payee', 'partiellement_payee', 'annulee')) DEFAULT 'brouillon',
    tiers_payant BOOLEAN DEFAULT 0,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (consultation_id) REFERENCES consultations(id),
    FOREIGN KEY (doctor_id) REFERENCES users(id)
);

CREATE TABLE invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    medical_act_id INTEGER,
    description TEXT NOT NULL,
    quantity INTEGER DEFAULT 1,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (medical_act_id) REFERENCES medical_acts(id)
);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    payment_method TEXT CHECK(payment_method IN ('especes', 'carte', 'cheque', 'virement', 'tiers_payant')) NOT NULL,
    payment_date DATE DEFAULT CURRENT_DATE,
    reference TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id)
);
```

---

### 3.9 — Questionnaires Patients (Pré-consultation)

**Description** : Formulaires personnalisés envoyés au patient avant sa consultation.

| Fonctionnalité | Détails |
|----------------|---------|
| Création | Éditeur de questionnaires avec différents types de champs (texte, choix, échelle) |
| Templates | Modèles par spécialité ou type de consultation |
| Partage | Génération d'un lien unique accessible sans authentification |
| Réponses | Réponses automatiquement rattachées au dossier patient |
| Visualisation | Affichage des réponses dans la consultation |

**Schéma SQLite** :
```sql
CREATE TABLE questionnaires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    specialty TEXT,
    structure TEXT NOT NULL,  -- JSON: définition des champs
    created_by INTEGER,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE questionnaire_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    questionnaire_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    appointment_id INTEGER,
    responses TEXT NOT NULL,  -- JSON: réponses
    access_token TEXT UNIQUE NOT NULL,
    submitted_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (questionnaire_id) REFERENCES questionnaires(id),
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(id)
);
```

---

### 3.10 — Tableau de Bord & Statistiques

**Description** : Vue d'ensemble de l'activité du cabinet.

| Fonctionnalité | Détails |
|----------------|---------|
| Dashboard | RDV du jour, patients en attente, messages non lus, rappels |
| Stats activité | Nombre de consultations par période, par type |
| Stats financières | Chiffre d'affaires, impayés, répartition par acte |
| Stats patients | Nouveaux patients, répartition par âge/genre |
| Export | Export des statistiques en CSV/PDF |

---

## 4. Architecture Technique

```
medfollow/
├── main.py                    # Point d'entrée, lancement du serveur
├── requirements.txt
├── config.py                  # Configuration (port, DB path, secret key)
├── database/
│   ├── __init__.py
│   ├── connection.py          # Connexion SQLite, création des tables
│   └── seed.py                # Données initiales (actes médicaux, etc.)
├── models/                    # Modèles Pydantic
│   ├── user.py
│   ├── patient.py
│   ├── appointment.py
│   ├── consultation.py
│   ├── prescription.py
│   ├── document.py
│   ├── message.py
│   ├── invoice.py
│   └── questionnaire.py
├── routers/                   # Endpoints FastAPI
│   ├── auth.py
│   ├── users.py
│   ├── patients.py
│   ├── appointments.py
│   ├── consultations.py
│   ├── prescriptions.py
│   ├── documents.py
│   ├── messages.py
│   ├── invoices.py
│   ├── questionnaires.py
│   └── dashboard.py
├── services/                  # Logique métier
│   ├── auth_service.py
│   ├── pdf_service.py         # Génération PDF (ReportLab/WeasyPrint)
│   └── stats_service.py
├── static/                    # Assets frontend
│   ├── css/
│   ├── js/
│   └── img/
├── templates/                 # Templates HTML (Jinja2)
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── patients/
│   ├── appointments/
│   ├── consultations/
│   ├── prescriptions/
│   ├── documents/
│   ├── messages/
│   ├── invoices/
│   └── questionnaires/
├── uploads/                   # Documents uploadés (organisés par patient)
│   └── patient_{id}/
└── data/
    └── medfollow.db           # Base SQLite
```

---

## 5. Dépendances Python

| Package | Usage |
|---------|-------|
| `fastapi` | Framework web / API REST |
| `uvicorn` | Serveur ASGI |
| `jinja2` | Templates HTML |
| `python-multipart` | Upload de fichiers |
| `pyjwt` | Authentification JWT |
| `bcrypt` | Hashage des mots de passe |
| `reportlab` ou `weasyprint` | Génération PDF |
| `pydantic` | Validation des données |
| `python-dateutil` | Manipulation des dates |
| `aiosqlite` | Accès SQLite asynchrone |

---

## 6. Exigences Non-Fonctionnelles

| Catégorie | Exigence |
|-----------|----------|
| **Sécurité** | Mots de passe hashés (bcrypt), sessions JWT, CSRF protection, données sensibles jamais en clair |
| **Performance** | Temps de réponse < 200ms pour les opérations courantes |
| **Sauvegarde** | Export/import complet de la base SQLite (backup one-click) |
| **Portabilité** | Fonctionne sur Windows, macOS, Linux sans dépendances système lourdes |
| **Accessibilité** | Interface responsive, utilisable sur tablette |
| **Données** | Toutes les données restent locales, aucun envoi externe |

---

## 7. Plan de Livraison par Phases

### Phase 1 — MVP (Fondations)
- [x] Structure du projet et configuration
- [ ] Authentification (login, rôles, sessions)
- [ ] Gestion des patients (CRUD complet)
- [ ] Agenda / Calendrier (vue jour/semaine, création RDV)
- [ ] Tableau de bord basique

### Phase 2 — Cœur Médical
- [ ] Consultations & comptes-rendus
- [ ] Prescriptions / Ordonnances
- [ ] Gestion des documents (upload, catégorisation)
- [ ] Génération PDF (ordonnances, comptes-rendus)

### Phase 3 — Communication & Finance
- [ ] Messagerie interne
- [ ] Facturation & paiements
- [ ] Export comptable

### Phase 4 — Fonctionnalités Avancées
- [ ] Questionnaires patients (pré-consultation)
- [ ] Statistiques avancées et graphiques
- [ ] Templates de consultation par spécialité
- [ ] Base de médicaments avec interactions

---

## 8. Contraintes & Décisions

| Décision | Justification |
|----------|---------------|
| SQLite plutôt que PostgreSQL | Simplicité, zéro configuration, portable. Migration possible ultérieurement |
| FastAPI plutôt que Django | Plus léger, API-first, async natif, meilleure perf pour une app locale |
| Jinja2 + JS vanilla plutôt que React/Vue | Moins de complexité, pas de build frontend, rendu côté serveur |
| Données 100% locales | Confidentialité médicale, pas de dépendance cloud |

---

## 9. Risques Identifiés

| Risque | Mitigation |
|--------|------------|
| SQLite limité en accès concurrent | Acceptable pour un cabinet (1-5 utilisateurs simultanés). WAL mode activé |
| Perte de données (disque local) | Fonctionnalité de backup automatique + export |
| Conformité RGPD | Données locales = pas de transfert, mais prévoir export/suppression des données patient |
| Taille de la base avec les documents | Les fichiers sont stockés sur disque, seuls les métadonnées sont en base |

---

## 10. Métriques de Succès

- Temps de saisie d'une consultation complète < 5 minutes
- Recherche d'un patient < 2 secondes
- Génération d'une ordonnance PDF < 3 secondes
- Zéro perte de données sur 12 mois d'utilisation

---

*Ce document doit être validé avant le début du développement. Toute modification majeure nécessite une mise à jour de ce PRD.*
