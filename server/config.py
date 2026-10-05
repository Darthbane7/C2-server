import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Database
DB_PATH = os.getenv("C2_DB_PATH", str(DATA_DIR / "c2_system.db"))

# Server settings
SERVER_HOST = os.getenv("C2_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("C2_SERVER_PORT", "8000"))

# Security
# Set C2_SECRET_KEY to require 'X-C2-Key' header on all requests
SECRET_KEY = os.getenv("C2_SECRET_KEY", "c2-secret-demo-key-2026")

# Agent settings
AGENT_OFFLINE_THRESHOLD_SECONDS = int(os.getenv("C2_OFFLINE_THRESHOLD", "20"))
DEFAULT_CHECKIN_INTERVAL = int(os.getenv("C2_CHECKIN_INTERVAL", "5"))
