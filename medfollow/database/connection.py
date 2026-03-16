import aiosqlite
import os
from config import DATABASE_PATH

async def get_db():
    """Yield a database connection for use in FastAPI dependencies."""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """Create all tables if they don't exist."""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

    db = await aiosqlite.connect(DATABASE_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")

    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
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

        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL REFERENCES users(id),
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            date_of_birth DATE NOT NULL,
            gender TEXT CHECK(gender IN ('M', 'F', 'Autre')),
            social_security_number TEXT,
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

        CREATE TABLE IF NOT EXISTS medical_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            type TEXT CHECK(type IN ('medical', 'surgical', 'family', 'allergy')) NOT NULL,
            description TEXT NOT NULL,
            date_recorded DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        CREATE TABLE IF NOT EXISTS appointments (
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

        CREATE TABLE IF NOT EXISTS consultations (
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

        CREATE TABLE IF NOT EXISTS vitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consultation_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            weight REAL,
            height REAL,
            blood_pressure_sys INTEGER,
            blood_pressure_dia INTEGER,
            heart_rate INTEGER,
            temperature REAL,
            spo2 REAL,
            notes TEXT,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (consultation_id) REFERENCES consultations(id),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        CREATE TABLE IF NOT EXISTS prescriptions (
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

        CREATE TABLE IF NOT EXISTS prescription_items (
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

        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            active_ingredient TEXT,
            category TEXT,
            contraindications TEXT,
            common_dosages TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS documents (
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

        CREATE TABLE IF NOT EXISTS messages (
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

        CREATE TABLE IF NOT EXISTS message_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES messages(id)
        );

        CREATE TABLE IF NOT EXISTS medical_acts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            base_price REAL NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS invoices (
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

        CREATE TABLE IF NOT EXISTS invoice_items (
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

        CREATE TABLE IF NOT EXISTS payments (
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

        CREATE TABLE IF NOT EXISTS questionnaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            specialty TEXT,
            structure TEXT NOT NULL,
            created_by INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS questionnaire_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questionnaire_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            appointment_id INTEGER,
            responses TEXT NOT NULL,
            access_token TEXT UNIQUE NOT NULL,
            submitted_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (questionnaire_id) REFERENCES questionnaires(id),
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (appointment_id) REFERENCES appointments(id)
        );

        CREATE TABLE IF NOT EXISTS consultation_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT,
            structure TEXT NOT NULL,
            created_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
    """)

    await db.commit()

    # Migration: add doctor_id to patients if missing
    try:
        await db.execute("ALTER TABLE patients ADD COLUMN doctor_id INTEGER REFERENCES users(id)")
        await db.commit()
    except Exception:
        pass  # Column already exists

    # Dental tables migration
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS dental_teeth (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            tooth_number INTEGER NOT NULL,
            condition TEXT DEFAULT 'sain',
            notes TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            UNIQUE(patient_id, tooth_number)
        );
        CREATE TABLE IF NOT EXISTS dental_treatments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            tooth_number INTEGER NOT NULL,
            treatment_type TEXT NOT NULL,
            description TEXT,
            treatment_date DATE DEFAULT CURRENT_DATE,
            doctor_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (doctor_id) REFERENCES users(id)
        );
    """)
    await db.commit()

    await db.close()
