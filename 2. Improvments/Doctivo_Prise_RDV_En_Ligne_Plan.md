# Prise de RDV en ligne — connecter le site web du cabinet à Doctivo

## Context

Certains praticiens Doctivo ont déjà un site web avec un formulaire « Demande de rendez-vous »
(Nom complet, Téléphone, Soin souhaité, Date souhaitée, Message, consentement d'être rappelé).
Aujourd'hui ces demandes arrivent par e-mail ou ne vont nulle part : elles sont ressaisies à la
main dans l'agenda, ou perdues.

Objectif : le formulaire du site alimente directement Doctivo. Le flux métier voulu est
**demande → vérification de disponibilité → validation du créneau par le praticien → appel de
confirmation par la secrétaire → création du RDV dans l'agenda**. Rien n'est réservé
automatiquement : un humain décroche le téléphone avant qu'un créneau soit bloqué.

C'est l'item 🟠 « Prise de RDV en ligne » de `Doctivo_Ameliorations_Roadmap.md:45`, et son
prérequis 🔴 HTTPS (`ligne 10`) est inclus ici : la VM tourne en HTTP pur, or un `<iframe>`
`http://` dans un site `https://` est bloqué par le navigateur.

### Décisions actées
| Sujet | Choix |
|---|---|
| Intégration | **Formulaire hébergé par Doctivo**, collé en `<iframe>` sur le site du praticien. Marche sur Wix / WordPress / HTML statique, sans backend côté site. |
| HTTPS | **Inclus dans ce chantier** (étape 0, bloquante). |
| Rôles | La **secrétaire fait tout** sauf *refuser une demande* et *gérer les clés API* (praticien uniquement). |
| Disponibilités publiques | **Aucune fuite en v1** : « Date souhaitée » reste un champ libre, comme sur la maquette actuelle. |

---

## Architecture

```
  Site du cabinet (Wix/WP/HTML, https://cabinet.ma)
        │  <iframe src="https://app.doctivo.org/public/rdv/pk_live_xxx/embed">
        ▼
  Doctivo — routeur PUBLIC  (routers/rdv_public.py, aucune session, aucun get_current_user)
        │  POST /public/api/rdv/{public_key}
        ▼
  booking_requests   ← table de QUARANTAINE : aucun code clinique ni financier ne la lit
        │
        │  badge barre latérale + toast  (poll 30 s, comme #msg-unread-badge)
        ▼
  Doctivo — module STAFF  (routers/demandes.py)
     inbox → verdict de dispo → créneau retenu → appel → fiche patient → « Créer le RDV »
        │
        ▼
  appointments  (statut 'confirme')  +  patients   ← seulement ici, après un humain
```

Le point clé : **une demande n'est jamais un `appointments`**. Sinon elle bloquerait un vrai
créneau (la requête de conflit sélectionne `status NOT IN ('annule','absent')`), apparaîtrait sur
FullCalendar, serait poussée en salle d'attente par `wr.sync_from_appointment`, et
`reminder_scheduler` enverrait un rappel WhatsApp à un inconnu. Sans compter que
`appointments.patient_id` est NOT NULL → il faudrait créer une fiche patient à partir d'un nom et
d'un téléphone tapés par n'importe qui sur Internet, dans une table qui n'a **aucune déduplication**.

---

## Étape 0 — HTTPS (bloquante, à faire en premier)

Sans TLS, le mode iframe est mort : le navigateur refuse un contenu actif `http://` dans une page
`https://`. Tout le reste (module `/demandes`, agenda, workflow) est développable et testable en
HTTP local, mais **aucune clé n'est remise à un praticien avant cette étape**.

1. Créer un enregistrement DNS `A app.doctivo.org → 145.241.162.251` *(à faire côté registrar —
   hypothèse : le domaine `doctivo.org`, déjà utilisé pour le site vitrine et l'image d'en-tête
   WhatsApp `config.py:119`, est sous votre contrôle)*.
2. Installer **Caddy** sur la VM (TLS automatique, plus simple que nginx + certbot), en
   remplacement du nginx actuel devant `127.0.0.1:8000`. Versionner la conf dans un nouveau
   `deploy/` — la roadmap le réclame déjà, et rien de la VM n'est aujourd'hui dans le dépôt.
3. Passer `MEDFOLLOW_HTTPS=1` dans l'unité systemd → bascule les cookies `access_token` et
   `csrf_token` en `Secure` et active HSTS (`main.py:124`).
4. Renseigner enfin `MEDFOLLOW_PUBLIC_BASE_URL=https://app.doctivo.org`. La variable existe dans
   `config.py` mais **n'est lue nulle part** ; ce chantier est son premier consommateur (le
   snippet iframe doit contenir une URL absolue, et derrière le proxy `request.base_url` renvoie
   `http://127.0.0.1:8000`).
5. Bonus offert par le TLS : le webhook WhatsApp entrant (`routers/whatsapp_webhook.py`),
   inerte aujourd'hui, devient fonctionnel.

Dans `deploy/Caddyfile`, sur `/public/api/*` : `request_body max_size 16KB` et
`X-Forwarded-For` **écrasé** par l'IP réelle (voir le risque n°2 plus bas).

---

## Étape 1 — Refactor `services/scheduling.py` (commit séparé, sans changement de comportement)

Prérequis technique : la boucle de génération de créneaux est écrite **trois fois** dans
[appointments.py](medfollow/routers/appointments.py) (l.120-139, l.195-207, l.302-313) et la
requête de conflit **deux fois** (l.168-175, l.280-287). Le module « demandes » a besoin des deux.

Nouveau `medfollow/services/scheduling.py`, extraction pure :

