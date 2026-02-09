import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:gameserver123@mysql:3306/gameserver?charset=utf8mb4"
)
DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "unix:///var/run/docker.sock")

# Docker Manager Configuration
DOCKER_TIMEOUT = int(os.getenv("DOCKER_TIMEOUT", "30"))
DOCKER_PULL_TIMEOUT = int(os.getenv("DOCKER_PULL_TIMEOUT", "300"))
DOCKER_STOP_TIMEOUT = int(os.getenv("DOCKER_STOP_TIMEOUT", "10"))

# Security Configuration
API_KEY = os.getenv("API_KEY", "")  # Empty means no auth required (dev mode)
API_KEY_HEADER = "X-API-Key"

# Resource Limits
MAX_SERVERS = int(os.getenv("MAX_SERVERS", "10"))
DEFAULT_MEMORY_LIMIT = os.getenv("DEFAULT_MEMORY_LIMIT", "512m")
DEFAULT_CPU_LIMIT = float(os.getenv("DEFAULT_CPU_LIMIT", "1.0"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "/var/log/gameserver/app.log")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "10485760"))  # 10MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# State Sync Configuration
STATE_SYNC_INTERVAL = int(os.getenv("STATE_SYNC_INTERVAL", "60"))  # seconds
