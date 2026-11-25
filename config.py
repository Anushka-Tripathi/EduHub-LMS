"""Central configuration. Everything comes from environment variables (or a .env file)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env(path=None):
    """Tiny .env loader (KEY=value lines). Real environment variables always win."""
    path = Path(path or BASE_DIR / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    ENV = os.getenv("APP_ENV", "development")            # development | production
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
    LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
    SESSION_HOURS = int(os.getenv("SESSION_HOURS", "8"))
    COOKIE_SECURE = _bool("COOKIE_SECURE", False)         # True when served over HTTPS
    BEHIND_PROXY = _bool("BEHIND_PROXY", False)           # nginx / load balancer in front
    # login throttling
    LOGIN_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "5"))
    LOGIN_WINDOW_MIN = int(os.getenv("LOGIN_WINDOW_MIN", "15"))
    # QR attendance
    QR_STEP_SECONDS = int(os.getenv("QR_STEP_SECONDS", "30"))
    QR_ALLOWED_NETWORKS = [n.strip() for n in os.getenv("QR_ALLOWED_NETWORKS", "").split(",") if n.strip()]
    ATTENDANCE_THRESHOLD = int(os.getenv("ATTENDANCE_THRESHOLD", "75"))
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")   # what phones should open, e.g. http://192.168.1.20:5000


def check_production_settings():
    if Config.ENV == "production" and Config.SECRET_KEY == "dev-only-change-me":
        raise RuntimeError("Set a real SECRET_KEY before running with APP_ENV=production.")
