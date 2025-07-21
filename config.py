# config.py

from pathlib import Path

# Configuración Flask
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5001

# Modelo Ollama
MODEL_NAME = "mistral"

# Tokens Meta
VERIFY_TOKEN = "TOKEN_SECRETO"
PAGE_ACCESS_TOKEN = "TOKEN_PAGINA_META"

# Timeout en segundos (15 min)
INACTIVITY_TIMEOUT = 5 * 60

# Carpetas de datos por país
DATA_PATH = Path("data")
AVAILABLE_COUNTRIES = {
    "CR": "cr",
    "NIC": "nic",
    "PA": "pa",
    "SLV": "slv"
}
