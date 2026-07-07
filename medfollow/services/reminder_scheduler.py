"""Planificateur des rappels WhatsApp 24 h avant le rendez-vous.

Boucle asyncio légère (aucune dépendance externe) démarrée dans le `lifespan`
de `main.py`. À chaque tick (~10 min, `REMINDER_POLL_SECONDS`), on cherche les
rendez-vous qui entrent dans la fenêtre « dans les 24 h à venir » et dont le
rappel n'a pas encore été envoyé, puis on délègue l'envoi à `whatsapp_service`.

Idempotence : le garde-fou `whatsapp_reminder_sent_at IS NULL` garantit un seul
rappel par rendez-vous ; la fenêtre « prochaines 24 h » fait qu'un redémarrage
rattrape les rendez-vous à venir non encore rappelés (aucun créneau perdu).

Hypothèses de fuseau : `start_datetime` est un datetime naïf en heure locale du
serveur ; on compare donc à `datetime('now','localtime')`. La VM doit être en
heure de la clinique (Africa/Casablanca) — cf. plan / vm-deployment.

Mono-processus : l'app tourne en un seul worker uvicorn, donc la boucle ne
double-déclenche pas. En cas de passage à plusieurs workers, il faudrait ne
lancer la boucle que dans un worker (ou basculer sur un timer systemd).
"""
import asyncio
import traceback

import aiosqlite

import config
from services import whatsapp_service


# Rendez-vous éligibles à un rappel : à venir dans les 24 h, non encore rappelés,
# statut actif, patient joignable (numéro présent + pas d'opt-out). Le dernier
# critère évite un rappel juste après la confirmation pour un RDV pris à court
# terme (< 24 h) : on ne rappelle que si le RDV démarre > 24 h après sa
# confirmation d'envoi (comparaison en heure locale des deux côtés).
_DUE_QUERY = """
    SELECT a.id
    FROM appointments a
    JOIN patients p ON a.patient_id = p.id
    JOIN users u    ON a.doctor_id  = u.id
    WHERE a.whatsapp_reminder_sent_at IS NULL
      AND a.status IN ('planifie', 'confirme')
      AND COALESCE(u.whatsapp_enabled, 1) = 1
      AND datetime(replace(a.start_datetime, 'T', ' ')) >  datetime('now', 'localtime')
      AND datetime(replace(a.start_datetime, 'T', ' ')) <= datetime('now', 'localtime', '+24 hours')
      AND COALESCE(p.whatsapp_opt_out, 0) = 0
      AND p.phone IS NOT NULL AND TRIM(p.phone) <> ''
      AND (
            a.whatsapp_confirmation_sent_at IS NULL
            OR datetime(replace(a.start_datetime, 'T', ' ')) >
               datetime(a.whatsapp_confirmation_sent_at, '+24 hours')
          )
    ORDER BY a.start_datetime
"""


async def run_due_reminders() -> int:
    """Envoie les rappels dus. Renvoie le nombre de rappels effectivement envoyés."""
    try:
        db = await aiosqlite.connect(config.DATABASE_PATH)
    except Exception:
        traceback.print_exc()
        return 0
    try:
        cur = await db.execute(_DUE_QUERY)
        ids = [row[0] for row in await cur.fetchall()]
    except Exception:
        traceback.print_exc()
        ids = []
    finally:
        await db.close()

    sent = 0
    for appt_id in ids:
        try:
            if await whatsapp_service.send_due_reminder(appt_id):
                sent += 1
        except Exception:
            traceback.print_exc()
    if ids:
        print(f"[reminders] {len(ids)} RDV dus, {sent} rappel(s) envoyé(s)")
    return sent


async def reminder_loop():
    """Boucle infinie : traite les rappels dus puis attend l'intervalle configuré."""
    # Petit délai de démarrage : laisse l'app finir de s'initialiser.
    try:
        await asyncio.sleep(15)
    except asyncio.CancelledError:
        return
    while True:
        try:
            await run_due_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
        try:
            await asyncio.sleep(max(60, config.REMINDER_POLL_SECONDS))
        except asyncio.CancelledError:
            return


def start(app) -> None:
    """Démarre la boucle et garde une référence sur la tâche (annulée à l'arrêt)."""
    app.state.reminder_task = asyncio.create_task(reminder_loop())


async def stop(app) -> None:
    """Annule proprement la boucle au shutdown."""
    task = getattr(app.state, "reminder_task", None)
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
