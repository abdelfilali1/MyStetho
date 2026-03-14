"""Seed initial data: medical acts, common medications."""
import aiosqlite
from config import DATABASE_PATH


MEDICAL_ACTS = [
    ("CS", "Consultation spécialisée", "Consultation", 30.00),
    ("C", "Consultation générale", "Consultation", 26.50),
    ("CSO", "Consultation en urgence", "Urgence", 40.00),
    ("ADE", "Acte technique diagnostique", "Acte technique", 55.00),
    ("KC25", "Acte chirurgical KC25", "Chirurgie", 73.13),
    ("KC50", "Acte chirurgical KC50", "Chirurgie", 146.25),
    ("IFD", "Injection intramusculaire", "Injection", 3.70),
    ("ECBU", "ECBU (prélevement)", "Biologie", 15.00),
    ("ECG", "Électrocardiogramme", "Cardio", 14.26),
    ("YYYY", "Radiologie standard", "Imagerie", 25.00),
    ("VT", "Visite à domicile", "Visite", 35.00),
    ("DE", "Dossier entretien / coordination", "Admin", 20.00),
]

MEDICATIONS = [
    ("Paracétamol 500mg", "Paracétamol", "Antalgique"),
    ("Paracétamol 1000mg", "Paracétamol", "Antalgique"),
    ("Ibuprofène 400mg", "Ibuprofène", "Anti-inflammatoire"),
    ("Amoxicilline 500mg", "Amoxicilline", "Antibiotique"),
    ("Amoxicilline 1g", "Amoxicilline", "Antibiotique"),
    ("Augmentin 875mg", "Amoxicilline/Acide clavulanique", "Antibiotique"),
    ("Azithromycine 250mg", "Azithromycine", "Antibiotique"),
    ("Oméprazole 20mg", "Oméprazole", "IPP"),
    ("Pantoprazole 40mg", "Pantoprazole", "IPP"),
    ("Metformine 500mg", "Metformine", "Antidiabétique"),
    ("Metformine 1000mg", "Metformine", "Antidiabétique"),
    ("Amlodipine 5mg", "Amlodipine", "Antihypertenseur"),
    ("Ramipril 5mg", "Ramipril", "IEC"),
    ("Atorvastatine 10mg", "Atorvastatine", "Statine"),
    ("Doliprane 1000mg", "Paracétamol", "Antalgique"),
    ("Efferalgan 1g", "Paracétamol", "Antalgique"),
    ("Spasfon 40mg", "Phloroglucinol", "Antispasmodique"),
    ("Lexomil 6mg", "Bromazépam", "Anxiolytique"),
    ("Ventoline 100mcg", "Salbutamol", "Bronchodilatateur"),
    ("Levothyrox 50mcg", "Lévothyroxine", "Thyroïde"),
    ("Seretide 25/250", "Salmétérol/Fluticasone", "Bronchodilatateur"),
    ("Prednisolone 20mg", "Prednisolone", "Corticoïde"),
    ("Singulair 10mg", "Montélukast", "Antiasthmatique"),
    ("Xarelto 20mg", "Rivaroxaban", "Anticoagulant"),
    ("Eliquis 5mg", "Apixaban", "Anticoagulant"),
]


async def seed_db():
    """Insert initial data only if tables are empty."""
    db = await aiosqlite.connect(DATABASE_PATH)

    # Medical acts
    cursor = await db.execute("SELECT COUNT(*) FROM medical_acts")
    count = (await cursor.fetchone())[0]
    if count == 0:
        await db.executemany(
            "INSERT INTO medical_acts (code, name, category, base_price) VALUES (?, ?, ?, ?)",
            MEDICAL_ACTS,
        )

    # Medications
    cursor = await db.execute("SELECT COUNT(*) FROM medications")
    count = (await cursor.fetchone())[0]
    if count == 0:
        await db.executemany(
            "INSERT INTO medications (name, active_ingredient, category) VALUES (?, ?, ?)",
            MEDICATIONS,
        )

    await db.commit()
    await db.close()
