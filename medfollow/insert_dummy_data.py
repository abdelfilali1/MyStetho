"""Insert realistic Moroccan dummy data."""
import sqlite3
from config import DATABASE_PATH

conn = sqlite3.connect(DATABASE_PATH)
c = conn.cursor()

# Avoid duplicate inserts when the seed has already been loaded once.
c.execute("SELECT 1 FROM patients WHERE social_security_number = ", ("185042312345",))
if c.fetchone():
    print("Dummy data already present. Skipping insert.")
    conn.close()
    raise SystemExit(0)

DOCTOR_ID = 1  # Dr. Hilalou

# -- PATIENTS (15 marocains) --
patients = [
    ("Youssef",  "Bennani",    "1985-04-12", "M", "0661-234567", "youssef.bennani@gmail.com",  "12 Rue Ibn Sina, Gueliz",   "Marrakech", "40000", "A+",  "Dr. Amrani",  "CNSS",        "185042312345", "Fatima Bennani", "0662-345678"),
    ("Fatima",   "El Amrani",  "1992-08-25", "F", "0670-456789", "fatima.elamrani@yahoo.fr",   "45 Bd Zerktouni",           "Casablanca","20000", "O+",  "Dr. Tazi",    "CNOPS",       "292082567890", "Ahmed El Amrani","0671-567890"),
    ("Hassan",   "Chraibi",    "1968-01-03", "M", "0655-678901", None,                          "8 Rue Allal Ben Abdellah",  "Rabat",     "10000", "B+",  "Dr. Hilalou", "Saham Assurance","168010312345","Aicha Chraibi",  "0656-789012"),
    ("Amina",    "Berrada",    "1990-11-17", "F", "0699-012345", "amina.berrada@outlook.com",  "23 Rue de Fes",             "Meknes",    "50000", "AB+", None,          "RMA Watanya", "290111756789", "Rachid Berrada", "0698-123456"),
    ("Karim",    "Fassi Fihri","1975-06-30", "M", "0661-111222", "karim.ff@gmail.com",         "78 Av. Hassan II",          "Fes",       "30000", "O-",  "Dr. Bensouda","CNSS",        "175063034567", None,             None),
    ("Nadia",    "Alaoui",     "1988-03-14", "F", "0677-333444", "nadia.alaoui@gmail.com",     "5 Derb Sidi Bouloukate",    "Tanger",    "90000", "A-",  None,          "Sanad",       "288031490123", "Omar Alaoui",    "0678-444555"),
    ("Omar",     "Tazi",       "1955-12-20", "M", "0650-555666", None,                          "112 Rue Moulay Ismail",     "Casablanca","20100", "B-",  "Dr. Hilalou", "CNOPS",       "155122023456", "Samira Tazi",    "0651-666777"),
    ("Khadija",  "Idrissi",    "2000-07-08", "F", "0688-777888", "khadija.idrissi@gmail.com",  "34 Av. Mohammed V",         "Agadir",    "80000", "O+",  None,          None,          "300070845678", "Mustapha Idrissi","0689-888999"),
    ("Abdellah", "Bouazza",    "1982-09-01", "M", "0665-999000", "a.bouazza@hotmail.com",      "67 Bd Anfa",                "Casablanca","20200", "A+",  "Dr. Bennani", "AXA Assurance","182090156789","Halima Bouazza", "0666-000111"),
    ("Salma",    "Kettani",    "1995-05-22", "F", "0672-222333", "salma.kettani@gmail.com",    "15 Rue Atlas",              "Rabat",     "10020", "AB-", "Dr. Fassi",   "CNSS",        "295052234567", "Youssef Kettani","0673-333444"),
    ("Rachid",   "Lahlou",     "1970-02-14", "M", "0654-444555", None,                          "90 Rue Oqba Ibn Nafiaa",   "Marrakech", "40020", "B+",  "Dr. Hilalou", "Saham Assurance","170021467890","Zahra Lahlou",  "0655-555666"),
    ("Zineb",    "Benkirane",  "1998-10-30", "F", "0690-666777", "zineb.benk@gmail.com",       "3 Rue Imam Malik",          "Oujda",     "60000", "O+",  None,          "CNOPS",       "298103078901", "Mohammed Benkirane","0691-777888"),
    ("Mustapha", "Zouiten",    "1960-04-18", "M", "0644-888999", None,                          "56 Bd de la Resistance",   "Casablanca","20050", "A+",  "Dr. Chraibi", "RMA Watanya", "160041812345", "Fatna Zouiten", "0645-999000"),
    ("Houda",    "Sqalli",     "1987-12-05", "F", "0676-000111", "houda.sqalli@yahoo.fr",      "29 Rue Patrice Lumumba",    "Kenitra",   "14000", "B-",  None,          "CNSS",        "287120534567", "Driss Sqalli",  "0677-111222"),
    ("Driss",    "Benjelloun", "1978-08-11", "M", "0663-222333", "driss.benj@gmail.com",       "41 Av. des FAR",            "Tanger",    "90020", "AB+", "Dr. Alaoui",  "Sanad",       "178081156789", "Naima Benjelloun","0664-333444"),
]

