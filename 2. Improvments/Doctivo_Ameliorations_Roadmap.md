# Doctivo — Feuille de route « best-in-class / état de l'art »

## Contexte
Audit complet du code (16 routers, 38 tables, 42 templates, services PDF/WhatsApp/IA) pour identifier ce qui sépare Doctivo d'un logiciel de gestion de cabinet dentaire best-in-class. Les points sont classés par catégorie, avec priorité (🔴 critique, 🟠 important, 🟢 différenciant) et ancrés sur des constats réels du code.

---

## 1. Sécurité & Conformité (loi 09-08 / RGPD)

- 🔴 **HTTPS obligatoire en production** — la VM Oracle tourne en HTTP pur (`medfollow/Push to VM`, `MEDFOLLOW_HTTPS` désactivé par défaut). Des données de santé transitent en clair ; les cookies ne sont pas `Secure`, HSTS inactif, et le webhook WhatsApp entrant ne peut pas fonctionner. → Caddy ou nginx + Let's Encrypt sur la VM, `MEDFOLLOW_HTTPS=1`.
- 🔴 **Chiffrement au repos** — `medfollow.db` et `uploads/` sont en clair sur le disque. → chiffrement du volume (LUKS) ou SQLCipher ; a minima chiffrer les sauvegardes hors-site.
- 🟠 **2FA (TOTP)** pour les comptes médecins/admin — standard attendu d'un logiciel santé moderne. Actuellement : mot de passe seul (bcrypt, bon, mais insuffisant).
- 🟠 **Interface de consultation du journal d'audit** — `audit_log` existe (`services/audit.py`) mais aucune page admin pour l'exploiter. La conformité exige de pouvoir *démontrer* la traçabilité.
- 🟠 **Verrouillage de session / déconnexion auto** sur inactivité (JWT 8h fixe aujourd'hui) + révocation de session (le JWT stateless ne peut pas être invalidé avant expiration).
- 🟠 **Supprimer l'email admin personnel codé en dur** (`config.py:65`, `ADMIN_EMAIL` par défaut) — à exiger via env sans valeur par défaut.
- 🟢 **Réduire `unsafe-inline` dans la CSP** — extraire le JS inline de `base.html` et des gros templates vers des fichiers statiques + nonces.
- 🟢 **Export RGPD par patient** (droit à la portabilité) et purge/anonymisation programmée des patients inactifs.

## 2. Fiabilité, Tests & CI/CD

- 🔴 **Suite de tests automatisée** — aujourd'hui un seul script smoke (`scripts/smoke_test.py`). → pytest + httpx TestClient : tests par router (auth, IDOR, CSRF, workflows devis→facture, paiements), fixtures DB temporaire. Cibler d'abord les flux facturation/paiement (argent) et droits d'accès (sécurité).
- 🔴 **CI GitHub Actions** — aucun `.github/` : lancer tests + lint (ruff) + audit deps (pip-audit) à chaque push.
- 🟠 **Migrations versionnées** — remplacer les dizaines de `ALTER TABLE ... except: pass` de `database/connection.py` (903 lignes) par des migrations numérotées (table `schema_version` maison, ou Alembic même sans ORM).
- 🟠 **Déploiement scripté** — remplacer la note manuelle `Push to VM` par un script idempotent (rsync + migration + restart systemd + smoke test post-deploy + rollback).
- 🟢 **Logging structuré** (JSON) au lieu de `traceback.print_exception` vers stdout, avec rotation ; intégrer Sentry (self-host ou SaaS) pour les erreurs.

## 3. Base de données & Performance

- 🔴 **Créer des index** — 38 tables, jointures partout, **zéro `CREATE INDEX`**. → index sur toutes les FK chaudes : `patients(doctor_id, is_active)`, `appointments(doctor_id, start_time)`, `consultations(patient_id)`, `invoices(patient_id, status)`, `audit_log(created_at)`, `whatsapp_messages(appointment_id)`, etc. Gain immédiat, risque nul.
- 🟠 **Supprimer la requête DB par requête HTTP** du middleware `_inject_active_consultation` (`main.py:54-81`) — mettre en cache par utilisateur (TTL court) ou ne l'exécuter que sur les pages HTML.
- 🟠 **Cache statique** — aucun header `Cache-Control`/ETag sur `/static` (dont le modèle ONNX de plusieurs Mo rechargé par le navigateur). → immutable + cache-busting déjà en place via `?v=`.
- 🟢 **Miniatures d'images** — les photos intra/extra-orales et radios sont servies pleine taille ; générer des thumbnails (Pillow déjà présent).
- 🟢 Préparer la **multi-instance** : rate-limit et scheduler sont en mémoire mono-processus (`services/rate_limit.py`, `reminder_scheduler.py`) — acceptable aujourd'hui, à documenter comme contrainte ; passer sur SQLite/Redis partagé si multi-workers un jour.

## 4. Ops, Sauvegardes & Supervision

- 🔴 **Sauvegarde hors-site automatisée et testée** — `backup_medfollow.sh` est bon (WAL-safe) mais installation manuelle et pas d'off-site actif. → cron installé + envoi chiffré vers OCI Object Storage + **test de restauration mensuel** + alerte si la sauvegarde échoue.
- 🟠 **Supervision** — `/health` existe mais personne ne le surveille. → UptimeRobot/Healthchecks.io (gratuit) + alerte disque plein (SQLite + uploads sur une petite VM).
- 🟠 **systemd + nginx/Caddy versionnés dans le repo** (dossier `deploy/`) — aujourd'hui la config VM vit hors repo, irreproductible.
- 🟢 **Dockerfile** pour reproductibilité locale/VM (Procfile/railway.toml existent déjà).

## 5. Expérience Patient (le plus gros différenciateur)

- 🔴 **Terminer les questionnaires patients** — tables `questionnaires`/`questionnaire_responses` avec `access_token` public déjà en place, mais `templates/questionnaires/` est **vide** et aucune route publique. → page publique par token (envoyée par WhatsApp avant le RDV), anamnèse pré-remplie dans la consultation.
- 🟠 **Prise de RDV en ligne** — le "free-slot finder" existe déjà (`/appointments/api/free-slots`) ; il manque une page publique de réservation (avec validation par le cabinet). C'est LA fonctionnalité attendue d'un logiciel état de l'art (Doctolib-like).
- 🟠 **Portail patient léger** : consulter ses RDV, ses devis (accepter en ligne), ses documents/ordonnances — par lien à token sécurisé, sans compte au début.
- 🟢 **Rappels enrichis** : file d'attente/liste de rappel en cas d'annulation, message post-soin, demande d'avis Google après RDV terminé.

## 6. Fonctionnalités métier manquantes

- 🟠 **Module certificats & attestations** — « certificat médical » n'existe que comme motif de RDV ; aucun générateur. → modèles paramétrables (certificat, attestation de présence, arrêt) branchés sur le PDF service existant (`services/pdf_service.py`).
- 🟠 **Consentements éclairés signés** (extraction, implanto, ortho) — génération PDF + signature sur tablette (canvas) + archivage dans documents.
- 🟠 **Tableau de bord financier** — CA par période/praticien/acte, impayés et relances, taux d'acceptation des devis, taux de RDV honorés. Les données existent toutes (invoices, payments, devis, appointments) ; il manque la vue.
- 🟢 **Gestion de stock** (consommables, implants avec lots/péremption) et **suivi labo** (travaux prothèse envoyés/reçus) — présents chez les leaders du marché.
- 🟢 **Plans de traitement multi-étapes** reliant devis → séances → soins réalisés sur l'odontogramme.

## 7. UX / UI

- 🟠 **PWA** — manifest + service worker : installable sur tablette au fauteuil, cache des assets (dont modèles ONNX). Aucun aujourd'hui.
- 🟠 **Accessibilité** — partielle (quelques aria-labels) ; ajouter skip-links, focus visibles, contrastes vérifiés.
- 🟢 **Mode sombre** (`prefers-color-scheme`) — les CSS custom properties de `style.css` rendent ça peu coûteux.
- 🟢 **Découper les méga-templates** — `patients/detail.html` (2400 lignes), `dental/chart.html` (1792) : extraire le JS inline en modules, composants Jinja réutilisables.
- 🟢 **i18n** (arabe/anglais) si ambition au-delà du cabinet initial — actuellement français codé en dur.

## 8. IA & état de l'art (capitaliser sur l'avance existante)

Doctivo a déjà deux vrais différenciateurs (céphalométrie IA + Radio IA navigateur). Pour être état de l'art :

- 🟠 **Assistant de compte-rendu** : génération du résumé de consultation / courrier confrère à partir des données structurées (API Claude), avec relecture obligatoire du praticien.
- 🟠 **Fiabiliser Radio IA** : afficher les scores de confiance, journal des détections rejetées (déjà stockées) pour mesurer la précision réelle, et avertissement médico-légal clair « aide au diagnostic, ne remplace pas le praticien ».
- 🟢 **Dictée vocale** pour les observations de consultation (Web Speech API ou Whisper) — mains occupées au fauteuil.
- 🟢 **Analyses céphalo supplémentaires** (Ricketts, Tweed…) — `steiner` seul aujourd'hui.
- 🟢 **Aide à la prescription** : le module alertes allergies/interactions existe ; l'enrichir avec posologies par défaut et contre-indications par terrain (grossesse, insuffisance rénale).

## 9. Interopérabilité

- 🟢 **Export/import standardisés** : export complet patient (PDF + JSON structuré), import DICOM pour les radios (PyMuPDF/Pillow ne lisent pas le DICOM des capteurs), export comptable pour l'expert-comptable.
- 🟢 **API REST documentée** (OpenAPI est déjà généré par FastAPI — le publier proprement) pour intégrations futures.

---

## Ordre d'attaque recommandé

1. **Semaine 1 — les 🔴 rapides** : HTTPS sur la VM, index DB, cron backup + off-site, monitoring `/health`. Quasi que de la config, gain maximal.
2. **Semaine 2-3 — filet de sécurité** : pytest + CI, migrations versionnées, script de déploiement.
3. **Ensuite — valeur visible** : questionnaires patients (déjà à moitié construits), module certificats, dashboard financier, prise de RDV en ligne.
4. **En continu — différenciation IA/UX** : PWA, compte-rendu assisté, dictée.

## Vérification
Chaque lot se valide par : `py scripts/smoke_test.py` (existant), la nouvelle suite pytest en CI, et un test manuel sur la VM après déploiement (HTTPS, webhook WhatsApp, restauration de sauvegarde).
