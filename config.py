"""config.py — Verity v2 configuration."""
import os
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Render (and most hosts) always set these. Used to tell "running on a server"
# from "running on someone's laptop".
IS_HOSTED = bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID")
                 or os.environ.get("DYNO") or os.environ.get("KUBERNETES_SERVICE_HOST"))

# Set when the app is hosted but has no database configured. The app still starts
# (so the page can explain itself) but every route shows the setup notice.
CONFIG_ERROR = None


def _db_url():
    global CONFIG_ERROR
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if IS_HOSTED:
            # Falling back to SQLite on a hosted disk is the trap: it works until
            # the next deploy wipes it, and accounts silently disappear. Refuse.
            CONFIG_ERROR = (
                "DATABASE_URL is not set. This app is running on a server, where "
                "local file storage is erased on every deploy or restart — any data "
                "and user accounts would be lost without warning. Set DATABASE_URL "
                "to your Neon Postgres connection string in the service's Environment "
                "settings, then redeploy."
            )
        return f"sqlite:///{BASE_DIR / 'verity.db'}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _db_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(os.environ.get("UPLOAD_FOLDER", BASE_DIR / "uploads"))
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024
    SEED_DEMO = os.environ.get("SEED_DEMO", "0") == "1"

DEFAULT_SETTINGS = {
    "amount_tolerance": 0.01,
    "date_window_days": 5,
    "fuzzy_ref_min": 88,
    "desc_sim_min": 80,
    "max_split_group": 4,
    "approval_thresholds": [10000, 50000, 100000, 500000],
    "threshold_band": 0.05,
    "duplicate_window": 7,
    "round_modulo": 1000,
    "recurrence_min_months": 3,
    "recurrence_min_count": 3,
    "request_due_days": 7,
    "watchlist_ids": [],
    "watchlist_names": [],
}

STARTER_ACCOUNTS = [
    ("CIB",   "Commercial International Bank", "bank",   ""),
    ("NBE",   "National Bank of Egypt",        "bank",   ""),
    ("VODA",  "Vodafone Cash",                 "wallet", ""),
    ("INSTA", "InstaPay",                      "wallet", ""),
    ("GL",    "Al Amin ledger",                "ledger", ""),
]