```python
DAY_START, DAY_END, GRID_MINUTES, DEFAULT_DURATION = "08:00", "19:30", 30, 30

async def booked_intervals(db, doctor_id, day, exclude_id=0) -> list[tuple[str, str]]
async def has_conflict(db, doctor_id, start, end, exclude_id=0) -> bool
def  generate_slots(day, booked, duration=30, from_time=None, limit=6) -> list[dict]
async def free_slots(db, doctor_id, day, duration=30, exclude_id=0, limit=6, from_time=None)
async def next_free_slots(db, doctor_id, from_day, days=3, duration=30, limit=6)
async def day_load(db, doctor_id, day, duration=30) -> str   # 'libre'|'charge'|'complet'
```

Puis réécrire les 3 sites d'appel dans `appointments.py`. La charge utile 409
`{"conflict": true, "suggestions": [...]}` et la bannière `#conflict-banner` de
[templates/appointments/index.html](medfollow/templates/appointments/index.html) restent
identiques. **Faire tourner `scripts/smoke_test.py` avant et après.**

Au passage : `GET /appointments/api/free-slots` (l.98) est du **code mort** (rien ne l'appelle) —
le réimplémenter sur `scheduling.free_slots` au lieu de le supprimer, la page de détail d'une
demande en a besoin.

Ajouter aussi l'index manquant — chaque vérification de dispo filtre sur `(doctor_id, start_datetime)`
et la table n'a **aucun index** :
```sql
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_start ON appointments(doctor_id, start_datetime);
```

---

## Étape 2 — Schéma

À placer **tout à la fin de `init_db()`** dans
[database/connection.py](medfollow/database/connection.py), juste avant `await db.close()` (l.1069).
Raison documentée l.1029 : les blocs de reconstruction de table plus haut dans le fichier
effacent silencieusement ce qui est défini avant eux.

```python
    # --- Prise de RDV en ligne : intégrations site web + demandes de RDV -----
    # Placement en toute fin d'init_db pour la meme raison que le bloc « remise »
    # ci-dessus : toute reconstruction de table plus haut effacerait ce qui est
    # defini avant elle.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS website_integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL REFERENCES users(id),
            label TEXT,                            -- « Site du cabinet »
            public_key TEXT UNIQUE NOT NULL,       -- pk_live_… : PUBLIC, present dans le HTML
            secret_prefix TEXT,                    -- 16 premiers car., affichage seul (v2)
            secret_sha256 TEXT,                    -- sha256(secret) ; revele une seule fois
            require_secret INTEGER DEFAULT 0,      -- v2 : mode serveur-a-serveur HMAC
            allowed_origins TEXT DEFAULT '[]',     -- JSON ; sert au frame-ancestors de /embed
            accepts_requests INTEGER DEFAULT 1,    -- interrupteur « je ferme les demandes »
            expose_availability INTEGER DEFAULT 0, -- v2
            ack_whatsapp INTEGER DEFAULT 0,        -- v2 : accuse de reception au patient
            notify_email INTEGER DEFAULT 1,
            soins TEXT DEFAULT '[]',               -- JSON : contenu du <select> « Soin souhaite »
            horizon_days INTEGER DEFAULT 60,
            default_duration INTEGER DEFAULT 30,
            is_active INTEGER DEFAULT 1,
            last_used_at DATETIME, rotated_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_webint_doctor "
                     "ON website_integrations(doctor_id, is_active)")
    await db.commit()

    await db.execute("""
        CREATE TABLE IF NOT EXISTS booking_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL REFERENCES users(id),
            integration_id INTEGER REFERENCES website_integrations(id),
            reference TEXT UNIQUE,                 -- RDV-7F3K2Q, communique au patient
            -- Saisie brute du patient : jamais ecrasee (trace de ce qu'il a demande).
            full_name TEXT NOT NULL,
            phone_raw TEXT NOT NULL,
            phone_e164 TEXT,                       -- normalize_msisdn() : sert au rapprochement
            soin TEXT, requested_date DATE, requested_time TEXT, message TEXT,
            consent INTEGER NOT NULL DEFAULT 0,          -- « accepte d'etre recontacte par tel. »
            consent_whatsapp INTEGER NOT NULL DEFAULT 0, -- consentement DISTINCT (loi 09-08)
            status TEXT CHECK(status IN ('nouvelle','creneau_propose','a_rappeler',
                                         'confirmee','planifiee','refusee','annulee','spam'))
                   DEFAULT 'nouvelle',
            proposed_start DATETIME, proposed_end DATETIME,   -- format 'YYYY-MM-DDTHH:MM'
            proposed_by INTEGER REFERENCES users(id), proposed_at DATETIME,
            called_by INTEGER REFERENCES users(id), called_at DATETIME,
            call_outcome TEXT, call_attempts INTEGER DEFAULT 0,
            patient_id INTEGER REFERENCES patients(id),
            appointment_id INTEGER REFERENCES appointments(id),
            refus_motif TEXT, staff_notes TEXT,
            source_ip TEXT, user_agent TEXT, client_request_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_breq_doctor_status "
                     "ON booking_requests(doctor_id, status, created_at)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_breq_phone "
                     "ON booking_requests(doctor_id, phone_e164)")
    await db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_breq_client_req
                        ON booking_requests(integration_id, client_request_id)
                        WHERE client_request_id IS NOT NULL""")
    await db.commit()
```

**Cycle de vie** (à faire respecter par une table `_ALLOWED` explicite dans `services/booking.py`,
pas par des `if` éparpillés) :

```
nouvelle ──► creneau_propose ──► a_rappeler ⇄ ──► confirmee ──► planifiee (terminal)
    │              │                                  │
    └──► spam      └──► refusee (medecin)             └──► annulee
```

**Clés.** La clé publique `pk_live_<token_urlsafe(24)>` est stockée en clair et `UNIQUE` : elle est
dans le HTML du site, ce n'est pas un secret — c'est un identifiant + la capacité de créer une
demande, jamais de lire quoi que ce soit. Le `doctor_id` est lu **sur la ligne d'intégration,
jamais dans le corps de la requête** (même discipline que `effective_doctor_id` dans
`appointments.py:152`). Révocation = `is_active = 0`, jamais de DELETE (la FK
`booking_requests.integration_id` et la piste d'audit doivent rester résolvables).
Le secret `sk_live_…` (mode serveur-à-serveur, v2) sera stocké en **sha256**, pas en bcrypt :
bcrypt coûte ~100 ms de CPU sur la boucle d'événements unique, sur une route **publique** — c'est
un levier de déni de service offert, et un secret de 256 bits n'a pas de dictionnaire à protéger.

---

## Étape 3 — Surface publique (`routers/rdv_public.py`, prefix `/public`)

```
GET     /public/rdv/{public_key}            → page autonome (lien « Prendre RDV »)
GET     /public/rdv/{public_key}/embed      → même formulaire, layout iframe + CSP frame-ancestors
GET     /public/rdv/{public_key}/merci      → confirmation + référence
GET     /public/api/rdv/{public_key}/config → JSON : nom du cabinet, liste des soins, horizon
POST    /public/api/rdv/{public_key}        → création d'une demande  (JSON ou form-urlencoded)
OPTIONS /public/api/rdv/{public_key}        → préflight CORS dynamique
```

Le formulaire hébergé POSTe sur cette même API : le contrat JSON existe donc dès la v1, prêt à
être ouvert à un formulaire tiers (mode « je garde mon formulaire ») en activant simplement une
origine dans les réglages.

### Deux règles dures pour l'exemption CSRF
`main.py:169` devient `.startswith(("/static", "/webhooks/", "/public/"))`.
1. **Aucun handler sous `/public/` ne lit `access_token` ni n'appelle `get_current_user`.** Une
   route exemptée de CSRF qui honore la session serait un *confused deputy*. Ici, un POST forgé
   depuis un site tiers crée une demande attribuée à personne — du spam, que le rate-limit gère.
2. Ne pas poser le cookie CSRF sous `/public/` non plus (`main.py:220`) : un cookie `SameSite=lax`
   posé depuis un iframe tiers est de toute façon jeté.

Ajouter aussi `/public` aux préfixes ignorés par `_inject_active_consultation` (`main.py:60`) —
cela évite une connexion SQLite par requête sur une route chaude.

### Requête / réponse

```jsonc
// POST, Content-Type: application/json  (form-urlencoded également accepté)
{ "nom_complet": "Fatima Zahra Bennani", "telephone": "06 12 34 56 78",
  "soin": "Détartrage", "date_souhaitee": "2026-09-12", "heure_souhaitee": "14:30",
  "message": "Après-midi de préférence.", "consent": true, "consent_whatsapp": false,
  "email": "",                       // HONEYPOT : doit rester vide
  "ts": "1756123456.7f2a…",          // nonce signé HMAC (formulaire hébergé)
  "client_request_id": "9f2b1c04-…"  // idempotence
}
```
```jsonc
// 201 (200 sur rejeu idempotent) — aucun créneau, aucune info de disponibilité
{ "ok": true, "reference": "RDV-7F3K2Q", "status": "recue",
  "message": "Votre demande a bien été reçue. Le cabinet vous rappellera au 06 12 34 56 78." }
```

Validation à la main (pas de Pydantic : garde l'enveloppe d'erreur cohérente avec les handlers
globaux). `telephone` passe par `whatsapp_service.normalize_msisdn()` (CC 212 par défaut) →
`phone_e164` ; le brut est conservé dans `phone_raw`. `consent` doit valoir exactement `true`.
`date_souhaitee` bornée à `[aujourd'hui, aujourd'hui + horizon_days]`.

| Cas | Statut | `code` |
|---|---|---|
| Clé inconnue / révoquée | 401 | `invalid_key` |
| `Origin` présent et non autorisé | 403 | `origin_not_allowed` |
| Champ invalide | 400 | `invalid_phone` / `invalid_soin` / `consent_required` / `date_out_of_range` |
| Corps > 8 Kio | 413 | `payload_too_large` |
| Débit dépassé | 429 + `Retry-After` | `rate_limited` |
| `accepts_requests = 0` | 503 | `booking_closed` |
| **Honeypot rempli** | **201 + fausse référence**, ligne rangée en `status='spam'` | — |

`invalid_key` et `origin_not_allowed` renvoient le même texte français générique : un scanner
n'apprend pas quelles clés existent.

### CORS — par route, pas de middleware
`CORSMiddleware` fige `allow_origins` au démarrage ; notre liste vit dans
`website_integrations.allowed_origins` et change quand un praticien édite un réglage. Donc un
helper `_cors_headers(origin, allowed)` qui pose **toujours `Vary: Origin`** (sans lui, un cache
servirait l'en-tête d'un site à un autre), jamais `*`, jamais `Allow-Credentials`, et qui échoie
l'en-tête **aussi sur les réponses d'erreur** (sinon le navigateur masque le corps du 400 et le
site affiche « erreur réseau » pour une erreur de validation). `Origin` absent (curl, POST de
formulaire classique) → accepté, le rate-limit s'applique quand même.

### CSP de `/embed` — à faire précisément
Le middleware pose `X-Frame-Options: DENY` + `frame-ancestors 'none'` via `setdefault`, donc un
handler qui pose sa propre CSP gagne (précédent : `_TV_CSP` dans `salle_attente.py:58`). Mais
`X-Frame-Options` ne sait pas exprimer une **liste** d'origines et un `DENY` résiduel est encore
honoré par certains navigateurs. Donc, dans `main.py:120` :
```python
if "frame-ancestors" not in response.headers.get("Content-Security-Policy", ""):
    response.headers.setdefault("X-Frame-Options", "DENY")
```
Si `allowed_origins` est vide → `frame-ancestors 'none'` : une intégration sans origine déclarée
n'est embarquable nulle part. C'est le bon défaut.

### Anti-abus
| Clé de limitation | Seuil |
|---|---|
| `rdvpub:ip:{ip}` | 5 / 600 s |
| `rdvpub:key:{public_key}` | 30 / 3600 s |
| `rdvpub:phone:{e164}` | 3 / 86400 s |
| `rdvpub:badkey:{ip}` | 20 / 600 s (vérifié **avant** la recherche de clé) |
| `rdvmail:doctor:{id}` | 6 / 3600 s (anti-rafale sur l'e-mail au praticien) |

+ **honeypot** `email` (`position:absolute;left:-9999px`, `tabindex="-1"`) → accepté
silencieusement, rangé en `spam` ; + **nonce temporel** signé HMAC posé par la page (rejet si
âge < 3 s ou > 1 h) ; + **suppression de doublon** (même `phone_e164` + même date, < 24 h,
`status='nouvelle'` → renvoie la référence existante en 200) ; + **idempotence** sur
`client_request_id`. Pas de CAPTCHA en v1.

---

## Étape 4 — Module staff « Demandes de RDV » (`routers/demandes.py`)

Structure calquée sur [rappels.py](medfollow/routers/rappels.py) + [templates/rappels/index.html](medfollow/templates/rappels/index.html)
(le plus petit module complet du dépôt). **Pas de `dependencies=[Depends(deny_secretaire)]`** au
niveau du routeur : la secrétaire est l'opératrice principale. Portée systématique par
`effective_doctor_id(user)`, garde d'appartenance `WHERE id = ? AND doctor_id = ?`.

```python
GET  /demandes/                          # inbox, ?filtre=nouvelles|a_traiter|confirmees|planifiees|refusees|toutes
GET  /demandes/{id}                      # détail : verdict + créneaux + candidats patients
GET  /demandes/api/pending-count         # {"count": N} pour le badge
GET  /demandes/api/{id}/availability     # ?date=&time=&duration= → verdict + suggestions
POST /demandes/{id}/creneau              # → 'creneau_propose' | 409 {conflict, suggestions}
POST /demandes/{id}/appel                # {outcome, notes} → 'a_rappeler'|'confirmee'|'annulee'
POST /demandes/{id}/patient              # {patient_id} OU {first_name,last_name,date_of_birth,gender}
POST /demandes/{id}/planifier            # → INSERT appointments + 'planifiee' | 409
POST /demandes/{id}/refuser              # {motif}        ← praticien uniquement (403 secrétaire)
POST /demandes/{id}/spam
GET  /demandes/integrations              # réglages clés  ← praticien uniquement (403 secrétaire)
POST /demandes/integrations/new | /{iid}/update | /{iid}/revoke
```

Helper local, car `deny_secretaire` ne s'applique qu'au niveau module :
```python
def _require_medecin(user: dict) -> None:
    """Certaines decisions restent au praticien (refus, cles API)."""
    if user.get("role") == "secretaire":
        raise HTTPException(status_code=403, detail="Réservé au praticien")
```

Chaque transition écrit un audit via `services/audit.log_audit(...)` :
`demande_recue`, `demande_creneau`, `demande_appel`, `demande_patient`, `demande_planifiee`,
`demande_refusee`, `demande_spam`, avec `entity_type="booking_request"`.

### Verdict de disponibilité (page de détail)
| Saisie du patient | Affichage |
|---|---|
| Aucune date | « Aucune date souhaitée » + les 6 prochains créneaux libres (`next_free_slots`) |
| Date seule | Créneaux libres du jour + pastille `day_load` (libre / chargé / complet) |
| Date + heure | 🟢 « Créneau libre — Retenir » (1 clic) ou 🔴 « Occupé » + 4 alternatives le jour même, puis les 2 jours suivants |

`POST /demandes/{id}/creneau` **rejoue `has_conflict` côté serveur** et renvoie le même
`409 {"conflict": true, "suggestions": [...]}` si le créneau a été pris entre l'affichage et le
clic — le JS de la bannière de conflit existante est réutilisé tel quel.

### Rapprochement patient — et le problème `date_of_birth NOT NULL`
Le formulaire ne demande pas de date de naissance, or `patients.date_of_birth` est
`NOT NULL` (`connection.py:44`) et SQLite ne sait pas retirer un NOT NULL sans **reconstruire la
table la plus jointe du schéma** — exactement le danger documenté l.1029. Sentinelle
`1900-01-01` exclue également : `calc_age` afficherait un âge faux dans chaque en-tête de dossier,
ce qui est pire qu'une donnée absente.

**Réponse : la secrétaire la demande pendant l'appel de confirmation.** Elle a le patient au
téléphone à l'étape 6 ; « votre date de naissance, s'il vous plaît » coûte trois secondes et c'est
le seul moment où la donnée est réellement obtenable.

- Le modal « Créer une fiche » exige `date_of_birth`, et **son bouton est désactivé tant que
  `called_at IS NULL`**, avec l'indication « Enregistrez d'abord l'appel : c'est le moment de
  demander la date de naissance. »
- Règle appliquée côté serveur : `POST /planifier` renvoie `400 patient_required` si
  `patient_id IS NULL`. **Pas de RDV sans fiche, pas de fiche sans date de naissance.**

Rapprochement v1, sans changement de schéma : scan mémoire des patients du cabinet
(`WHERE doctor_id = ? AND is_active = 1`, quelques milliers de lignes) avec
`normalize_msisdn(r["phone"]) == phone_e164` pour les correspondances exactes, plus un
recoupement faible sur les mots du nom en « candidats possibles ». **Jamais automatique** : trois
boutons explicites — « Rattacher à *BENNANI Fatima (née le 04/03/1988)* », « Chercher un autre
patient », « Créer une nouvelle fiche ». Le `Nom complet` n'est jamais découpé en silence : le
modal pré-découpe (premier mot = prénom) en **deux champs éditables** et affiche la saisie brute
au-dessus.

### Création du RDV (`POST /{id}/planifier`), en une transaction
```sql
INSERT INTO appointments (patient_id, doctor_id, title, appointment_type, status,
                          start_datetime, end_datetime, notes)
VALUES (?, ?, ?, 'consultation', 'confirme', ?, ?, ?);
UPDATE booking_requests SET appointment_id = ?, patient_id = ?, status = 'planifiee',
       updated_at = CURRENT_TIMESTAMP
 WHERE id = ? AND doctor_id = ?;
```
`'confirme'` et non `'planifie'` : le patient a confirmé par téléphone, et c'est ce qui rend
`wr.sync_from_appointment` cohérent avec un RDV confirmé à la main. **Aucune colonne ajoutée à
`appointments`** — la recherche inverse est `SELECT … FROM booking_requests WHERE appointment_id = ?`.

### UI
- **Inbox** : copie structurelle de `rappels/index.html` — pastilles de comptage (« Nouvelles »,
  « À rappeler », « Confirmées, RDV à créer »), onglets de filtre, `<table class="table">`,
  téléphone en lien `tel:`, colonne « Fiche : ✅ liée / ⚠️ à créer »,
  `ORDER BY (status='nouvelle') DESC, created_at DESC`.
- **Détail** : trois cartes empilées qui suivent le flux humain — ① *La demande* (lecture seule,
  telle que tapée, + consentement + provenance) ② *Disponibilité & créneau* ③ *Appel &
  confirmation* (lien `tel:`, radio confirme/injoignable/renonce, notes, compteur de tentatives),
  puis la carte patient, puis le gros bouton vert **« Créer le rendez-vous »**, actif seulement si
  `status='confirmee' AND patient_id IS NOT NULL AND proposed_start IS NOT NULL`.

---

## Étape 5 — Notification

**Badge barre latérale** : copier exactement le motif `#msg-unread-badge` de
[templates/base.html](medfollow/templates/base.html) (l.344-365) — nouveau `<li>` après « Salle
d'attente » (~l.87) avec `id="rdv-pending-badge"`, et un poller de 30 s dans l'IIFE existante qui
déclenche `window.showToast('Nouvelle demande de rendez-vous', 'info')` quand le compteur monte.
Endpoint calqué sur `messages.py:133` :
`SELECT COUNT(*) … WHERE doctor_id = ? AND status IN ('nouvelle','a_rappeler')`.

**E-mail au praticien** (v1, sans risque) : `services/email_service.send_email()` est déjà en
dry-run quand SMTP n'est pas configuré. Déclenché via `BackgroundTasks` depuis le handler public
— **jamais en ligne** : un SMTP synchrone ferait dépendre la latence d'une route publique d'un
serveur externe et transformerait chaque POST en e-mail sortant. Anti-rafale par
`rate_limit.retry_after(f"rdvmail:doctor:{did}", 6, 3600)`.

**WhatsApp accusé de réception** (v2, code livrable dès maintenant en dry-run) : nouveau modèle
Meta `demande_recue` à faire approuver. **Ne pas réutiliser `rdv_confirmation`** — il affirme un
rendez-vous confirmé avec date et heure ; l'envoyer pour une demande non confirmée annoncerait au
patient un RDV qu'il n'a pas. Triple garde : `ack_whatsapp` + `users.whatsapp_enabled` +
`consent_whatsapp`. Ce dernier est une **case distincte** du consentement téléphonique de la
maquette : « accepter d'être rappelé par téléphone » ne couvre pas un message WhatsApp
(loi 09-08).

---

## Fichiers

### À créer
| Fichier | Contenu |
|---|---|
| `medfollow/services/scheduling.py` | Les 3 boucles de créneaux et les 2 requêtes de conflit, dédupliquées |
| `medfollow/services/booking.py` | Résolution d'intégration, génération/vérif. de clés, `origin_allowed`, `create_request` (validation + honeypot + dédup + idempotence), `match_patients`, `create_patient_from_request`, `create_appointment_from_request`, table `_ALLOWED` des transitions. Même rôle que `services/waiting_room.py`. |
| `medfollow/routers/rdv_public.py` | prefix `/public`. **Zéro dépendance d'auth, zéro `get_current_user`.** CORS par route, CSP par route pour `/embed`. |
| `medfollow/routers/demandes.py` | prefix `/demandes`, pas de `deny_secretaire`, helper `_require_medecin` |
| `medfollow/templates/rdv_public/{base_public,form,merci,ferme}.html` | Layout autonome — **ne pas** étendre `base.html` (barre latérale, `user`, patch fetch/CSRF) ni `base_embed.html` (fait pour l'odontogramme) |
| `medfollow/templates/demandes/{index,detail,integrations}.html` | Inbox / détail / réglages + snippet à copier |
| `medfollow/static/css/rdv-public.css` | Style autonome de la page publique |
| `medfollow/scripts/test_public_booking.ps1` | Simulateur de POST depuis le site |
| `deploy/Caddyfile` | TLS auto, limite de corps, `X-Forwarded-For` écrasé |

### À modifier
| Fichier | Changement |
|---|---|
| [main.py](medfollow/main.py) | `include_router` ×2 + **ajout des 2 routeurs à la liste de patch Jinja l.321** ; `"/public/"` dans l'exemption CSRF l.169 ; pas de cookie CSRF sous `/public/` l.220 ; garde `frame-ancestors` avant `X-Frame-Options` l.120 ; `/public` ignoré l.60 |
| [database/connection.py](medfollow/database/connection.py) | Les 2 `CREATE TABLE` + 4 index + `idx_appointments_doctor_start`, **tout à la fin de `init_db()`** |
| [routers/appointments.py](medfollow/routers/appointments.py) | Appels à `scheduling.*` à la place des l.120-139 / 168-207 / 280-313 ; `/api/free-slots` (l.98) ressuscité |
| [templates/base.html](medfollow/templates/base.html) | `<li>` + `#rdv-pending-badge` (~l.87) et son poller (~l.381) |
| [services/rate_limit.py](medfollow/services/rate_limit.py) | `prune(max_age_seconds)`, appelée depuis la boucle existante de `reminder_scheduler` |
| [services/audit.py](medfollow/services/audit.py) | `client_ip_public(request)` — voir risque n°2 |
| [config.py](medfollow/config.py) | `BOOKING_MAX_BODY_BYTES=8192`, `BOOKING_MAX_HORIZON_DAYS=180`, `WHATSAPP_TPL_DEMANDE_RECUE` ; et **lire enfin** `PUBLIC_BASE_URL` |
| `medfollow/.env.example`, `medfollow/scripts/smoke_test.py` | Nouvelles variables ; bloc `== Demandes de RDV ==` |

---

## Vérification

**Automatique** — `py medfollow/scripts/smoke_test.py`, vert avant *et* après le refactor
`scheduling.py`. Nouveau bloc :
- création d'intégration → `pk_live_…` ; `GET /public/rdv/{pk}` et `/embed` → 200 ; clé inconnue → 404
- `POST /public/api/rdv/{pk}` **sans jeton CSRF** → 201 (exemption effective) ; rejeu du même
  `client_request_id` → 200 + même référence
- erreurs : consentement manquant 400, téléphone invalide 400, hors horizon 400, clé inconnue 401,
  Origin interdite 403, corps trop gros 413, honeypot → 201 mais absent de l'inbox
- CORS : `OPTIONS` avec Origin autorisée → ACAO présent ; Origin inconnue → pas d'ACAO
- workflow : `/creneau` → `/appel` → `/planifier` **sans fiche → 400** → `/patient` → `/planifier` → 200
- **assertions de sécurité négatives** : réponse identique sous `/public/**` avec et sans cookie de
  session ; secrétaire → `/demandes/1/refuser` 403 et `/demandes/integrations` 403 ; médecin B →
  `/demandes/1` 404 (cloisonnement)
- non-régression agenda : `POST /appointments/api/new` en conflit → 409 + suggestions

**Manuelle, de bout en bout**
1. Connexion praticien → `/demandes/integrations` → nouvelle intégration, origine
   `http://localhost:5500`, liste de soins. Copier le snippet.
2. Coller le snippet dans un `test-site.html` servi sur `http://localhost:5500` (Live Server) →
   le formulaire s'affiche dans l'iframe, aucune erreur CSP en console.
3. Envoyer → page de remerciement avec référence. Vérifier que le texte dit bien que **rien n'est
   encore réservé**.
4. Onglet Doctivo laissé ouvert : sous 30 s le badge passe à 1 et le toast se déclenche.
5. `/demandes` → ouvrir le détail → le verdict indique libre/occupé avec alternatives → retenir un créneau.
6. Se reconnecter en **secrétaire** liée à ce praticien : elle voit la demande, enregistre l'appel,
   crée la fiche (avec date de naissance), crée le RDV ; « Refuser » et `/demandes/integrations` → 403.
7. Vérifier dans FullCalendar que le RDV est là en statut `confirme`, et en base que
   `booking_requests` a `appointment_id`, `patient_id` et `status='planifiee'`.
8. Prendre d'abord le créneau à la main dans l'agenda puis réessayer `/planifier` → 409 + bannière.
9. Servir `test-site.html` depuis un autre port → iframe bloqué (`frame-ancestors`). Comportement attendu.
10. `sqlite3 data/medfollow.db ".schema booking_requests"` après **deux redémarrages consécutifs** —
    confirme que les tables survivent au rejeu de `init_db()` (piège l.1029).
11. `audit_log` contient bien `demande_recue`, `demande_creneau`, `demande_appel`, `demande_patient`,
    `demande_planifiee`.

---

## Risques

| # | Risque | Mitigation |
|---|---|---|
| 1 | **Écriture publique sur une app médicale.** N'importe qui peut créer des lignes. | Table de quarantaine qu'aucun code clinique ou financier ne lit ; ni fiche patient ni RDV sans un humain au téléphone ; rate-limits + honeypot + dédup ; audit sur chaque transition. |
| 2 | **`client_ip()` (`audit.py:44`) prend le *premier* élément de `X-Forwarded-For`**, entièrement contrôlé par le client → le seau par IP se contourne en une ligne. | `client_ip_public()` utilisant le saut de proxy, **et** Caddy/nginx qui **écrase** XFF par l'IP réelle. |
| 3 | **`_BUCKETS` du rate-limiter n'est jamais purgé** (`rate_limit.py:9`) ; avec des IP et des téléphones choisis par l'attaquant, la mémoire croît sans borne sur une petite VM. | `prune()` appelée depuis la boucle `reminder_scheduler` qui tourne déjà toutes les 600 s. |
| 4 | **Rate-limiter mono-processus.** Se multiplierait silencieusement le jour où l'on passe à `--workers 2`. | Documenté dans le docstring du routeur ; `limit_req` côté proxy en filet indépendant du processus. |
| 5 | **Exemption CSRF élargie à tout `/public/`.** | Les deux règles dures ci-dessus, dont une assertion de smoke test vérifiant qu'une session n'accorde rien de plus. |
| 6 | **La liste blanche d'Origin n'est pas une authentification** (curl forge n'importe quel Origin). | Le dire explicitement dans l'UI des réglages ; le pire cas reste une ligne de spam en quarantaine, jamais un créneau réservé. Mode HMAC en v2 pour qui a un vrai backend. |
| 7 | **Le refactor `scheduling.py` touche du code d'agenda en production.** | Commit isolé, extraction pure, smoke test avant/après ; forme du 409 et bannière de conflit inchangées. |
| 8 | **`/docs`, `/redoc` et `/openapi.json` sont publics** et énumèrent toutes les routes internes d'une app médicale (pré-existant, `main.py:44`). | `docs_url=None, redoc_url=None, openapi_url=None` — prérequis de l'item roadmap « API REST documentée ». |
| 9 | Trois pollers de 30 s, une connexion SQLite chacun. | Acceptable à cette échelle ; fusionner en `/api/badges` seulement si ça se voit un jour. |

---

## Recommandations — actions concrètes pour lever les risques

Chaque ligne est une action réalisable, rattachée à son risque. Les **R1 à R6 sont bloquantes** :
elles doivent être faites *dans* la v1, pas après.

### R1 — TLS avant toute clé remise (risque 12 du constat initial, prérequis de tout le reste)
- Installer Caddy sur la VM, conf versionnée dans `deploy/Caddyfile` (aujourd'hui rien de la VM
  n'est dans le dépôt : le nginx en place n'existe que sur la machine).
- `MEDFOLLOW_HTTPS=1` dans l'unité systemd → cookies `Secure` + HSTS.
- **Critère de sortie :** `curl -I https://app.doctivo.org/health` renvoie 200 avec
  `Strict-Transport-Security`, et le cookie `access_token` porte `Secure`.
- **Règle organisationnelle :** aucune ligne dans `website_integrations` pour un vrai praticien
  tant que ce critère n'est pas vert.

### R2 — Neutraliser l'usurpation d'IP (risque 2)
Sans ça, tous les seaux `rdvpub:ip:` se contournent avec un simple en-tête forgé.
- Dans `deploy/Caddyfile`, **écraser** l'en-tête au lieu de le concaténer :
  ```
  handle /public/api/* {
      request_header X-Forwarded-For {remote_host}   # ECRASE la valeur envoyee par le client
      request_body   max_size 16KB
      reverse_proxy 127.0.0.1:8000
  }
  ```
- Ajouter dans `services/audit.py` une fonction **distincte** (ne pas toucher `client_ip`, utilisée
  partout dans l'app authentifiée) :
  ```python
  def client_ip_public(request) -> str:
      """IP pour les routes PUBLIQUES : ne fait confiance qu'au dernier saut de proxy.
      client_ip() prend le PREMIER element de X-Forwarded-For, que le client controle
      entierement — utilisable pour l'audit interne, jamais pour du rate-limiting public."""
      xff = request.headers.get("x-forwarded-for", "")
      if xff:
          return xff.split(",")[-1].strip()
      return getattr(request.client, "host", "") or ""
  ```
- L'utiliser **uniquement** sous `/public/`.
- **Test de non-régression :** deux POST avec `X-Forwarded-For: 1.2.3.4` puis `5.6.7.8` doivent
  tomber dans le **même** seau et déclencher le 429.

### R3 — Borner la mémoire du rate-limiter (risque 3)
- Ajouter `prune(max_age_seconds=86400)` dans `services/rate_limit.py` : itérer sur `_BUCKETS`,
  vider les `deque` dont tous les horodatages sont périmés, supprimer les clés vides.
- L'appeler depuis la boucle existante de `services/reminder_scheduler.py` (elle tourne déjà toutes
  les 600 s — zéro nouvelle infrastructure, un seul fichier touché).
- **Critère :** après 10 000 POST avec des téléphones différents, `len(_BUCKETS)` retombe au
  prochain tick.

### R4 — Verrouiller l'exemption CSRF (risque 5)
- Écrire les deux règles en **docstring du module** `routers/rdv_public.py`, pas dans un commentaire
  perdu : *(1) aucun handler sous `/public/` ne lit `access_token` ni n'appelle `get_current_user` ;
  (2) le cookie CSRF n'y est pas posé.*
- Les rendre **testables** plutôt que déclaratives — assertion de smoke test : le même
  `POST /public/api/rdv/{pk}` envoyé avec et sans cookie de session doit produire une réponse
  **identique** (statut + corps, référence mise à part).
- Garde-fou statique : `grep -n "get_current_user\|access_token" medfollow/routers/rdv_public.py`
  doit ne rien renvoyer — à ajouter en fin de `smoke_test.py`.

### R5 — Être honnête sur ce que vaut la liste d'Origin (risque 6)
- Afficher l'avertissement **dans** `templates/demandes/integrations.html`, à côté du champ, pas
  dans une doc annexe : « Cette liste empêche les *navigateurs* d'autres sites d'utiliser votre
  clé. Elle n'empêche pas un script d'usurper l'origine. C'est sans danger : au pire, une demande
  indésirable arrive dans votre boîte — jamais un créneau réservé. »
- Défaut sûr à la création : `allowed_origins = []` → aucun POST navigateur, aucun embarquement
  possible tant que le praticien n'a pas déclaré son domaine.
- Renvoyer le **même texte générique** pour `invalid_key` et `origin_not_allowed`, et s'assurer que
  les deux chemins font le même nombre de requêtes SQL (une seule) : un scanner ne doit pas pouvoir
  distinguer « clé inexistante » de « origine refusée », ni au message ni au temps de réponse.

### R6 — Rendre le refactor de l'agenda bisectable (risque 7)
- `services/scheduling.py` et la réécriture des 3 sites d'appel = **un commit à part**, poussé et
  vérifié avant que la moindre ligne du module « demandes » soit écrite.
- Extraction **littérale** : mêmes constantes (08:00 / 19:30 / pas de 30 min), même comparaison de
  chaînes `s_str < b_end and e_str > b_start`, mêmes limites (`8` créneaux pour `free-slots`,
  `4` suggestions sur conflit). Aucune « amélioration » dans ce commit.
- `py medfollow/scripts/smoke_test.py` vert **avant** et **après**, plus une vérification manuelle :
  créer un RDV en conflit dans l'agenda → la bannière `#conflict-banner` et ses suggestions
  cliquables se comportent exactement comme avant.

### R7 — Fermer `/docs`, `/redoc`, `/openapi.json` (risque 8, pré-existant)
Ils sont publics aujourd'hui et énumèrent toutes les routes internes d'une application médicale —
c'est une carte offerte à quiconque scanne le domaine, et ça le devient d'autant plus une fois le
domaine public annoncé aux praticiens.
- `FastAPI(title=…, lifespan=…, docs_url=None, redoc_url=None, openapi_url=None)` dans `main.py:44`.
- Si vous voulez les garder pour le développement : les conditionner à une variable
  (`MEDFOLLOW_DOCS=1`, désactivée sur la VM) plutôt que de les laisser ouverts.
- **Vérification :** `curl -si https://app.doctivo.org/openapi.json` → 404.

### R8 — Protéger la table de quarantaine dans la durée (risque 1)
Le cloisonnement ne tient que si personne ne le perce plus tard par mégarde.
- Écrire la règle en tête de `booking_requests` dans `connection.py` : *« Aucun code clinique,
  financier ou de rappel ne doit lire cette table. Le seul pont vers `patients` / `appointments`
  passe par `POST /demandes/{id}/planifier`, après un appel téléphonique enregistré. »*
- La rendre vérifiable : `grep -rn "booking_requests" medfollow/` ne doit apparaître que dans
  `services/booking.py`, `routers/demandes.py`, `routers/rdv_public.py` et
  `database/connection.py`. À transformer en assertion de `smoke_test.py`.
- Purge : les lignes `status='spam'` de plus de 30 jours sont supprimées par le tick de
  `reminder_scheduler` (même passage que `rate_limit.prune()`).

### R9 — Documenter la contrainte mono-processus (risque 4)
Elle est aujourd'hui vraie et correcte ; elle devient un trou de sécurité silencieux le jour où
quelqu'un ajoute `--workers 2` (chaque worker aurait ses propres seaux → limite multipliée).
- Docstring du routeur public **et** commentaire dans l'unité systemd, à côté de la ligne
  `ExecStart` : *« uvicorn DOIT rester en un seul worker : rate_limit et reminder_scheduler sont en
  mémoire de processus. »*
- Filet indépendant du processus : `rate_limit` côté Caddy sur `/public/api/*`, qui reste efficace
  même si la contrainte est un jour violée.

### R10 — Consentement WhatsApp séparé (risque légal, loi 09-08)
- Case **distincte et facultative** sur le formulaire : « J'accepte de recevoir la confirmation par
  WhatsApp » → colonne `consent_whatsapp`, recopiée (inversée) dans `patients.whatsapp_opt_out` à
  la création de la fiche.
- Ne **jamais** dériver ce consentement de la ligne « vous acceptez d'être recontacté par
  téléphone » : elle couvre un appel, pas un message.
- Modèle Meta dédié `demande_recue` ; interdiction explicite de réutiliser `rdv_confirmation`, qui
  annoncerait au patient un rendez-vous qu'il n'a pas.

### À surveiller, sans action immédiate
- **Trois pollers de 30 s** (risque 9) : fusionner en un `GET /api/badges` seulement si la charge
  se voit. Le faire maintenant toucherait `messages.py`, `salle_attente.py` et `base.html` pour
  aucun gain visible.
- **Absence de déduplication des patients** : réglée fonctionnellement en v1 (rapprochement
  proposé, jamais automatique) ; le vrai correctif est `patients.phone_e164` + index en v2.

---

## Phases

**v1** (ce plan) : étapes 0 → 5. La boucle complète, formulaire hébergé, aucune fuite de planning.

**v2** : verdict par jour `libre/chargé/complet` (jours pleins grisés dans le sélecteur de date,
opt-in) · mode serveur-à-serveur HMAC `require_secret=1` · ouverture aux formulaires tiers avec
`GET /public/api/rdv/{key}/nonce` · `patients.phone_e164` + backfill + index → rapprochement exact ·
**horaires par praticien** (`doctor_schedule`, `doctor_days_off`) remplaçant le 08:00–19:30 codé en
dur — `services/scheduling.py` est le point unique de branchement, c'est tout l'intérêt de
l'extraction · WhatsApp `demande_recue` · `/static/js/rdv-embed.js` auto-redimensionnant.

**v3** : vraie réservation en self-service avec sélecteur de créneaux et verrou temporaire
(`slot_holds`, TTL 10 min) — exige les horaires par praticien de la v2 · CAPTCHA Turnstile ·
plugin WordPress · API REST publique documentée.