patient_ids = []
for p in patients:
    c.execute("""INSERT INTO patients
        (first_name, last_name, date_of_birth, gender, phone, email, address, city, postal_code,
         blood_type, referring_doctor, insurance_name, social_security_number,
         emergency_contact_name, emergency_contact_phone)
        VALUES (,,,,,,,,,,,,,,)""", p)
    patient_ids.append(c.lastrowid)

# -- MEDICAL HISTORY --
histories = [
    (patient_ids[2],  "medical",  "Hypertension arterielle sous traitement depuis 2010",    "2010-03-15"),
    (patient_ids[2],  "medical",  "Diabete type 2 diagnostique en 2015",                     "2015-06-20"),
    (patient_ids[6],  "medical",  "Insuffisance cardiaque stade II",                          "2018-01-10"),
    (patient_ids[6],  "surgical", "Pontage coronarien en 2019",                               "2019-05-22"),
    (patient_ids[6],  "allergy",  "Allergie a la Penicilline",                                "2000-01-01"),
    (patient_ids[4],  "family",   "Pere decede d'infarctus du myocarde a 58 ans",            "2020-11-01"),
    (patient_ids[4],  "medical",  "Hypercholesterolemie",                                     "2018-09-10"),
    (patient_ids[0],  "allergy",  "Allergie aux sulfamides",                                  "2005-04-12"),
    (patient_ids[1],  "medical",  "Asthme modere depuis l'enfance",                           "2000-01-01"),
    (patient_ids[1],  "family",   "Mere diabetique type 2",                                   "2020-01-01"),
    (patient_ids[9],  "surgical", "Appendicectomie en 2015",                                  "2015-08-14"),
    (patient_ids[10], "medical",  "Lombalgie chronique",                                      "2016-03-01"),
    (patient_ids[10], "medical",  "HTA grade 2 sous bitherapie",                              "2012-07-20"),
    (patient_ids[12], "medical",  "BPCO stade modere - ancien fumeur",                        "2017-10-05"),
    (patient_ids[12], "medical",  "Arthrose du genou bilaterale",                             "2019-02-15"),
    (patient_ids[3],  "allergy",  "Allergie aux acariens",                                    "2010-01-01"),
    (patient_ids[5],  "medical",  "Hypothyroidie sous Levothyrox",                            "2019-06-01"),
    (patient_ids[14], "medical",  "Goutte avec crises recurrentes",                           "2020-04-10"),
]
c.executemany("INSERT INTO medical_history (patient_id, type, description, date_recorded) VALUES (,,,)", histories)

