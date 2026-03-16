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
    # General medications (name, active_ingredient, category, specialty)
    ("Paracétamol 500mg", "Paracétamol", "Antalgique", "general"),
    ("Paracétamol 1000mg", "Paracétamol", "Antalgique", "general"),
    ("Ibuprofène 400mg", "Ibuprofène", "Anti-inflammatoire", "general"),
    ("Amoxicilline 500mg", "Amoxicilline", "Antibiotique", "general"),
    ("Amoxicilline 1g", "Amoxicilline", "Antibiotique", "general"),
    ("Augmentin 875mg", "Amoxicilline/Acide clavulanique", "Antibiotique", "general"),
    ("Azithromycine 250mg", "Azithromycine", "Antibiotique", "general"),
    ("Oméprazole 20mg", "Oméprazole", "IPP", "general"),
    ("Pantoprazole 40mg", "Pantoprazole", "IPP", "general"),
    ("Metformine 500mg", "Metformine", "Antidiabétique", "general"),
    ("Metformine 1000mg", "Metformine", "Antidiabétique", "general"),
    ("Amlodipine 5mg", "Amlodipine", "Antihypertenseur", "general"),
    ("Ramipril 5mg", "Ramipril", "IEC", "general"),
    ("Atorvastatine 10mg", "Atorvastatine", "Statine", "general"),
    ("Doliprane 1000mg", "Paracétamol", "Antalgique", "general"),
    ("Efferalgan 1g", "Paracétamol", "Antalgique", "general"),
    ("Spasfon 40mg", "Phloroglucinol", "Antispasmodique", "general"),
    ("Lexomil 6mg", "Bromazépam", "Anxiolytique", "general"),
    ("Ventoline 100mcg", "Salbutamol", "Bronchodilatateur", "general"),
    ("Levothyrox 50mcg", "Lévothyroxine", "Thyroïde", "general"),
    ("Seretide 25/250", "Salmétérol/Fluticasone", "Bronchodilatateur", "general"),
    ("Prednisolone 20mg", "Prednisolone", "Corticoïde", "general"),
    ("Singulair 10mg", "Montélukast", "Antiasthmatique", "general"),
    ("Xarelto 20mg", "Rivaroxaban", "Anticoagulant", "general"),
    ("Eliquis 5mg", "Apixaban", "Anticoagulant", "general"),
    # Dental medications — commonly prescribed by dentists in Morocco
    ("Amoxicilline 1g", "Amoxicilline", "Antibiotique", "dentiste"),
    ("Augmentin 1g", "Amoxicilline/Acide clavulanique", "Antibiotique", "dentiste"),
    ("Métronidazole 250mg (Flagyl)", "Métronidazole", "Antibiotique", "dentiste"),
    ("Métronidazole 500mg (Flagyl)", "Métronidazole", "Antibiotique", "dentiste"),
    ("Spiramycine 3M UI (Rovamycine)", "Spiramycine", "Antibiotique", "dentiste"),
    ("Spiramycine/Métronidazole (Rodogyl)", "Spiramycine/Métronidazole", "Antibiotique", "dentiste"),
    ("Azithromycine 500mg (Zithromax)", "Azithromycine", "Antibiotique", "dentiste"),
    ("Clindamycine 300mg (Dalacine)", "Clindamycine", "Antibiotique", "dentiste"),
    ("Céfixime 200mg (Oroken)", "Céfixime", "Antibiotique", "dentiste"),
    ("Paracétamol 1000mg (Doliprane)", "Paracétamol", "Antalgique", "dentiste"),
    ("Paracétamol 500mg", "Paracétamol", "Antalgique", "dentiste"),
    ("Ibuprofène 400mg (Brufen)", "Ibuprofène", "Anti-inflammatoire", "dentiste"),
    ("Ibuprofène 600mg", "Ibuprofène", "Anti-inflammatoire", "dentiste"),
    ("Kétoprofène 100mg (Profenid)", "Kétoprofène", "Anti-inflammatoire", "dentiste"),
    ("Diclofénac 50mg (Voltarène)", "Diclofénac", "Anti-inflammatoire", "dentiste"),
    ("Diclofénac 75mg (Voltarène)", "Diclofénac", "Anti-inflammatoire", "dentiste"),
    ("Acide Méfénamique 250mg (Ponstyl)", "Acide Méfénamique", "Anti-inflammatoire", "dentiste"),
    ("Paracétamol/Codéine (Codoliprane)", "Paracétamol/Codéine", "Antalgique", "dentiste"),
    ("Tramadol 50mg", "Tramadol", "Antalgique", "dentiste"),
    ("Prednisolone 20mg (Solupred)", "Prednisolone", "Corticoïde", "dentiste"),
    ("Dexaméthasone 4mg", "Dexaméthasone", "Corticoïde", "dentiste"),
    ("Chlorhexidine 0.12% (Eludril)", "Chlorhexidine", "Bain de bouche", "dentiste"),
    ("Chlorhexidine 0.20% (Paroex)", "Chlorhexidine", "Bain de bouche", "dentiste"),
    ("Hexétidine (Hextril)", "Hexétidine", "Bain de bouche", "dentiste"),
    ("Acide Hyaluronique gel (Hyalugel)", "Acide Hyaluronique", "Topique buccal", "dentiste"),
    ("Miconazole gel buccal (Daktarin)", "Miconazole", "Antifongique", "dentiste"),
    ("Fluconazole 150mg", "Fluconazole", "Antifongique", "dentiste"),
    ("Aciclovir 200mg (Zovirax)", "Aciclovir", "Antiviral", "dentiste"),
    ("Aciclovir crème 5%", "Aciclovir", "Antiviral topique", "dentiste"),
    ("Lidocaïne gel 2% (Dynexan)", "Lidocaïne", "Anesthésique local", "dentiste"),
    ("Oxyde de zinc/eugénol (pansement)", "Oxyde de zinc/Eugénol", "Pansement dentaire", "dentiste"),
    ("Acide Tranexamique 500mg (Exacyl)", "Acide Tranexamique", "Hémostatique", "dentiste"),
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
            "INSERT INTO medications (name, active_ingredient, category, specialty) VALUES (?, ?, ?, ?)",
            MEDICATIONS,
        )
    else:
        # Add dental medications if missing
        cursor = await db.execute("SELECT COUNT(*) FROM medications WHERE specialty = 'dentiste'")
        dental_count = (await cursor.fetchone())[0]
        if dental_count == 0:
            dental_meds = [m for m in MEDICATIONS if m[3] == "dentiste"]
            await db.executemany(
                "INSERT INTO medications (name, active_ingredient, category, specialty) VALUES (?, ?, ?, ?)",
                dental_meds,
            )
            # Tag existing meds as general
            await db.execute("UPDATE medications SET specialty = 'general' WHERE specialty IS NULL")

    await db.commit()
    await db.close()
