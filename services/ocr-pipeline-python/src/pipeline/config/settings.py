import os
from pathlib import Path

from dotenv import load_dotenv


# Locate the project root dynamically so it works both inside Docker (/app)
# and during local development (repo root with docker-compose.yml).
def _detect_project_root() -> Path:
    current = Path(__file__).resolve()

    # Prefer the first parent that contains docker-compose (repo root when running locally)
    for parent in current.parents:
        if (parent / "docker-compose.yml").exists():
            return parent

    # Fallback: pick the first directory that looks like the service root (src + requirements)
    for parent in current.parents:
        if (parent / "src").exists() and (parent / "requirements.txt").exists():
            return parent

    # Absolute fallback to avoid IndexError if structure changes again
    return current.parents[3]


PROJECT_ROOT = _detect_project_root()
ENV_PATH = PROJECT_ROOT / "configs" / "env" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:  # pragma: no cover - fallback for tests
    load_dotenv()

DATA_ROOT = PROJECT_ROOT / "data"
CACHE_DIR = DATA_ROOT / "cache"


def _resolve_path(value: str | Path) -> Path:
    if isinstance(value, Path):
        path = value
    else:
        path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path

    # Directories used across ingestion, caching, and persistence.


UPLOAD_DIR = _resolve_path(os.getenv("UPLOAD_DIR", DATA_ROOT / "uploads"))
PROCESSED_DIR = _resolve_path(os.getenv("PROCESSED_DIR", DATA_ROOT / "processed"))
DB_STORAGE_DIR = _resolve_path(os.getenv("DB_DIR", DATA_ROOT))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

db_path_env = os.getenv("DB_PATH")
DEFAULT_DB_PATH = (
    _resolve_path(db_path_env) if db_path_env else DB_STORAGE_DIR / "app.db"
)
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


PIPELINE_LLM_MODEL = os.getenv(
    "PIPELINE_LLM_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
)
PIPELINE_LLM_API_BASE = os.getenv(
    "PIPELINE_LLM_API_BASE",
    os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1"),
)
PIPELINE_LLM_API_KEY = os.getenv(
    "PIPELINE_LLM_API_KEY", os.getenv("GROQ_API_KEY", "")
)
PIPELINE_LLM_ALLOW_STUB = _get_bool_env(
    "PIPELINE_LLM_ALLOW_STUB",
    _get_bool_env("GROQ_ALLOW_STUB", True),
)

# Rate Limiter Settings (conservative defaults for free tier)
# llama-3.3-70b-versatile limits: RPM=30, RPD=14500, TPM=6K, TPD=500K
# Conservative settings to account for concurrent requests and safety margin
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "24"))     # 24/30 (80% for safety)
RATE_LIMIT_RPD = int(os.getenv("RATE_LIMIT_RPD", "11500"))  # 11500/14500 (79%)
RATE_LIMIT_TPM = int(os.getenv("RATE_LIMIT_TPM", "4800"))   # 4800/6000 (80%)
RATE_LIMIT_TPD = int(os.getenv("RATE_LIMIT_TPD", "400000")) # 400K/500K (80%)

# Database
db_url_env = os.getenv("DB_URL")
if db_url_env and db_url_env.startswith("sqlite:///"):
    # Support both sqlite:///relative and sqlite:////absolute
    raw_path = db_url_env.split("sqlite:///", 1)[1]
    resolved = _resolve_path(raw_path)
    DB_URL = f"sqlite:///{resolved.as_posix()}"
elif db_url_env:
    DB_URL = db_url_env
else:
    DB_URL = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

# Defaults
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "UNK")
PDF_OCR_DPI = int(os.getenv("PDF_OCR_DPI", "300"))
PDF_OCR_MAX_PAGES = int(os.getenv("PDF_OCR_MAX_PAGES", "5"))
TEXT_MIN_LENGTH = int(os.getenv("TEXT_MIN_LENGTH", "120"))

# Samples path (optional helper for CLI/tests)
SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", DATA_ROOT / "samples"))
