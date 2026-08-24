"""Salle d'attente : file d'attente du jour, reliée à l'agenda.

Toute la logique métier du module vit ici pour que `routers/appointments.py` et
`routers/consultations.py` puissent synchroniser la file sans dupliquer de SQL.

Chaîne complète : RDV planifié → arrivée (pointage) → file d'attente → appel
→ consultation → terminé.

Règle de tri : `sort_order ASC` seul, pour qu'un réordonnancement manuel ne
soit jamais contredit par un autre critère. `sort_order` est initialisé en
minutes depuis minuit (heure du RDV, ou heure d'arrivée pour un patient sans
RDV) : la file suit l'agenda par défaut et les sans-RDV s'intercalent au bon
endroit. Marquer une urgence place l'entrée en tête (voir `set_priority`).

Confidentialité : l'écran de la salle d'attente ne reçoit jamais de nom complet,
d'identifiant patient ni de motif — `public_board()` ne renvoie que des libellés
déjà anonymisés côté serveur (voir `format_display_name`).
"""
from datetime import date, datetime
import json
import secrets
from typing import Optional

import aiosqlite

TS_FMT = "%Y-%m-%d %H:%M:%S"

NAME_MODES = ("full", "initial", "ticket")
QUEUE_STATUSES = ("attente", "appele", "en_cours", "termine", "absent", "parti")

DEFAULT_TICKER = [
    "Merci de patienter, vous serez appelé(e) par votre nom.",
    "Merci de mettre votre téléphone en mode silencieux.",
]


def now_ts() -> str:
    return datetime.now().strftime(TS_FMT)


def today_str() -> str:
    return date.today().isoformat()


def ticket_label(ticket_no) -> str:
    try:
        return "A-%02d" % int(ticket_no)
    except (TypeError, ValueError):
        return ""


