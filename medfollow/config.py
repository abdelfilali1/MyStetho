import os
import secrets
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _resolve_database_path() -> str:
    explicit_path = os.getenv("MEDFOLLOW_DATABASE_PATH")
    if explicit_path:
        return explicit_path

    local_path = os.path.join(BASE_DIR, "data", "medfollow.db")
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        return local_path
    except OSError:
        temp_dir = tempfile.gettempdir()
        return os.path.join(temp_dir, "medfollow.db")

# Database
DATABASE_PATH = _resolve_database_path()

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
        # Fallback for read-only filesystems (e.g. Railway ephemeral FS).
        print(
            "\n⚠️  WARNING: MEDFOLLOW_SECRET_KEY is not set and the secret key file "
            "could not be written. A new random key will be generated on every restart, "
            "invalidating all user sessions. Set MEDFOLLOW_SECRET_KEY as an environment "
            "variable in your deployment platform (Railway → Variables).\n"
        )
        return secrets.token_hex(32)

SECRET_KEY = _load_or_create_secret_key()
if not os.environ.get("MEDFOLLOW_SECRET_KEY"):
    import os as _os
    if not _os.path.exists(_SECRET_KEY_FILE):
        print(
            "\n⚠️  WARNING: MEDFOLLOW_SECRET_KEY env variable not set. "
            "Set it in Railway → Variables to persist sessions across deploys.\n"
        )
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8

# Compte administrateur principal : seul cet email peut créer le premier compte
# (/setup) ou recevoir le rôle admin. Surchargez via MEDFOLLOW_ADMIN_EMAIL.
ADMIN_EMAIL = os.getenv("MEDFOLLOW_ADMIN_EMAIL", "abdelfilaliansary@gmail.com")

# When the app is served over HTTPS (TLS terminated at the reverse proxy), set
# MEDFOLLOW_HTTPS=1 so auth cookies are flagged Secure and HSTS is emitted.
# Defaults OFF so local HTTP dev — and an HTTP-only deployment — keep working
# (a Secure cookie is never sent over plain HTTP, which would break login).
HTTPS_ENABLED = os.getenv("MEDFOLLOW_HTTPS", "0").lower() in ("1", "true", "yes")

# Uploads
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
MAX_UPLOAD_SIZE_MB = 50

# --- Radio IA : détection de pathologies sur radiographie (DentalXrayAI) ------
# Modèle YOLOv8 entraîné sur DENTEX (SubGlitch1/DentalXrayAI) : détecte carie,
# carie profonde, dent incluse, lésion périapicale. L'inférence tourne DANS LE
# NAVIGATEUR via onnxruntime-web (comme la Céphalométrie) : le serveur ne fait que
# servir le fichier modèle statique. La VM de production n'a pas assez de RAM pour
# PyTorch — le serveur n'a donc AUCUNE dépendance lourde (torch/Ultralytics).
#
# Le fichier ONNX servi au navigateur (généré en local par scripts/export_onnx.py).
RADIO_AI_ONNX = os.path.join(BASE_DIR, "static", "js", "radio", "model", "dentalxray.onnx")
# Poids PyTorch d'origine — nécessaires UNIQUEMENT en local pour (re)générer le
# fichier ONNX (export Ultralytics) ; jamais chargés par le serveur.
RADIO_AI_WEIGHTS = os.getenv(
    "MEDFOLLOW_RADIO_AI_WEIGHTS",
    os.path.join(BASE_DIR, "models", "dentalxray", "best.pt"),
)
# URL de téléchargement des poids (utilisée par scripts/download_dentalxray.py).
# Le serveur d'origine de DentalXrayAI (xray.cyphersec.eu) est hors ligne ; on
# récupère donc best.pt (YOLOv8n DENTEX, ~6 Mo) versionné dans la fork NoahOksuz.
RADIO_AI_MODEL_URL = os.getenv(
    "MEDFOLLOW_RADIO_AI_MODEL_URL",
    "https://raw.githubusercontent.com/NoahOksuz/DentalXrayAI/main/best.pt",
)

# --- WhatsApp (Meta Cloud API) : confirmations / rappels de rendez-vous ------
# Tant que WHATSAPP_ENABLED est faux OU que le token/phone-id manquent, le
# service tourne en « dry-run » : il journalise mais n'appelle jamais l'API.
# L'app fonctionne donc en local et sur la VM AVANT d'avoir les identifiants,
# sans jamais casser la création de rendez-vous.
WHATSAPP_ENABLED = os.getenv("MEDFOLLOW_WHATSAPP_ENABLED", "0").lower() in ("1", "true", "yes")
WHATSAPP_TOKEN = os.getenv("MEDFOLLOW_WHATSAPP_TOKEN", "")                 # token d'accès (temporaire 24h ou permanent)
WHATSAPP_PHONE_NUMBER_ID = os.getenv("MEDFOLLOW_WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("MEDFOLLOW_WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_DEFAULT_CC = os.getenv("MEDFOLLOW_WHATSAPP_DEFAULT_CC", "212")    # indicatif par défaut (Maroc)
WHATSAPP_TEMPLATE_LANG = os.getenv("MEDFOLLOW_WHATSAPP_TEMPLATE_LANG", "fr")
WHATSAPP_TPL_CONFIRMATION = os.getenv("MEDFOLLOW_WHATSAPP_TPL_CONFIRMATION", "rdv_confirmation")
WHATSAPP_TPL_RAPPEL = os.getenv("MEDFOLLOW_WHATSAPP_TPL_RAPPEL", "rdv_rappel_24h")
WHATSAPP_TPL_RAPPEL_SOIN = os.getenv("MEDFOLLOW_WHATSAPP_TPL_RAPPEL_SOIN", "rappel_soin")
# En-tête IMAGE : les 3 modèles Doctivo (rdv_confirmation, rdv_rappel_24h,
# rappel_soin) ont un header de type IMAGE, OBLIGATOIRE à chaque envoi. On fournit
# une URL HTTPS publique que les serveurs de Meta téléchargent. Mettre à vide (« »)
# pour un template SANS header image (sinon Meta rejette l'envoi).
WHATSAPP_HEADER_IMAGE_URL = os.getenv(
    "MEDFOLLOW_WHATSAPP_HEADER_IMAGE_URL",
    "https://www.doctivo.org/static/img/logo4.png",
)
# Mode test : ignore les modèles réels et envoie « hello_world » (pré-approuvé
# par Meta, sans variable) pour valider tout le tuyau AVANT l'approbation des
# modèles Doctivo. À remettre à 0 dès que les vrais modèles sont approuvés.
WHATSAPP_TEST_MODE = os.getenv("MEDFOLLOW_WHATSAPP_TEST_MODE", "0").lower() in ("1", "true", "yes")
# Intervalle du planificateur de rappels 24h (secondes). 600 = 10 min.
REMINDER_POLL_SECONDS = int(os.getenv("MEDFOLLOW_REMINDER_POLL_SECONDS", "600"))
# Lot 2 (webhook entrant, nécessite un HTTPS public) — déclarés dès maintenant.
WHATSAPP_VERIFY_TOKEN = os.getenv("MEDFOLLOW_WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.getenv("MEDFOLLOW_WHATSAPP_APP_SECRET", "")


def whatsapp_configured() -> bool:
    """Vrai si l'envoi réel est possible (sinon : mode dry-run/journal seul)."""
    return bool(WHATSAPP_ENABLED and WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID)
