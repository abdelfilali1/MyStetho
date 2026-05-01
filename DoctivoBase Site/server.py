"""
Doctivo Annuaire — Backend server
FastAPI + SQLite on port 9000
"""
import sqlite3, os, json
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

BASE = Path(__file__).parent
DB_PATH = BASE / "data" / "doctivo.db"

# ── Pydantic models ───────────────────────
class DoctorCreate(BaseModel):
    prenom: str
    nom: str
    specialite: str
    ville: str
    quartier: str
    adresse: str
    type: str
    langues: str           # comma-separated
    note: float = 0.0
    avis: int = 0
    conventionne: bool = False
    verifie: bool = False
    sexe: str = "H"
    email: str = ""
    tel: str = ""
    bio: str = ""

class DoctorUpdate(DoctorCreate):
    pass

# ── DB helpers ────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(row):
    d = dict(row)
    # Parse langues back to list
    d["langues"] = [l.strip() for l in (d.get("langues") or "").split(",") if l.strip()]
    d["conventionne"] = bool(d.get("conventionne"))
    d["verifie"] = bool(d.get("verifie"))
    return d

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            prenom      TEXT NOT NULL,
            nom         TEXT NOT NULL,
            specialite  TEXT NOT NULL,
            ville       TEXT NOT NULL,
            quartier    TEXT NOT NULL DEFAULT '',
            adresse     TEXT NOT NULL DEFAULT '',
            type        TEXT NOT NULL DEFAULT 'Cabinet privé',
            langues     TEXT NOT NULL DEFAULT 'Français,Arabe',
            note        REAL NOT NULL DEFAULT 0.0,
            avis        INTEGER NOT NULL DEFAULT 0,
            conventionne INTEGER NOT NULL DEFAULT 0,
            verifie     INTEGER NOT NULL DEFAULT 1,
            sexe        TEXT NOT NULL DEFAULT 'H',
            email       TEXT NOT NULL DEFAULT '',
            tel         TEXT NOT NULL DEFAULT '',
            bio         TEXT NOT NULL DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id    INTEGER NOT NULL,
            prenom       TEXT NOT NULL,
            nom          TEXT NOT NULL,
            email        TEXT NOT NULL,
            tel          TEXT,
            raison       TEXT,
            message      TEXT,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)
    conn.commit()

    # Seed if empty
    if cur.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
        seed_data = [
          ("Karim","Drissi","Cardiologie","Casablanca","Maârif","12 Rue Ibn Khaldoun, Maârif","Cabinet privé","Français,Arabe,Anglais",4.9,142,1,1,"H","k.drissi@doctivo.ma","+212 522 47 18 32","Cardiologue interventionnel diplômé de la faculté de médecine de Casablanca, exercice depuis 18 ans. Spécialisé en échocardiographie et suivi des pathologies coronariennes."),
          ("Salma","Bensouda","Dermatologie","Rabat","Agdal","Avenue Mohammed VI, Résidence Al Hambra","Cabinet privé","Français,Arabe",4.8,98,1,1,"F","s.bensouda@doctivo.ma","+212 537 68 22 14","Dermatologue-vénérologue, prise en charge des pathologies cutanées de l'adulte et de l'enfant. Dermatologie esthétique et laser."),
          ("Mohamed","Razi","Médecine générale","Marrakech","Guéliz","Rue de la Liberté, Immeuble Atlas","Cabinet privé","Français,Arabe,Berbère",4.7,76,1,1,"H","m.razi@doctivo.ma","+212 524 43 91 07","Médecin généraliste, suivi familial, médecine préventive et bilans de santé."),
          ("Nadia","El Fassi","Pédiatrie","Casablanca","Anfa","Boulevard d'Anfa, Centre Médical Anfa","Clinique","Français,Arabe,Anglais",5.0,213,1,1,"F","n.elfassi@doctivo.ma","+212 522 36 14 88","Pédiatre, suivi du nouveau-né à l'adolescent, vaccinations et pathologies courantes."),
          ("Youssef","Alaoui","Chirurgie dentaire","Tanger","Centre","Rue de Belgique, n°45","Cabinet privé","Français,Arabe,Espagnol",4.6,54,0,1,"H","y.alaoui@doctivo.ma","+212 539 32 40 19","Chirurgien-dentiste, soins conservateurs, endodontie, prothèse et implantologie."),
          ("Imane","Tazi","Gynécologie","Rabat","Hassan","Avenue Allal Ben Abdellah","Cabinet privé","Français,Arabe",4.9,168,1,1,"F","i.tazi@doctivo.ma","+212 537 70 88 55","Gynécologue-obstétricienne, suivi de grossesse, échographie obstétricale et gynécologie médicale."),
          ("Hassan","Benjelloun","Ophtalmologie","Fès","Ville Nouvelle","Avenue Hassan II, Résidence Andalous","Cabinet privé","Français,Arabe",4.7,89,1,1,"H","h.benjelloun@doctivo.ma","+212 535 65 12 33","Ophtalmologue, chirurgie de la cataracte, glaucome, suivi de la rétine."),
          ("Leila","Chraibi","Psychiatrie","Casablanca","Gauthier","Rue d'Alger, n°22","Cabinet privé","Français,Arabe,Anglais",4.9,64,0,1,"F","l.chraibi@doctivo.ma","+212 522 26 78 41","Psychiatre, prise en charge des troubles anxieux, dépressifs et thérapies cognitivo-comportementales."),
          ("Omar","Lahlou","Orthopédie","Marrakech","Hivernage","Avenue Mohammed VI, Clinique du Sud","Hôpital","Français,Arabe,Anglais",4.8,121,1,1,"H","o.lahlou@doctivo.ma","+212 524 42 18 90","Chirurgien orthopédiste, traumatologie du sport, prothèses de hanche et de genou."),
          ("Fatima","Idrissi","Endocrinologie","Rabat","Souissi","Avenue Imam Malik, n°78","Cabinet privé","Français,Arabe",4.7,47,1,1,"F","f.idrissi@doctivo.ma","+212 537 75 33 21","Endocrinologue-diabétologue, prise en charge du diabète, troubles thyroïdiens et nutritionnels."),
          ("Rachid","Mernissi","Cardiologie","Tanger","Iberia","Boulevard Pasteur, Immeuble Atlantique","Clinique","Français,Arabe,Espagnol",4.6,73,1,1,"H","r.mernissi@doctivo.ma","+212 539 94 21 06","Cardiologue, exploration fonctionnelle, holter et test d'effort."),
          ("Amina","Berrada","Médecine générale","Casablanca","Bourgogne","Rue Jean Jaurès, n°15","Cabinet privé","Français,Arabe",4.8,156,1,1,"F","a.berrada@doctivo.ma","+212 522 94 33 87","Médecin généraliste, médecine de famille et suivi des pathologies chroniques."),
          ("Tarik","Sefrioui","Dermatologie","Marrakech","Guéliz","Rue Mohammed El Beqal","Cabinet privé","Français,Arabe,Anglais",4.5,38,0,1,"H","t.sefrioui@doctivo.ma","+212 524 43 71 02","Dermatologue, dermatologie générale et esthétique."),
          ("Khadija","Amrani","Pédiatrie","Fès","Atlas","Avenue des FAR, Résidence Al Manar","Cabinet privé","Français,Arabe",4.9,102,1,1,"F","k.amrani@doctivo.ma","+212 535 73 45 18","Pédiatre, suivi du développement et pathologies infantiles."),
          ("Mehdi","Filali","Chirurgie dentaire","Casablanca","Maârif","Rue Ibnou Mounir, Centre Maârif","Cabinet privé","Français,Arabe,Anglais",4.8,91,1,1,"H","m.filali@doctivo.ma","+212 522 27 83 14","Chirurgien-dentiste, dentisterie esthétique et implantologie."),
          ("Sara","Cherkaoui","Gynécologie","Marrakech","Guéliz","Avenue Mohammed V, Cabinet Atlas","Cabinet privé","Français,Arabe",4.7,84,1,1,"F","s.cherkaoui@doctivo.ma","+212 524 44 12 76","Gynécologue-obstétricienne, suivi de grossesse et échographie."),
          ("Adil","Bennani","Ophtalmologie","Casablanca","Anfa","Boulevard de la Corniche, Centre Visio","Clinique","Français,Arabe,Anglais",4.9,187,1,1,"H","a.bennani@doctivo.ma","+212 522 39 64 21","Ophtalmologue, chirurgie réfractive au laser et chirurgie de la cataracte."),
          ("Hanae","Zniber","Endocrinologie","Casablanca","Maârif","Rue Soumaya, Résidence Diamond","Cabinet privé","Français,Arabe",4.6,52,1,1,"F","h.zniber@doctivo.ma","+212 522 98 17 33","Endocrinologue, diabète et maladies métaboliques."),
          ("Brahim","Ouazzani","Orthopédie","Rabat","Agdal","Avenue Fal Ould Oumeir","Cabinet privé","Français,Arabe",4.7,68,1,1,"H","b.ouazzani@doctivo.ma","+212 537 67 14 92","Orthopédiste, chirurgie de la main et du poignet."),
          ("Yasmine","Kabbaj","Psychiatrie","Rabat","Hay Riad","Rue Annaba, Résidence Les Roses","Cabinet privé","Français,Arabe,Anglais",5.0,89,0,1,"F","y.kabbaj@doctivo.ma","+212 537 56 28 45","Psychiatre, psychothérapies et troubles de l'humeur."),
          ("Reda","Hakimi","Médecine générale","Tanger","Centre","Avenue Mohammed V, n°102","Cabinet privé","Français,Arabe,Espagnol",4.5,41,1,1,"H","r.hakimi@doctivo.ma","+212 539 33 78 14","Médecin généraliste, médecine du travail et certificats médicaux."),
          ("Soukaina","Lazrak","Dermatologie","Casablanca","Gauthier","Rue d'Avignon, n°8","Cabinet privé","Français,Arabe,Anglais",4.8,134,1,1,"F","s.lazrak@doctivo.ma","+212 522 48 91 27","Dermatologue, acné, psoriasis et dermatologie pédiatrique."),
          ("Othmane","Tahiri","Cardiologie","Rabat","Souissi","Avenue Imam Malik, Centre Cardio","Clinique","Français,Arabe,Anglais",4.9,156,1,1,"H","o.tahiri@doctivo.ma","+212 537 75 02 88","Cardiologue, rythmologie et stimulation cardiaque."),
          ("Lamia","Saadi","Pédiatrie","Marrakech","Hivernage","Rue du Capitaine Arrigui","Cabinet privé","Français,Arabe",4.7,79,1,1,"F","l.saadi@doctivo.ma","+212 524 45 33 12","Pédiatre, allergologie et asthme de l'enfant."),
          ("Amine","Kettani","Neurologie","Casablanca","Maârif","Rue Abou Inane, Centre Médical Iberia","Clinique","Français,Arabe,Anglais",4.9,112,1,1,"H","a.kettani@doctivo.ma","+212 522 45 32 10","Neurologue, spécialiste des maladies vasculaires cérébrales, épilepsie et sclérose en plaques."),
          ("Zineb","Oufkir","Rhumatologie","Rabat","Hay Riad","Résidence les Orangers, Avenue Annakhil","Cabinet privé","Français,Arabe",4.7,63,1,1,"F","z.oufkir@doctivo.ma","+212 537 58 24 17","Rhumatologue, polyarthrite rhumatoïde, spondylarthrite et ostéoporose."),
          ("Khalid","Benali","Urologie","Fès","Ville Nouvelle","Avenue des Almohades, n°33","Hôpital","Français,Arabe",4.8,95,1,1,"H","k.benali@doctivo.ma","+212 535 64 18 92","Urologue, oncologie urologique, lithiase urinaire et laparoscopie."),
          ("Meryem","Ait Taleb","Pneumologie","Marrakech","Guéliz","Rue Ibn Toumert, Résidence Palmeraie","Cabinet privé","Français,Arabe,Berbère",4.6,58,1,1,"F","m.aittaleb@doctivo.ma","+212 524 43 77 25","Pneumologue, asthme, BPCO, sommeil et bronchoscopie."),
        ]
        cur.executemany("""
            INSERT INTO doctors (prenom,nom,specialite,ville,quartier,adresse,type,langues,note,avis,conventionne,verifie,sexe,email,tel,bio)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, seed_data)
        conn.commit()
    conn.close()

# ── App ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("\n  Doctivo Annuaire - http://localhost:9000\n")
    yield

app = FastAPI(title="Doctivo Annuaire API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── API routes ────────────────────────────
@app.get("/api/doctors")
def list_doctors(
    q: str = "",
    ville: str = "",
    spec: str = "",
    type_: str = Query("", alias="type"),
    lang: str = "",
    conv: bool = False,
    sort: str = "note",
    page: int = 1,
    per_page: int = 100,
):
    conn = get_db()
    cur = conn.cursor()
    where, params = ["1=1"], []

    if q:
        where.append("(lower(prenom||' '||nom) LIKE ? OR lower(specialite) LIKE ? OR lower(ville) LIKE ? OR lower(bio) LIKE ?)")
        like = f"%{q.lower()}%"
        params += [like, like, like, like]
    if ville:
        where.append("ville = ?"); params.append(ville)
    if spec:
        where.append("specialite = ?"); params.append(spec)
    if type_:
        where.append("type = ?"); params.append(type_)
    if lang:
        where.append("(',' || langues || ',') LIKE ?"); params.append(f"%,{lang},%")
    if conv:
        where.append("conventionne = 1")

    order = {"note": "note DESC, avis DESC", "nom": "nom ASC", "avis": "avis DESC"}.get(sort, "note DESC")
    sql = f"SELECT * FROM doctors WHERE {' AND '.join(where)} ORDER BY {order}"
    rows = cur.execute(sql, params).fetchall()
    total = len(rows)
    offset = (page - 1) * per_page
    sliced = rows[offset:offset + per_page]
    conn.close()
    return {"total": total, "page": page, "doctors": [row_to_dict(r) for r in sliced]}

@app.get("/api/doctors/{doctor_id}")
def get_doctor(doctor_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Médecin introuvable")
    return row_to_dict(row)

@app.post("/api/doctors", status_code=201)
def create_doctor(d: DoctorCreate):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO doctors (prenom,nom,specialite,ville,quartier,adresse,type,langues,note,avis,conventionne,verifie,sexe,email,tel,bio)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (d.prenom,d.nom,d.specialite,d.ville,d.quartier,d.adresse,d.type,d.langues,d.note,d.avis,int(d.conventionne),int(d.verifie),d.sexe,d.email,d.tel,d.bio))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "message": "Médecin créé"}

@app.put("/api/doctors/{doctor_id}")
def update_doctor(doctor_id: int, d: DoctorUpdate):
    conn = get_db()
    conn.execute("""
        UPDATE doctors SET prenom=?,nom=?,specialite=?,ville=?,quartier=?,adresse=?,type=?,langues=?,note=?,avis=?,conventionne=?,verifie=?,sexe=?,email=?,tel=?,bio=?
        WHERE id=?
    """, (d.prenom,d.nom,d.specialite,d.ville,d.quartier,d.adresse,d.type,d.langues,d.note,d.avis,int(d.conventionne),int(d.verifie),d.sexe,d.email,d.tel,d.bio,doctor_id))
    conn.commit(); conn.close()
    return {"message": "Mis à jour"}

@app.delete("/api/doctors/{doctor_id}")
def delete_doctor(doctor_id: int):
    conn = get_db()
    conn.execute("DELETE FROM doctors WHERE id=?", (doctor_id,))
    conn.commit(); conn.close()
    return {"message": "Supprimé"}

@app.post("/api/contact")
def submit_contact(data: dict):
    conn = get_db()
    conn.execute("""
        INSERT INTO contact_requests (doctor_id,prenom,nom,email,tel,raison,message)
        VALUES (?,?,?,?,?,?,?)
    """, (data.get("doctor_id"),data.get("prenom"),data.get("nom"),data.get("email"),data.get("tel"),data.get("raison"),data.get("message")))
    conn.commit(); conn.close()
    return {"message": "Demande enregistrée"}

@app.get("/api/meta")
def get_meta():
    conn = get_db()
    villes = [r[0] for r in conn.execute("SELECT DISTINCT ville FROM doctors ORDER BY ville").fetchall()]
    specs = [r[0] for r in conn.execute("SELECT DISTINCT specialite FROM doctors ORDER BY specialite").fetchall()]
    types = [r[0] for r in conn.execute("SELECT DISTINCT type FROM doctors ORDER BY type").fetchall()]
    conn.close()
    return {"villes": villes, "specialites": specs, "types": types}

# ── Static files (last, catch-all) ────────
app.mount("/", StaticFiles(directory=str(BASE), html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
