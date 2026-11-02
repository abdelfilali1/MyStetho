"""Theme visuel de l'application, choisi par l'administrateur (page Admin > Layout).

La valeur vit dans la table app_settings (cle 'ui_theme') et reste en cache
memoire : base.html l'interroge a chaque rendu, sans requete supplementaire.
"""
import sqlite3

from config import DATABASE_PATH

THEMES = {
    "original": "Original",
    "premium": "Premium clinique",
    "vibrant": "Vivant",
}
DEFAULT_THEME = "premium"
_KEY = "ui_theme"

_current: str | None = None


def get_theme() -> str:
    """Theme actif (charge depuis la base au premier appel)."""
    global _current
    if _current is None:
        try:
            with sqlite3.connect(DATABASE_PATH) as conn:
                row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (_KEY,)).fetchone()
            _current = row[0] if row and row[0] in THEMES else DEFAULT_THEME
        except sqlite3.Error:
            return DEFAULT_THEME
    return _current


async def set_theme(db, theme: str) -> None:
    global _current
    if theme not in THEMES:
        raise ValueError(f"Theme inconnu : {theme}")
    await db.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_KEY, theme),
    )
    await db.commit()
    _current = theme