# -- APPOINTMENTS (20 rdv) --
appointments = [
    # Passes (termines)
    (patient_ids[0],  DOCTOR_ID, "Consultation douleur abdominale",  "consultation", "2026-02-10T09:00", "2026-02-10T09:30", "Salle 1", "termine",  None),
    (patient_ids[1],  DOCTOR_ID, "Suivi asthme",                     "suivi",        "2026-02-12T10:00", "2026-02-12T10:30", "Salle 2", "termine",  None),
    (patient_ids[2],  DOCTOR_ID, "Controle HTA + diabete",           "suivi",        "2026-02-15T11:00", "2026-02-15T11:45", "Salle 1", "termine",  "Patient a jeun"),
    (patient_ids[4],  DOCTOR_ID, "Bilan lipidique",                   "consultation", "2026-02-20T14:00", "2026-02-20T14:30", "Salle 1", "termine",  None),
    (patient_ids[6],  DOCTOR_ID, "Suivi cardiaque",                   "suivi",        "2026-02-25T09:00", "2026-02-25T09:45", "Salle 2", "termine",  "ECG a faire"),
    (patient_ids[3],  DOCTOR_ID, "Rhinite allergique",                "consultation", "2026-03-01T10:00", "2026-03-01T10:30", "Salle 1", "termine",  None),
    (patient_ids[10], DOCTOR_ID, "Douleur lombaire",                  "consultation", "2026-03-03T11:00", "2026-03-03T11:30", "Salle 2", "termine",  None),
    (patient_ids[5],  DOCTOR_ID, "Controle thyroide",                 "suivi",        "2026-03-05T15:00", "2026-03-05T15:30", "Salle 1", "termine",  None),
    (patient_ids[12], DOCTOR_ID, "Suivi BPCO",                        "suivi",        "2026-03-07T09:30", "2026-03-07T10:15", "Salle 1", "termine",  None),
    (patient_ids[9],  DOCTOR_ID, "Douleur epigastrique",              "consultation", "2026-03-10T14:00", "2026-03-10T14:30", "Salle 2", "termine",  None),
    # Aujourd'hui
    (patient_ids[7],  DOCTOR_ID, "Premiere consultation",             "consultation", "2026-03-14T10:00", "2026-03-14T10:30", "Salle 1", "confirme", None),
    (patient_ids[11], DOCTOR_ID, "Angine aigue",                      "urgence",      "2026-03-14T11:30", "2026-03-14T12:00", "Salle 2", "planifie", None),
    (patient_ids[14], DOCTOR_ID, "Crise de goutte",                   "urgence",      "2026-03-14T15:00", "2026-03-14T15:30", "Salle 1", "planifie", None),
    # Futurs
    (patient_ids[0],  DOCTOR_ID, "Suivi douleur abdominale",          "suivi",        "2026-03-17T09:00", "2026-03-17T09:30", "Salle 1", "confirme", None),
    (patient_ids[2],  DOCTOR_ID, "Controle trimestriel HTA",          "suivi",        "2026-03-19T10:00", "2026-03-19T10:45", "Salle 2", "confirme", "Apporter bilan sanguin"),
    (patient_ids[13], DOCTOR_ID, "Bilan de sante",                    "consultation", "2026-03-20T14:00", "2026-03-20T14:30", "Salle 1", "planifie", None),
    (patient_ids[8],  DOCTOR_ID, "Consultation migraine",             "consultation", "2026-03-21T11:00", "2026-03-21T11:30", "Salle 2", "planifie", None),
    (patient_ids[6],  DOCTOR_ID, "Controle cardiaque trimestriel",    "suivi",        "2026-03-25T09:00", "2026-03-25T09:45", "Salle 1", "confirme", "Prevoir ECG + echo"),
    (patient_ids[1],  DOCTOR_ID, "Renouvellement ordonnance asthme",  "suivi",        "2026-03-27T10:00", "2026-03-27T10:30", "Salle 2", "planifie", None),
    (patient_ids[5],  DOCTOR_ID, "Suivi thyroide + resultats TSH",    "suivi",        "2026-04-02T14:00", "2026-04-02T14:30", "Salle 1", "planifie", None),
]

appt_ids = []
for a in appointments:
    c.execute("""INSERT INTO appointments
        (patient_id, doctor_id, title, appointment_type, start_datetime, end_datetime, room, status, notes)
        VALUES (,,,,,,,,)""", a)
    appt_ids.append(c.lastrowid)