def _parse_ts(value) -> Optional[datetime]:
    """Les horodatages maison sont naïfs et locaux ; on tolère aussi le format
    ISO avec 'T' et l'absence de secondes."""
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in (TS_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _minutes_of_day(value) -> int:
    dt = _parse_ts(value)
    if not dt:
        return 0
    return dt.hour * 60 + dt.minute


def _hhmm(value) -> str:
    dt = _parse_ts(value)
    return dt.strftime("%H:%M") if dt else ""


def _elapsed_minutes(value) -> int:
    dt = _parse_ts(value)
    if not dt:
        return 0
    return max(0, int((datetime.now() - dt).total_seconds() // 60))


def _get(row, key):
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _name_parts(row) -> tuple:
    """(prénom, nom) d'une entrée, qu'elle vienne d'une fiche patient ou d'une
    saisie libre (patient sans RDV et sans dossier)."""
    first = _get(row, "first_name") or ""
    last = _get(row, "last_name") or ""
    if not first and not last:
        raw = (_get(row, "display_name") or "").strip()
        bits = raw.split()
        if len(bits) >= 2:
            first, last = bits[0], " ".join(bits[1:])
        else:
            first, last = raw, ""
    return first.strip(), last.strip()


def full_name(row) -> str:
    """Nom complet : interface praticien uniquement, jamais l'écran public."""
    first, last = _name_parts(row)
    label = ("%s %s" % (first, last.upper())).strip()
    return label or "Patient"


def format_display_name(row, mode: str) -> str:
    """Libellé affiché sur l'écran de la salle d'attente."""
    ticket = ticket_label(_get(row, "ticket_no"))
    if mode == "ticket":
        return ticket or "--"
    first, last = _name_parts(row)
    if mode == "full":
        return ("%s %s" % (first, last.upper())).strip() or ticket or "Patient"
    # 'initial' (défaut) : prénom + initiale du nom — reconnaissable par le
    # patient concerné, illisible pour le reste de la salle.
    if first and last:
        return "%s %s." % (first, last[0].upper())
    return first or ticket or "Patient"


# ----------------------------------------------------------------- réglages

async def get_settings(db: aiosqlite.Connection, doctor_id: int) -> dict:
    """Lit les réglages du médecin, en créant la ligne (et le jeton d'écran) au
    premier appel."""
    cur = await db.execute("SELECT * FROM waiting_room_settings WHERE doctor_id = ?", (doctor_id,))
    row = await cur.fetchone()
    if not row:
        await db.execute(
            """INSERT INTO waiting_room_settings (doctor_id, display_token, ticker_messages, updated_at)
               VALUES (?, ?, ?, ?)""",
            (doctor_id, secrets.token_urlsafe(24), json.dumps(DEFAULT_TICKER, ensure_ascii=False), now_ts()),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM waiting_room_settings WHERE doctor_id = ?", (doctor_id,))
        row = await cur.fetchone()
    s = dict(row)
    if not s.get("display_token"):
        token = secrets.token_urlsafe(24)
        await db.execute(
            "UPDATE waiting_room_settings SET display_token = ? WHERE doctor_id = ?", (token, doctor_id)
        )
        await db.commit()
        s["display_token"] = token
    if s.get("name_mode") not in NAME_MODES:
        s["name_mode"] = "initial"
    try:
        messages = json.loads(s.get("ticker_messages") or "[]")
        s["ticker"] = [str(m) for m in messages if str(m).strip()]
    except Exception:
        s["ticker"] = []
    if not s["ticker"]:
        s["ticker"] = list(DEFAULT_TICKER)
    for flag in ("show_times", "sound_enabled", "auto_checkin_on_confirm"):
        s[flag] = 1 if (s.get(flag) is None or s.get(flag)) else 0
    try:
        s["call_banner_seconds"] = max(5, min(120, int(s.get("call_banner_seconds") or 20)))
    except (TypeError, ValueError):
        s["call_banner_seconds"] = 20
    return s


async def save_settings(db: aiosqlite.Connection, doctor_id: int, data: dict) -> dict:
    await get_settings(db, doctor_id)  # garantit l'existence de la ligne
    name_mode = data.get("name_mode")
    if name_mode not in NAME_MODES:
        name_mode = "initial"
    ticker = [str(m).strip() for m in (data.get("ticker") or []) if str(m).strip()][:8]
    try:
        banner = max(5, min(120, int(data.get("call_banner_seconds") or 20)))
    except (TypeError, ValueError):
        banner = 20
    await db.execute(
        """UPDATE waiting_room_settings
           SET name_mode = ?, show_times = ?, sound_enabled = ?, auto_checkin_on_confirm = ?,
               call_banner_seconds = ?, clinic_name = ?, ticker_messages = ?, updated_at = ?
           WHERE doctor_id = ?""",
        (
            name_mode,
            1 if data.get("show_times") else 0,
            1 if data.get("sound_enabled") else 0,
            1 if data.get("auto_checkin_on_confirm") else 0,
            banner,
            (data.get("clinic_name") or "").strip()[:120] or None,
            json.dumps(ticker, ensure_ascii=False),
            now_ts(),
            doctor_id,
        ),
    )
    await db.commit()
    return await get_settings(db, doctor_id)


async def regenerate_token(db: aiosqlite.Connection, doctor_id: int) -> str:
    await get_settings(db, doctor_id)
    token = secrets.token_urlsafe(24)
    await db.execute(
        "UPDATE waiting_room_settings SET display_token = ?, updated_at = ? WHERE doctor_id = ?",
        (token, now_ts(), doctor_id),
    )
    await db.commit()
    return token


# --------------------------------------------------------------------- file

async def _next_ticket(db: aiosqlite.Connection, doctor_id: int, day: str) -> int:
    cur = await db.execute(
        "SELECT COALESCE(MAX(ticket_no), 0) + 1 FROM waiting_room WHERE doctor_id = ? AND day = ?",
        (doctor_id, day),
    )
    return (await cur.fetchone())[0]


async def find_entry_by_appointment(db: aiosqlite.Connection, appointment_id: int):
    cur = await db.execute("SELECT * FROM waiting_room WHERE appointment_id = ?", (appointment_id,))
    return await cur.fetchone()


async def check_in(
    db: aiosqlite.Connection,
    doctor_id: int,
    *,
    appointment_id: Optional[int] = None,
    patient_id: Optional[int] = None,
    name: Optional[str] = None,
    reason: Optional[str] = None,
    room: Optional[str] = None,
    priority: int = 0,
    created_by: Optional[int] = None,
    day: Optional[str] = None,
) -> tuple:
    """Pointe l'arrivée d'un patient. Idempotent sur `appointment_id`.

    Renvoie (entry_id, created). Un patient marqué `absent`/`parti` qui se
    représente est remis dans la file plutôt que dupliqué.
    """
    day = day or today_str()
    now = now_ts()

    if appointment_id:
        existing = await find_entry_by_appointment(db, appointment_id)
        if existing:
            if existing["status"] in ("absent", "parti"):
                await db.execute(
                    """UPDATE waiting_room SET status = 'attente', arrived_at = ?, called_at = NULL,
                       started_at = NULL, ended_at = NULL, updated_at = ? WHERE id = ?""",
                    (now, now, existing["id"]),
                )
                await db.commit()
            return existing["id"], False

    apt_time = None
    if appointment_id:
        cur = await db.execute(
            "SELECT patient_id, start_datetime, title, room FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        apt = await cur.fetchone()
        if apt:
            patient_id = patient_id or apt["patient_id"]
            apt_time = apt["start_datetime"]
            reason = reason or apt["title"]
            room = room or apt["room"]

    # Un patient déjà présent et non terminé n'est pas ajouté deux fois.
    if patient_id:
        cur = await db.execute(
            """SELECT id FROM waiting_room
               WHERE doctor_id = ? AND day = ? AND patient_id = ?
                 AND status IN ('attente', 'appele', 'en_cours')
               LIMIT 1""",
            (doctor_id, day, patient_id),
        )
        dup = await cur.fetchone()
        if dup:
            return dup["id"], False

    sort_order = _minutes_of_day(apt_time) if apt_time else _minutes_of_day(now)
    ticket_no = await _next_ticket(db, doctor_id, day)

    cur = await db.execute(
        """INSERT INTO waiting_room
           (doctor_id, patient_id, appointment_id, display_name, ticket_no, status, priority,
            sort_order, room, reason, day, arrived_at, created_by, updated_at)
           VALUES (?, ?, ?, ?, ?, 'attente', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            doctor_id,
            patient_id,
            appointment_id,
            (name or "").strip()[:120] or None,
            ticket_no,
            1 if priority else 0,
            sort_order,
            (room or "").strip()[:60] or None,
            (reason or "").strip()[:200] or None,
            day,
            now,
            created_by,
            now,
        ),
    )
    await db.commit()
    return cur.lastrowid, True


async def set_status(db: aiosqlite.Connection, entry_id: int, status: str, room: Optional[str] = None):
    """Change le statut d'une entrée et horodate la transition."""
    if status not in QUEUE_STATUSES:
        return None
    now = now_ts()
    sets = ["status = ?", "updated_at = ?"]
    params = [status, now]

    if status == "appele":
        # Rappeler un patient rafraîchit `called_at` : l'écran redéclenche le
        # bandeau et le carillon.
        sets.append("called_at = ?")
        params.append(now)
    elif status == "en_cours":
        sets.append("started_at = ?")
        params.append(now)
        sets.append("called_at = COALESCE(called_at, ?)")
        params.append(now)
    elif status in ("termine", "absent", "parti"):
        sets.append("ended_at = ?")
        params.append(now)

    if room is not None:
        sets.append("room = ?")
        params.append((room or "").strip()[:60] or None)

    params.append(entry_id)
    await db.execute("UPDATE waiting_room SET %s WHERE id = ?" % ", ".join(sets), params)
    await db.commit()
    cur = await db.execute("SELECT * FROM waiting_room WHERE id = ?", (entry_id,))
    return await cur.fetchone()


async def sync_from_appointment(db: aiosqlite.Connection, appointment_id: int, new_status: str) -> None:
    """Répercute un changement de statut de RDV sur la file d'attente.

    Ne lève jamais : la salle d'attente ne doit pas casser l'agenda.
    """
    try:
        cur = await db.execute(
            "SELECT id, doctor_id, patient_id, start_datetime FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        apt = await cur.fetchone()
        if not apt:
            return
        entry = await find_entry_by_appointment(db, appointment_id)
        is_today = str(apt["start_datetime"] or "")[:10] == today_str()

        if new_status == "confirme":
            # Un RDV confirmé trois jours à l'avance ne doit pas remplir la salle :
            # le pointage automatique ne vaut que pour les RDV du jour.
            if is_today and not entry:
                settings = await get_settings(db, apt["doctor_id"])
                if settings.get("auto_checkin_on_confirm"):
                    await check_in(db, apt["doctor_id"], appointment_id=appointment_id)
        elif new_status == "en_cours":
            if not entry and is_today:
                entry_id, _ = await check_in(db, apt["doctor_id"], appointment_id=appointment_id)
                await set_status(db, entry_id, "en_cours")
            elif entry and entry["status"] != "en_cours":
                await set_status(db, entry["id"], "en_cours")
        elif new_status == "termine":
            if entry and entry["status"] != "termine":
                await set_status(db, entry["id"], "termine")
        elif new_status == "absent":
            if entry:
                await set_status(db, entry["id"], "absent")
        elif new_status == "annule":
            if entry:
                await db.execute("DELETE FROM waiting_room WHERE id = ?", (entry["id"],))
                await db.commit()
        elif new_status == "planifie":
            # Retour en arrière : on retire le patient de la file s'il n'a pas
            # encore été appelé.
            if entry and entry["status"] == "attente":
                await db.execute("DELETE FROM waiting_room WHERE id = ?", (entry["id"],))
                await db.commit()
    except Exception:
        pass


async def sync_consultation_started(db, doctor_id: int, patient_id: int, appointment_id=None) -> None:
    """Appelée au démarrage d'une consultation : le patient passe en `en_cours`."""
    try:
        day = today_str()
        entry = await find_entry_by_appointment(db, appointment_id) if appointment_id else None
        if not entry and patient_id:
            cur = await db.execute(
                """SELECT * FROM waiting_room
                   WHERE doctor_id = ? AND day = ? AND patient_id = ?
                     AND status IN ('attente', 'appele')
                   ORDER BY id DESC LIMIT 1""",
                (doctor_id, day, patient_id),
            )
            entry = await cur.fetchone()
        if entry:
            if entry["status"] != "en_cours":
                await set_status(db, entry["id"], "en_cours")
        elif appointment_id:
            entry_id, _ = await check_in(db, doctor_id, appointment_id=appointment_id, patient_id=patient_id)
            await set_status(db, entry_id, "en_cours")
    except Exception:
        pass


async def sync_consultation_ended(db, doctor_id: int, patient_id: int, appointment_id=None) -> None:
    """Appelée à la clôture d'une consultation : le patient sort de la file."""
    try:
        day = today_str()
        entry = await find_entry_by_appointment(db, appointment_id) if appointment_id else None
        if not entry and patient_id:
            cur = await db.execute(
                """SELECT * FROM waiting_room
                   WHERE doctor_id = ? AND day = ? AND patient_id = ?
                     AND status IN ('attente', 'appele', 'en_cours')
                   ORDER BY id DESC LIMIT 1""",
                (doctor_id, day, patient_id),
            )
            entry = await cur.fetchone()
        if entry and entry["status"] != "termine":
            await set_status(db, entry["id"], "termine")
    except Exception:
        pass


async def _waiting_rows(db, doctor_id: int, day: str):
    cur = await db.execute(
        """SELECT id, sort_order, appointment_id, arrived_at FROM waiting_room
           WHERE doctor_id = ? AND day = ? AND status = 'attente'
           ORDER BY sort_order ASC, arrived_at ASC, id ASC""",
        (doctor_id, day),
    )
    return await cur.fetchall()


async def move(db, doctor_id: int, entry_id: int, direction: str, day: Optional[str] = None) -> bool:
    """Remonte ou descend une entrée d'un cran dans la file.

    On réutilise les valeurs de `sort_order` déjà présentes (redistribuées dans
    le nouvel ordre) plutôt qu'une renumérotation 1..N : l'échelle « minutes
    depuis minuit » est préservée, donc une arrivée ultérieure continue de se
    placer correctement.
    """
    day = day or today_str()
    rows = await _waiting_rows(db, doctor_id, day)
    ids = [r["id"] for r in rows]
    if entry_id not in ids:
        return False
    i = ids.index(entry_id)
    j = i - 1 if direction == "up" else i + 1
    if j < 0 or j >= len(ids):
        return False
    ids[i], ids[j] = ids[j], ids[i]

    values = sorted(int(r["sort_order"] or 0) for r in rows)
    for k in range(1, len(values)):          # valeurs strictement croissantes
        if values[k] <= values[k - 1]:
            values[k] = values[k - 1] + 1

    now = now_ts()
    for value, eid in zip(values, ids):
        await db.execute(
            "UPDATE waiting_room SET sort_order = ?, updated_at = ? WHERE id = ?", (value, now, eid)
        )
    await db.commit()
    return True


async def set_priority(db, doctor_id: int, entry_id: int, priority: int, day: Optional[str] = None) -> bool:
    """Bascule le marqueur d'urgence. Activé, il place l'entrée en tête de file ;
    désactivé, il la remet à sa place naturelle (heure de RDV ou d'arrivée)."""
    day = day or today_str()
    cur = await db.execute("SELECT * FROM waiting_room WHERE id = ? AND doctor_id = ?", (entry_id, doctor_id))
    entry = await cur.fetchone()
    if not entry:
        return False

    if priority:
        cur = await db.execute(
            "SELECT MIN(sort_order) FROM waiting_room WHERE doctor_id = ? AND day = ? AND status = 'attente'",
            (doctor_id, day),
        )
        lowest = (await cur.fetchone())[0]
        sort_order = (lowest if lowest is not None else _minutes_of_day(now_ts())) - 1
    else:
        apt_time = None
        if entry["appointment_id"]:
            cur = await db.execute(
                "SELECT start_datetime FROM appointments WHERE id = ?", (entry["appointment_id"],)
            )
            apt = await cur.fetchone()
            apt_time = apt["start_datetime"] if apt else None
        sort_order = _minutes_of_day(apt_time or entry["arrived_at"])

    await db.execute(
        "UPDATE waiting_room SET priority = ?, sort_order = ?, updated_at = ? WHERE id = ?",
        (1 if priority else 0, sort_order, now_ts(), entry_id),
    )
    await db.commit()
    return True


# --------------------------------------------------------------------- vues

_ENTRY_SQL = """
    SELECT w.*, p.first_name, p.last_name,
           a.start_datetime AS apt_start, a.title AS apt_title, a.appointment_type AS apt_type
    FROM waiting_room w
    LEFT JOIN patients p ON w.patient_id = p.id
    LEFT JOIN appointments a ON w.appointment_id = a.id
    WHERE w.doctor_id = ? AND w.day = ?
    ORDER BY w.sort_order ASC, w.arrived_at ASC, w.id ASC
"""


def _entry_dict(row) -> dict:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "appointment_id": row["appointment_id"],
        "name": full_name(row),
        "ticket": ticket_label(row["ticket_no"]),
        "status": row["status"],
        "priority": int(row["priority"] or 0),
        "room": row["room"] or "",
        "reason": row["reason"] or row["apt_title"] or "",
        "apt_time": _hhmm(row["apt_start"]),
        "arrived_at": _hhmm(row["arrived_at"]),
        "called_at": _hhmm(row["called_at"]),
        "started_at": _hhmm(row["started_at"]),
        "ended_at": _hhmm(row["ended_at"]),
        "waited_minutes": _elapsed_minutes(row["arrived_at"]) if row["status"] in ("attente", "appele") else None,
        "busy_minutes": _elapsed_minutes(row["started_at"]) if row["status"] == "en_cours" else None,
    }


def _signature(rows, extra: int = 0) -> str:
    """Empreinte de l'état courant : le front ne reconstruit le DOM que si elle
    change (évite le clignotement à chaque interrogation)."""
    parts = [
        "%s:%s:%s:%s:%s:%s"
        % (r["id"], r["status"], r["priority"], r["sort_order"], r["room"] or "", r["called_at"] or "")
        for r in rows
    ]
    return "%d|%d|%s" % (extra, len(parts), "#".join(parts))


async def board(db: aiosqlite.Connection, doctor_id: int, day: Optional[str] = None) -> dict:
    """Les colonnes de l'interface praticien."""
    day = day or today_str()

    cur = await db.execute(_ENTRY_SQL, (doctor_id, day))
    rows = await cur.fetchall()

    waiting, active, done = [], [], []
    for row in rows:
        item = _entry_dict(row)
        if row["status"] == "attente":
            waiting.append(item)
        elif row["status"] in ("appele", "en_cours"):
            active.append(item)
        else:
            done.append(item)

    # Colonne 1 : les RDV du jour pas encore pointés.
    cur = await db.execute(
        """SELECT a.id, a.start_datetime, a.title, a.status, a.room, a.appointment_type,
                  p.id AS patient_id, p.first_name, p.last_name
           FROM appointments a
           JOIN patients p ON a.patient_id = p.id
           WHERE a.doctor_id = ? AND date(a.start_datetime) = ?
             AND a.status NOT IN ('annule', 'absent')
             AND NOT EXISTS (SELECT 1 FROM waiting_room w WHERE w.appointment_id = a.id)
           ORDER BY a.start_datetime""",
        (doctor_id, day),
    )
    expected = []
    for row in await cur.fetchall():
        expected.append({
            "appointment_id": row["id"],
            "patient_id": row["patient_id"],
            "name": ("%s %s" % (row["first_name"] or "", (row["last_name"] or "").upper())).strip(),
            "apt_time": _hhmm(row["start_datetime"]),
            "reason": row["title"] or "",
            "status": row["status"],
            "room": row["room"] or "",
            "type": row["appointment_type"] or "",
        })

    return {
        "day": day,
        "expected": expected,
        "waiting": waiting,
        "active": active,
        "done": done,
        "counts": {
            "expected": len(expected),
            "waiting": len(waiting),
            "active": len(active),
            "done": len(done),
        },
        "signature": _signature(rows, len(expected)),
    }


async def waiting_count(db: aiosqlite.Connection, doctor_id: int) -> int:
    cur = await db.execute(
        "SELECT COUNT(*) FROM waiting_room WHERE doctor_id = ? AND day = ? AND status = 'attente'",
        (doctor_id, today_str()),
    )
    return (await cur.fetchone())[0]


async def settings_by_token(db: aiosqlite.Connection, token: str):
    """Résout un jeton d'écran vers les réglages du médecin (None si inconnu)."""
    if not token:
        return None
    cur = await db.execute("SELECT doctor_id FROM waiting_room_settings WHERE display_token = ?", (token,))
    row = await cur.fetchone()
    if not row:
        return None
    return await get_settings(db, row["doctor_id"])


async def public_board(db: aiosqlite.Connection, settings: dict, limit: int = 6) -> dict:
    """Vue anonymisée destinée à l'écran de la salle d'attente.

    Ne contient ni nom complet (sauf si le cabinet l'a explicitement choisi via
    `name_mode`), ni identifiant patient, ni motif, ni téléphone.
    """
    day = today_str()
    mode = settings.get("name_mode") or "initial"
    show_times = bool(settings.get("show_times"))

    cur = await db.execute(_ENTRY_SQL, (settings["doctor_id"], day))
    rows = await cur.fetchall()

    current, upcoming, last_call, last_call_at = [], [], None, ""
    for row in rows:
        if row["status"] in ("appele", "en_cours"):
            current.append({
                "label": format_display_name(row, mode),
                "room": row["room"] or "",
                "status": row["status"],
            })
        elif row["status"] == "attente":
            upcoming.append({
                "position": len(upcoming) + 1,
                "label": format_display_name(row, mode),
                "time": _hhmm(row["apt_start"]) if show_times else "",
                "urgent": bool(row["priority"]),
            })
        called_at = str(row["called_at"] or "")
        if called_at and called_at > last_call_at:
            last_call_at = called_at
            last_call = {
                # Clé opaque : l'écran compare, il n'a pas besoin de l'horodatage.
                "key": "%s:%s" % (row["id"], called_at),
                "label": format_display_name(row, mode),
                "room": row["room"] or "",
            }

    return {
        "clinic_name": settings.get("clinic_name") or "",
        "sound_enabled": bool(settings.get("sound_enabled")),
        "call_banner_seconds": settings.get("call_banner_seconds") or 20,
        "ticker": settings.get("ticker") or [],
        "current": current,
        "next": upcoming[:limit],
        "more": max(0, len(upcoming) - limit),
        "waiting_total": len(upcoming),
        "last_call": last_call,
        "signature": _signature(rows),
    }
