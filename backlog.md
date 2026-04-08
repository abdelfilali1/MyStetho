# Doctivo — Backlog

> Priorités : 🔴 Critique · 🟠 Important · 🟡 Amélioration · 🟢 Nice-to-have

---

## Application (FastAPI)

### Agenda & Rendez-vous

| # | Priorité | Feature | Détail |
|---|---|---|---|
| A1 | 🔴 | **Conflit de créneau** | Bloquer la création d'un RDV si le créneau est déjà pris. Afficher un message d'erreur clair + proposer les créneaux libres du même jour. |
| A2 | 🟠 | **Modifier RDV depuis le dashboard** | Permettre le changement de date/heure directement depuis la vue agenda. Proposer automatiquement un nouveau créneau disponible. |
| A3 | 🟡 | **Notifications patients** | Envoyer un message au patient (SMS / email) pour : proposition d'un nouveau créneau, ou absence/fermeture du cabinet. |

### Dossier Patient

| # | Priorité | Feature | Détail |
|---|---|---|---|
| A4 | 🔴 | **Cohérence antécédents** | Les antécédents dans la fiche patient (diabète, HTA, allergies, etc.) doivent être identiques et synchronisés avec le formulaire de consultation. Un seul endroit de saisie, affiché partout. |
| A5 | 🟠 | **Mutuelle & Assurance** | Ajouter dans la fiche patient : organisme (CNOPS / CNSS / AMO / MAMDA / autre), numéro d'affiliation, numéro de série. Afficher sur les factures et ordonnances. |

### Odontogramme & Dentaire

| # | Priorité | Feature | Détail |
|---|---|---|---|
| A6 | 🟠 | **Détartrage multi-dents** | Permettre d'appliquer le traitement "Détartrage" à toutes les dents en une seule action (bouton "Appliquer à toutes les dents"). Actuellement il faut le faire dent par dent. |
| A7 | 🟡 | **Historique condition par dent** | Ajouter un historique chronologique des conditions par dent (ex : dent 21 — Saine → Carie → Obturée). Visible dans le panel de la dent. |

---

## Site Marketing (doctivo-site)

| # | Priorité | Feature | Détail |
|---|---|---|---|
| S1 | 🟠 | **Brochures de l'application** | Créer des brochures PDF téléchargeables depuis le site : présentation des fonctionnalités, tarifs, guide de démarrage rapide. Une version à imprimer pour les cabinets. |
| S2 | 🟡 | **Page assurances/mutuelles** | Ajouter une section ou page dédiée aux organismes pris en charge (CNOPS, CNSS, AMO, MAMDA, RMA, Saham) avec calendrier d'intégration. |

---

## En attente de décision

| # | Sujet | Question ouverte |
|---|---|---|
| D1 | Notifications patients | Canal préféré : SMS (coût), email, ou WhatsApp ? |
| D2 | Mutuelle | Le numéro de série doit-il apparaître sur l'ordonnance PDF ou uniquement sur la facture ? |
| D3 | Brochures | Format : A4 recto-verso ou trifold ? Langue : FR uniquement ou FR + AR ? |
