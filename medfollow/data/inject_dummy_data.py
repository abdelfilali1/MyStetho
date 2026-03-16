"""
Inject dummy data for dentist Mahmoud Harrachi (id=2) into medfollow.db
Run: python inject_dummy_data.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "medfollow.db")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ------------------------------------------------------------------ #
    # 0. Inspect schema so we know column names
    # ------------------------------------------------------------------ #
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in c.fetchall()]
    print("=== Tables found ===")
    for t in tables:
        c.execute(f"PRAGMA table_info({t})")
        cols = [(row[1], row[2]) for row in c.fetchall()]
        print(f"  {t}: {cols}")

    # ------------------------------------------------------------------ #
    # 1. Check & clean existing patients for doctor_id=2
    # ------------------------------------------------------------------ #
    c.execute("SELECT id, first_name, last_name FROM patients WHERE doctor_id = 2")
    existing = c.fetchall()
    if existing:
        print(f"\n=== Existing patients for doctor_id=2 ({len(existing)} found) ===")
        for row in existing:
            print(f"  id={row[0]}  {row[1]} {row[2]}")
        existing_ids = [row[0] for row in existing]
        ids_str = ",".join(str(i) for i in existing_ids)
        # Delete cascading data first
        for tbl in ("dental_teeth", "dental_treatments"):
            try:
                c.execute(f"DELETE FROM {tbl} WHERE patient_id IN ({ids_str})")
                print(f"  Deleted rows from {tbl} for those patients")
            except Exception as e:
                print(f"  (skip {tbl}: {e})")
        try:
            c.execute(f"DELETE FROM appointments WHERE patient_id IN ({ids_str}) AND doctor_id = 2")
            print("  Deleted appointments for those patients")
        except Exception as e:
            print(f"  (skip appointments: {e})")
        c.execute(f"DELETE FROM patients WHERE doctor_id = 2")
        print("  Deleted existing patients for doctor_id=2")
    else:
        print("\nNo existing patients for doctor_id=2 — starting fresh.")

    # ------------------------------------------------------------------ #
    # 2. Insert patients
    # ------------------------------------------------------------------ #
    # Detect available columns (some builds may differ)
    c.execute("PRAGMA table_info(patients)")
    patient_cols = {row[1] for row in c.fetchall()}
    print(f"\nPatient columns: {sorted(patient_cols)}")

    patients_data = [
        (2, 'Fatima Zahra', 'Benali',  '1985-03-12', 'F', '06-12-34-56-78', 'fz.benali@gmail.com',    'Casablanca',  'Patiente régulière, anxieuse chez le dentiste'),
        (2, 'Youssef',      'Oulhaj',  '1979-07-22', 'M', '06-23-45-67-89', 'y.oulhaj@hotmail.com',   'Rabat',       'Bruxisme nocturne signalé'),
        (2, 'Aicha',        'Tazi',    '1992-11-05', 'F', '06-34-56-78-90', 'aicha.tazi@gmail.com',   'Casablanca',  'Sensibilité dentaire importante'),
        (2, 'Khalid',       'Berrada', '1968-01-30', 'M', '06-45-67-89-01', 'k.berrada@gmail.com',    'Casablanca',  'Diabétique - précautions nécessaires'),
        (2, 'Nadia',        'Squalli', '2001-06-18', 'F', '06-56-78-90-12', 'nadia.squalli@gmail.com','Mohammedia',  'Première visite, orthodontie en cours'),
        (2, 'Omar',         'Hajji',   '1955-09-14', 'M', '06-67-89-01-23', 'omar.hajji@gmail.com',   'Casablanca',  'Prothèse partielle existante'),
        (2, 'Samira',       'Idrissi', '1988-04-25', 'F', '06-78-90-12-34', 'samira.idrissi@gmail.com','Kenitra',    'Grossesse - 6 mois, soins conservateurs uniquement'),
        (2, 'Mehdi',        'Zouiten', '1995-12-03', 'M', '06-89-01-23-45', 'mehdi.zouiten@gmail.com','Casablanca',  'Sport de contact - port de gouttière recommandé'),
    ]

    # Build INSERT dynamically based on which columns exist
    # Required: doctor_id, first_name, last_name; optional extras
    optional_map = {
        'date_of_birth': 3,
        'dob': 3,
        'gender': 4,
        'sex': 4,
        'phone': 5,
        'phone_number': 5,
        'email': 6,
        'city': 7,
        'notes': 8,
    }

    insert_cols = ['doctor_id', 'first_name', 'last_name']
    insert_idx  = [0, 1, 2]
    for col, idx in optional_map.items():
        if col in patient_cols and col not in insert_cols:
            insert_cols.append(col)
            insert_idx.append(idx)

    col_str  = ", ".join(insert_cols)
    placeholder = ", ".join(["?"] * len(insert_cols))
    sql = f"INSERT INTO patients ({col_str}) VALUES ({placeholder})"
    print(f"Patient INSERT SQL: {sql}")

    patient_ids = []
    for row in patients_data:
        values = tuple(row[i] for i in insert_idx)
        c.execute(sql, values)
        patient_ids.append(c.lastrowid)

    p1, p2, p3, p4, p5, p6, p7, p8 = patient_ids
    print(f"\n=== Inserted patients ===")
    names = ['Fatima Zahra Benali', 'Youssef Oulhaj', 'Aicha Tazi', 'Khalid Berrada',
             'Nadia Squalli', 'Omar Hajji', 'Samira Idrissi', 'Mehdi Zouiten']
    for pid, name in zip(patient_ids, names):
        print(f"  id={pid}  {name}")

    # ------------------------------------------------------------------ #
    # 3. Dental teeth
    # ------------------------------------------------------------------ #
    c.execute("PRAGMA table_info(dental_teeth)")
    teeth_cols = {row[1] for row in c.fetchall()}
    print(f"\nDental_teeth columns: {sorted(teeth_cols)}")

    # Determine condition column name
    condition_col = 'condition'
    for candidate in ('condition', 'status', 'state', 'tooth_condition', 'condition_type'):
        if candidate in teeth_cols:
            condition_col = candidate
            break

    # (patient_id, tooth_number, condition)
    teeth_data = [
        # Fatima Zahra Benali (p1)
        (p1, 16, 'carie'),
        (p1, 26, 'couronne'),
        (p1, 36, 'obturation'),
        (p1, 46, 'obturation'),
        (p1, 17, 'extraction'),
        # Youssef Oulhaj (p2)
        (p2, 14, 'carie'),
        (p2, 24, 'carie'),
        (p2, 36, 'couronne'),
        (p2, 46, 'couronne'),
        (p2, 18, 'extraction'),
        (p2, 28, 'extraction'),
        (p2, 15, 'devitalise'),
        # Aicha Tazi (p3)
        (p3, 11, 'obturation'),
        (p3, 21, 'obturation'),
        (p3, 16, 'couronne'),
        (p3, 26, 'obturation_amalgame'),
        (p3, 36, 'obturation_amalgame'),
        (p3, 37, 'carie'),
        # Khalid Berrada (p4)
        (p4, 16, 'extraction'),
        (p4, 26, 'extraction'),
        (p4, 36, 'implant'),
        (p4, 46, 'implant'),
        (p4, 14, 'devitalise'),
        (p4, 24, 'devitalise'),
        (p4, 17, 'extraction'),
        (p4, 27, 'extraction'),
        (p4, 47, 'bridge'),
        (p4, 48, 'bridge'),
        # Nadia Squalli (p5)
        (p5, 13, 'carie'),
        (p5, 23, 'carie'),
        # Omar Hajji (p6)
        (p6, 16, 'extraction'),
        (p6, 17, 'extraction'),
        (p6, 18, 'extraction'),
        (p6, 26, 'extraction'),
        (p6, 27, 'extraction'),
        (p6, 28, 'extraction'),
        (p6, 36, 'couronne'),
        (p6, 46, 'couronne'),
        (p6, 35, 'devitalise'),
        (p6, 45, 'devitalise'),
        (p6, 14, 'obturation_amalgame'),
        (p6, 24, 'obturation_amalgame'),
        # Samira Idrissi (p7)
        (p7, 36, 'carie'),
        (p7, 46, 'carie'),
        # Mehdi Zouiten (p8)
        (p8, 11, 'fracture'),
        (p8, 21, 'fracture'),
        (p8, 16, 'obturation'),
        (p8, 26, 'obturation'),
    ]

    # Figure out which columns exist for dental_teeth insert
    teeth_insert_cols = ['patient_id', 'tooth_number', condition_col]
    # Some schemas may use tooth_num instead of tooth_number
    if 'tooth_number' not in teeth_cols:
        for candidate in ('tooth_num', 'tooth_id', 'number', 'tooth_no'):
            if candidate in teeth_cols:
                teeth_insert_cols[1] = candidate
                break

    t_col_str     = ", ".join(teeth_insert_cols)
    t_placeholder = ", ".join(["?"] * len(teeth_insert_cols))
    teeth_sql = f"INSERT OR IGNORE INTO dental_teeth ({t_col_str}) VALUES ({t_placeholder})"
    print(f"Teeth INSERT SQL: {teeth_sql}")

    teeth_inserted = 0
    for row in teeth_data:
        try:
            c.execute(teeth_sql, row)
            teeth_inserted += 1
        except Exception as e:
            print(f"  WARN teeth {row}: {e}")

    print(f"  Inserted {teeth_inserted} tooth records")

    # ------------------------------------------------------------------ #
    # 4. Dental treatments
    # ------------------------------------------------------------------ #
    c.execute("PRAGMA table_info(dental_treatments)")
    treat_cols = {row[1] for row in c.fetchall()}
    print(f"\nDental_treatments columns: {sorted(treat_cols)}")

    # (patient_id, doctor_id, tooth_number, treatment_type, description, treatment_date)
    treatments_data = [
        # Fatima Zahra (p1)
        (p1, 2, 16, 'Détartrage',           'Détartrage complet + polissage',                    '2024-09-15'),
        (p1, 2, 16, 'Obturation composite',  'Obturation mésio-occlusale dent 16',                '2024-10-02'),
        (p1, 2, 26, 'Pose couronne',          'Couronne céramique sur 26 après dévitalisation',    '2024-11-20'),
        (p1, 2, 36, 'Obturation composite',  'Obturation occlusale composite A2',                 '2025-01-08'),
        # Youssef Oulhaj (p2)
        (p2, 2, 36, 'Pose couronne',          'Couronne zircone 36',                               '2024-08-10'),
        (p2, 2, 46, 'Pose couronne',          'Couronne zircone 46',                               '2024-08-10'),
        (p2, 2, 14, 'Examen',                 'Carie diagnostiquée, traitement prévu',             '2025-02-14'),
        (p2, 2, 18, 'Extraction',             'Extraction dent de sagesse 18 sous anesthésie locale','2024-06-05'),
        # Aicha Tazi (p3)
        (p3, 2, 16, 'Traitement endodontique','Dévitalisation sur 16 - 3 séances',                '2024-07-22'),
        (p3, 2, 16, 'Pose couronne',          'Couronne céramo-métallique 16',                     '2024-09-30'),
        (p3, 2, 11, 'Obturation composite',  'Obturation composite bord incisif',                 '2025-01-15'),
        # Khalid Berrada (p4)
        (p4, 2, 36, 'Pose implant',           'Implant Nobel Biocare 36 - chirurgie',              '2023-11-12'),
        (p4, 2, 46, 'Pose implant',           'Implant Nobel Biocare 46 - chirurgie',              '2024-01-20'),
        (p4, 2, 36, 'Radiographie',           'Contrôle ostéo-intégration implant 36',             '2024-06-15'),
        # Mehdi Zouiten (p8)
        (p8, 2, 11, 'Examen',                 'Fracture coronaire suite traumatisme sport - 11 et 21','2025-03-01'),
        (p8, 2, 11, 'Radiographie',           'Bilan radiographique post-traumatique',             '2025-03-01'),
    ]

    # Map column names (handle variations)
    treat_col_candidates = {
        'patient_id':      'patient_id',
        'doctor_id':       'doctor_id',
        'tooth_number':    ('tooth_number', 'tooth_num', 'tooth_id', 'number', 'tooth_no'),
        'treatment_type':  ('treatment_type', 'type', 'name', 'treatment_name', 'titre', 'title'),
        'description':     ('description', 'notes', 'details', 'comment'),
        'treatment_date':  ('treatment_date', 'date', 'created_at', 'date_traitement'),
    }

    resolved = {}
    for key, candidates in treat_col_candidates.items():
        if isinstance(candidates, str):
            resolved[key] = candidates
        else:
            for cand in candidates:
                if cand in treat_cols:
                    resolved[key] = cand
                    break
            else:
                resolved[key] = None

    print(f"  Resolved treatment columns: {resolved}")

    t_cols = [v for v in resolved.values() if v is not None]
    t_col_str     = ", ".join(t_cols)
    t_placeholder = ", ".join(["?"] * len(t_cols))
    treat_sql = f"INSERT OR IGNORE INTO dental_treatments ({t_col_str}) VALUES ({t_placeholder})"
    print(f"Treatment INSERT SQL: {treat_sql}")

    treat_inserted = 0
    # Build value tuples matching resolved column order
    col_order = list(resolved.keys())
    row_template_indices = [0, 1, 2, 3, 4, 5]  # patient_id, doctor_id, tooth, type, desc, date

    for row in treatments_data:
        values = []
        for key in col_order:
            if resolved[key] is None:
                continue
            idx = col_order.index(key)
            values.append(row[idx])
        try:
            c.execute(treat_sql, values)
            treat_inserted += 1
        except Exception as e:
            print(f"  WARN treatment {row[:3]}: {e}")

    print(f"  Inserted {treat_inserted} treatment records")

    # ------------------------------------------------------------------ #
    # 5. Appointments
    # ------------------------------------------------------------------ #
    c.execute("PRAGMA table_info(appointments)")
    appt_cols = {row[1] for row in c.fetchall()}
    print(f"\nAppointments columns: {sorted(appt_cols)}")

    # (patient_id, doctor_id, title, appointment_type, start_datetime, end_datetime, status, notes)
    appointments_data = [
        # Today 2026-03-16
        (p1, 2, 'Détartrage',                    'consultation', '2026-03-16 09:00', '2026-03-16 09:30', 'confirme',  'Détartrage semestriel'),
        (p2, 2, 'Obturation composite dent 14',  'intervention', '2026-03-16 10:00', '2026-03-16 11:00', 'confirme',  'Carie 14 à traiter'),
        (p3, 2, 'Contrôle couronne 16',          'suivi',        '2026-03-16 11:30', '2026-03-16 12:00', 'planifie',  ''),
        (p4, 2, 'Contrôle implants',             'suivi',        '2026-03-16 14:00', '2026-03-16 14:30', 'confirme',  'Bilan annuel implants 36/46'),
        # Tomorrow 2026-03-17
        (p5, 2, 'Première consultation',          'consultation', '2026-03-17 09:00', '2026-03-17 09:45', 'planifie',  'Bilan complet + caries'),
        (p6, 2, 'Prothèse - essayage',           'suivi',        '2026-03-17 10:30', '2026-03-17 11:00', 'planifie',  ''),
        (p7, 2, 'Soin carie 36',                 'intervention', '2026-03-17 14:00', '2026-03-17 14:45', 'confirme',  'Grossesse 6 mois - anesthésie sans adrénaline'),
        # Day after tomorrow 2026-03-18
        (p8, 2, 'Gouttière occlusale',           'consultation', '2026-03-18 09:30', '2026-03-18 10:00', 'planifie',  'Livraison gouttière bruxisme'),
        (p1, 2, 'Bilan parodontal',              'consultation', '2026-03-18 11:00', '2026-03-18 11:30', 'planifie',  ''),
        # Past
        (p1, 2, 'Détartrage',                    'consultation', '2026-02-10 09:00', '2026-02-10 09:30', 'termine',   ''),
        (p2, 2, 'Pose couronnes',                'intervention', '2026-01-15 10:00', '2026-01-15 12:00', 'termine',   'Couronnes 36 et 46 posées'),
        (p4, 2, 'Contrôle implants',             'suivi',        '2025-12-10 14:00', '2025-12-10 14:30', 'termine',   ''),
    ]

    # Map appointment column names
    appt_col_candidates = {
        'patient_id':       'patient_id',
        'doctor_id':        'doctor_id',
        'title':            ('title', 'name', 'titre', 'subject'),
        'appointment_type': ('appointment_type', 'type', 'appt_type', 'consultation_type'),
        'start_datetime':   ('start_datetime', 'start_time', 'start', 'datetime_start', 'appointment_date', 'date_heure_debut'),
        'end_datetime':     ('end_datetime',   'end_time',   'end',   'datetime_end',   'date_heure_fin'),
        'status':           ('status', 'state', 'etat'),
        'notes':            ('notes', 'description', 'comment', 'details'),
    }

    appt_resolved = {}
    for key, candidates in appt_col_candidates.items():
        if isinstance(candidates, str):
            appt_resolved[key] = candidates if candidates in appt_cols else None
        else:
            for cand in candidates:
                if cand in appt_cols:
                    appt_resolved[key] = cand
                    break
            else:
                appt_resolved[key] = None

    print(f"  Resolved appointment columns: {appt_resolved}")

    a_cols = [v for v in appt_resolved.values() if v is not None]
    a_col_str     = ", ".join(a_cols)
    a_placeholder = ", ".join(["?"] * len(a_cols))
    appt_sql = f"INSERT OR IGNORE INTO appointments ({a_col_str}) VALUES ({a_placeholder})"
    print(f"Appointment INSERT SQL: {appt_sql}")

    appt_keys = list(appt_resolved.keys())
    appt_inserted = 0
    for row in appointments_data:
        values = []
        for key in appt_keys:
            if appt_resolved[key] is None:
                continue
            idx = appt_keys.index(key)
            values.append(row[idx])
        try:
            c.execute(appt_sql, values)
            appt_inserted += 1
        except Exception as e:
            print(f"  WARN appt {row[:3]}: {e}")

    print(f"  Inserted {appt_inserted} appointment records")

    # ------------------------------------------------------------------ #
    # Commit & summary
    # ------------------------------------------------------------------ #
    conn.commit()
    conn.close()

    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    print(f"  Patients inserted  : {len(patient_ids)}")
    print(f"  Tooth records      : {teeth_inserted}")
    print(f"  Treatments         : {treat_inserted}")
    print(f"  Appointments       : {appt_inserted}")
    print(f"  Patient IDs        : {patient_ids}")
    print("Done!")


if __name__ == "__main__":
    main()
