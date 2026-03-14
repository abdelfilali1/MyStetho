import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Database
DATABASE_PATH = os.getenv(
    "MEDFOLLOW_DATABASE_PATH",
    os.path.join(BASE_DIR, "data", "medfollow.db"),
)

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Security — key is persisted so restarts/reloads don't invalidate sessions
_SECRET_KEY_FILE = os.path.join(BASE_DIR, "data", ".secret_key")

def _load_or_create_secret_key() -> str:
    if os.environ.get("MEDFOLLOW_SECRET_KEY"):
        return os.environ["MEDFOLLOW_SECRET_KEY"]
    try:
        os.makedirs(os.path.dirname(_SECRET_KEY_FILE), exist_ok=True)
        if os.path.exists(_SECRET_KEY_FILE):
            key = open(_SECRET_KEY_FILE).read().strip()
            if key:
                return key
        key = secrets.token_hex(32)
        open(_SECRET_KEY_FILE, "w").write(key)
        return key
    except OSError:
        # Fallback for read-only filesystems in some deployment environments.
        return secrets.token_hex(32)

SECRET_KEY = _load_or_create_secret_key()
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8

# Uploads
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
MAX_UPLOAD_SIZE_MB = 50
