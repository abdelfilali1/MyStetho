# Doctivo — Backlog

Status: `- [ ]` todo · `- [~]` in progress · `- [x]` done · `- [!]` blocked

---

## App — Fonctionnalités

- [x] A1 — Conflit créneau : blocage + suggestions de créneaux libres
- [x] A2 — Déplacer RDV depuis l'agenda avec vérification de conflit
- [x] A4 — Cohérence antécédents fiche patient ↔ formulaire consultation
- [x] A5 — Mutuelle & Assurance : dropdown organismes maroc + N° série carte
- [x] A6 — Détartrage appliqué à toutes les dents (32) en un clic
- [x] A7 — Historique condition par dent avec toggle afficher/masquer

## Bugs (validés 2026-04-08)

- [x] B1 — Calcul d'âge approximatif : ajouter filtre Jinja2 `calc_age` tenant compte du mois/jour
- [x] B2 — Statut de facture affiché brut (`PARTIELLEMENT_PAYEE`) : ajouter mapping lisible
- [x] B3 — Clé JWT non persistée sur Railway : lire `MEDFOLLOW_SECRET_KEY` depuis env variable
- [x] B4 — Race condition numéro de facture : transaction SQLite exclusive sur la génération
- [x] B5 — Posologie & fréquence ordonnance en select fixe : remplacer par input + datalist
- [x] B6 — Email affiché au lieu du nom praticien dans la sidebar : ajouter first_name/last_name au JWT
- [x] B7 — Tri des colonnes absent dans la liste patients : ajouter sort_by/sort_order query params

## Bugs (validés 2026-04-24)

- [x] B8 — Ownership manquant sur delete/status RDV : vérifier `doctor_id` avant suppression ou changement de statut **(Sécurité Majeure)** *(2026-04-25)*

## UX (validés 2026-04-24)

- [x] U1 — Vue liste agenda : activer `listWeek`/`listMonth` dans FullCalendar **(UX-12 — Haute)** *(2026-04-25)*

- [x] U2 — Bouton annulation facture : route POST `/cancel` + bouton conditionnel dans `detail.html` **(UX-13 — Moyenne)** *(2026-04-25)*

- [x] U3 — Colonne "Dernière visite" dans liste patients **(UX-15 — Moyenne)** *(2026-04-25)*

- [x] U4 — Export CSV factures : endpoint `/export.csv` + bouton dans `list.html` **(UX-16 — Haute)** *(2026-04-25)*
  

## Site — Doctivo.ma

- [x] S1 — Brochures PDF patients (design + génération ReportLab)