# -- CONSULTATIONS (10 avec diagnostics realistes) --
consultations_data = [
    (patient_ids[0],  DOCTOR_ID, appt_ids[0], "2026-02-10 09:00", "Douleur abdominale epigastrique depuis 3 jours",
     "Douleur epigastrique irradiant vers le dos, nausees, pas de vomissements, transit normal",
     "Abdomen souple, douleur a la palpation epigastrique, pas de defense, bruits hydro-aeriques normaux",
     "Gastrite aigue", "Omeprazole 20mg 1cp/j pendant 4 semaines + regles hygieno-dietetiques", "Controle dans 1 mois"),

    (patient_ids[1],  DOCTOR_ID, appt_ids[1], "2026-02-12 10:00", "Suivi asthme - gene respiratoire nocturne",
     "Toux seche nocturne, sifflements intermittents, dyspnee d'effort stade 2",
     "Auscultation: sibilants bilateraux, FR 20/min, SpO2 96%",
     "Asthme persistant modere - exacerbation legere", "Ajout Singulair 10mg le soir + maintien Ventoline a la demande", None),

    (patient_ids[2],  DOCTOR_ID, appt_ids[2], "2026-02-15 11:00", "Controle trimestriel HTA + diabete",
     "Pas de plainte particuliere, observance therapeutique correcte",
     "TA 145/90 mmHg, examen cardio normal, pas d'oedemes, pouls pedieux percus",
     "HTA partiellement controlee - diabete type 2 equilibre (HbA1c 6.8%)", "Augmenter Amlodipine a 10mg, maintenir Metformine 1000mg x2/j", "Bilan renal dans 3 mois"),

    (patient_ids[4],  DOCTOR_ID, appt_ids[3], "2026-02-20 14:00", "Bilan lipidique - resultats analyse",
     "Asymptomatique, venu pour resultats du bilan",
     "Examen clinique normal, IMC 28.5",
     "Dyslipidemie mixte (LDL 1.85g/L, TG 2.1g/L)", "Atorvastatine 20mg le soir + regime pauvre en graisses saturees", "Controle lipidique dans 3 mois"),

    (patient_ids[6],  DOCTOR_ID, appt_ids[4], "2026-02-25 09:00", "Suivi insuffisance cardiaque",
     "Dyspnee d'effort stade II NYHA stable, pas d'orthopnee",
     "TA 130/80, FC 72 regulier, auscultation cardiaque: B1B2 normaux, souffle systolique 2/6 au foyer aortique, pas de crepitants",
     "Insuffisance cardiaque stable sous traitement - cardiopathie ischemique", "Maintien du traitement actuel: Ramipril 5mg, Bisoprolol 2.5mg, Furosemide 40mg", "ECG + BNP dans 3 mois"),

    (patient_ids[3],  DOCTOR_ID, appt_ids[5], "2026-03-01 10:00", "Rhinite allergique saisonniere",
     "Eternuements en salves, rhinorrhee claire, prurit nasal et oculaire depuis 2 semaines",
     "Muqueuse nasale pale et oedematiee, conjonctives legerement injectees",
     "Rhinite allergique saisonniere", "Cetirizine 10mg 1cp/j + spray nasal Mometasone 2 pulv/narine/j", "Bilan allergologique a programmer"),

    (patient_ids[10], DOCTOR_ID, appt_ids[6], "2026-03-03 11:00", "Lombalgie aigue sur fond chronique",
     "Douleur lombaire basse apparue brutalement apres effort de soulevement, irradiation fessiere droite, pas de sciatique vraie",
     "Contracture paravertebrale L4-L5, Lasegue negatif bilateral, ROT normaux, pas de deficit sensitivo-moteur",
     "Lumbago aigu", "Ketoprofene 100mg x2/j pendant 5 jours + Thiocolchicoside 4mg x2/j + repos relatif", "Radiographie si persistance > 10 jours"),

    (patient_ids[5],  DOCTOR_ID, appt_ids[7], "2026-03-05 15:00", "Controle thyroide - resultats TSH",
     "Pas de plainte, traitement bien tolere",
     "Palpation thyroidienne: glande de taille normale, pas de nodule, pas d'adenopathie cervicale",
     "Hypothyroidie bien equilibree sous Levothyrox 75mcg (TSH 2.1 mUI/L)", "Maintien Levothyrox 75mcg a jeun", "Prochain controle TSH dans 6 mois"),

    (patient_ids[12], DOCTOR_ID, appt_ids[8], "2026-03-07 09:30", "Suivi BPCO",
     "Toux productive matinale chronique, expectoration blanchatre, dyspnee d'effort stade 2 mMRC",
     "Auscultation: diminution du murmure vesiculaire aux bases, quelques ronchi, FR 18, SpO2 94% en AA",
     "BPCO stade modere (GOLD B) - stable", "Maintien Spiriva 18mcg 1 inh/j + Ventoline a la demande, vaccination antigrippale recommandee", "EFR de controle dans 6 mois"),

    (patient_ids[9],  DOCTOR_ID, appt_ids[9], "2026-03-10 14:00", "Douleur epigastrique + reflux",
     "Brulures epigastriques postprandiales, reflux acide, pyrosis, depuis 1 mois",
     "Abdomen souple, sensibilite epigastrique, pas de masse, TR normal",
     "Reflux gastro-oesophagien (RGO)", "Pantoprazole 40mg 1cp/j avant le petit-dejeuner pendant 8 semaines + mesures posturales", "Endoscopie si persistance des symptomes"),
]

