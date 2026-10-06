import os
from pathlib import Path
#directory path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)




DB_PATH = os.getenv("C2_DB_PATH", str(DATA_DIR / "c2_system.db"))


#server setting

SERVER_HOST = os.getenv("C2_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("C2_SERVER_PORT", "8000"))




SECRET_KEY = os.getenv("C2_SECRET_KEY", "c2-secret-demo-key-2026")





AGENT_OFFLINE_THRESHOLD_SECONDS = int(os.getenv("C2_OFFLINE_THRESHOLD", "20"))
DEFAULT_CHECKIN_INTERVAL = int(os.getenv("C2_CHECKIN_INTERVAL", "5"))