consultation_ids = []
for cd in consultations_data:
    c.execute("""INSERT INTO consultations
        (patient_id, doctor_id, appointment_id, consultation_date, reason, symptoms, clinical_exam, diagnosis, treatment_plan, notes)
        VALUES (,,,,,,,,,)""", cd)
    consultation_ids.append(c.lastrowid)

# -- VITALS --
vitals = [
    (consultation_ids[0], patient_ids[0],  78.5, 175.0, 125, 80, 76, 37.0, 98.0),
    (consultation_ids[1], patient_ids[1],  55.0, 162.0, 115, 72, 82, 37.1, 96.0),
    (consultation_ids[2], patient_ids[2],  92.0, 170.0, 145, 90, 80, 36.8, 97.0),
    (consultation_ids[3], patient_ids[4],  88.0, 176.0, 130, 85, 72, 36.9, 98.0),
    (consultation_ids[4], patient_ids[6],  75.0, 168.0, 130, 80, 72, 36.7, 96.0),
    (consultation_ids[5], patient_ids[3],  60.0, 165.0, 110, 70, 68, 36.6, 99.0),
    (consultation_ids[6], patient_ids[10], 85.0, 172.0, 140, 88, 78, 37.0, 98.0),
    (consultation_ids[7], patient_ids[5],  58.0, 160.0, 118, 75, 70, 36.5, 99.0),
    (consultation_ids[8], patient_ids[12], 70.0, 165.0, 135, 82, 84, 36.9, 94.0),
    (consultation_ids[9], patient_ids[9],  62.0, 168.0, 120, 78, 74, 36.8, 98.0),
]
c.executemany("""INSERT INTO vitals
    (consultation_id, patient_id, weight, height, blood_pressure_sys, blood_pressure_dia, heart_rate, temperature, spo2)
    VALUES (,,,,,,,,)""", vitals)

# -- PRESCRIPTIONS + ITEMS (medicaments vendus au Maroc) --
prescriptions = [
    (consultation_ids[0], patient_ids[0], DOCTOR_ID, "2026-02-10", None, 0),
    (consultation_ids[1], patient_ids[1], DOCTOR_ID, "2026-02-12", None, 1),
    (consultation_ids[2], patient_ids[2], DOCTOR_ID, "2026-02-15", "Renouvellement trimestriel", 1),
    (consultation_ids[3], patient_ids[4], DOCTOR_ID, "2026-02-20", None, 0),
    (consultation_ids[4], patient_ids[6], DOCTOR_ID, "2026-02-25", "Ordonnance longue duree", 1),
    (consultation_ids[5], patient_ids[3], DOCTOR_ID, "2026-03-01", None, 0),
    (consultation_ids[6], patient_ids[10], DOCTOR_ID, "2026-03-03", None, 0),
    (consultation_ids[7], patient_ids[5], DOCTOR_ID, "2026-03-05", "Renouvellement 6 mois", 1),
    (consultation_ids[8], patient_ids[12], DOCTOR_ID, "2026-03-07", None, 1),
    (consultation_ids[9], patient_ids[9], DOCTOR_ID, "2026-03-10", None, 0),
]

presc_ids = []
for pr in prescriptions:
    c.execute("""INSERT INTO prescriptions
        (consultation_id, patient_id, doctor_id, prescription_date, notes, is_renewable)
        VALUES (,,,,,)""", pr)
    presc_ids.append(c.lastrowid)

# Prescription items
items = [
    # Gastrite
    (presc_ids[0], "Omeprazole 20mg (Mopral)",       "1 gelule",   "1 fois/jour le matin a jeun", "4 semaines", "30 minutes avant le petit-dejeuner", 28),
    (presc_ids[0], "Gaviscon suspension buvable",     "1 sachet",   "3 fois/jour apres les repas",  "2 semaines", "Apres chaque repas",                 42),

    # Asthme
    (presc_ids[1], "Ventoline 100mcg aerosol",        "2 bouffees", "A la demande",                 "3 mois",    "En cas de gene respiratoire, max 8 bouffees/jour", 1),
    (presc_ids[1], "Singulair 10mg (Montelukast)",    "1 comprime", "1 fois/jour le soir",          "3 mois",    "A prendre le soir au coucher",       90),
    (presc_ids[1], "Seretide Diskus 250/50mcg",       "1 inhalation","2 fois/jour",                 "3 mois",    "Matin et soir, rincer la bouche apres", 1),

    # HTA + Diabete
    (presc_ids[2], "Amlodipine 10mg (Amlor)",         "1 comprime", "1 fois/jour le matin",         "3 mois",    None,                                 90),
    (presc_ids[2], "Metformine 1000mg (Glucophage)",   "1 comprime", "2 fois/jour",                  "3 mois",    "Pendant les repas (midi et soir)",   180),
    (presc_ids[2], "Ramipril 5mg (Triatec)",           "1 comprime", "1 fois/jour le matin",         "3 mois",    None,                                 90),

    # Dyslipidemie
    (presc_ids[3], "Atorvastatine 20mg (Tahor)",       "1 comprime", "1 fois/jour le soir",          "3 mois",    "A prendre le soir au coucher",       90),

    # Insuffisance cardiaque
    (presc_ids[4], "Ramipril 5mg (Triatec)",           "1 comprime", "1 fois/jour",                  "3 mois",    "Le matin",                           90),
    (presc_ids[4], "Bisoprolol 2.5mg (Concor)",        "1 comprime", "1 fois/jour le matin",         "3 mois",    "Ne pas arreter brutalement",         90),
    (presc_ids[4], "Furosemide 40mg (Lasilix)",        "1 comprime", "1 fois/jour le matin",         "3 mois",    "Surveiller la kaliemie",             90),
    (presc_ids[4], "Eliquis 5mg (Apixaban)",           "1 comprime", "2 fois/jour",                  "3 mois",    "Matin et soir a heure fixe",         180),

    # Rhinite allergique
    (presc_ids[5], "Cetirizine 10mg (Zyrtec)",         "1 comprime", "1 fois/jour",                  "1 mois",    "Le soir de preference",              30),
    (presc_ids[5], "Mometasone spray nasal (Nasonex)", "2 pulv/narine","1 fois/jour le matin",       "1 mois",    "Se moucher avant utilisation",       1),

    # Lombalgie
    (presc_ids[6], "Ketoprofene 100mg (Profenid)",     "1 comprime", "2 fois/jour",                  "5 jours",   "Pendant les repas",                  10),
    (presc_ids[6], "Thiocolchicoside 4mg (Coltramyl)", "1 comprime", "2 fois/jour",                  "5 jours",   "Matin et soir",                      10),
    (presc_ids[6], "Paracetamol 1g (Doliprane)",       "1 comprime", "3 fois/jour si douleur",       "7 jours",   "Espacer de 6h minimum",              21),

    # Hypothyroidie
    (presc_ids[7], "Levothyrox 75mcg",                 "1 comprime", "1 fois/jour le matin a jeun",  "6 mois",    "30 min avant le petit-dejeuner, loin du calcium et fer", 180),

    # BPCO
    (presc_ids[8], "Spiriva 18mcg (Tiotropium)",       "1 gelule inhalee","1 fois/jour",             "3 mois",    "Le matin via HandiHaler",            90),
    (presc_ids[8], "Ventoline 100mcg",                 "2 bouffees", "A la demande",                 "3 mois",    "En cas de dyspnee",                  1),

    # RGO
    (presc_ids[9], "Pantoprazole 40mg (Inipomp)",      "1 comprime", "1 fois/jour le matin a jeun",  "8 semaines", "30 min avant le petit-dejeuner",    56),
    (presc_ids[9], "Gaviscon suspension buvable",      "1 sachet",   "Apres les 3 repas + au coucher","4 semaines","Apres les repas et au coucher",     120),
]

c.executemany("""INSERT INTO prescription_items
    (prescription_id, medication_name, dosage, frequency, duration, instructions, quantity)
    VALUES (,,,,,,)""", items)

conn.commit()

print(f"Patients ajoutes: {len(patients)}")
print(f"Antecedents ajoutes: {len(histories)}")
print(f"Rendez-vous ajoutes: {len(appointments)}")
print(f"Consultations ajoutees: {len(consultations_data)}")
print(f"Ordonnances ajoutees: {len(prescriptions)}")
print(f"Medicaments prescrits ajoutes: {len(items)}")
print("Done!")

conn.close()
