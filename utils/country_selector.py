# utils/country_selector.py

import json
from pathlib import Path
from config import AVAILABLE_COUNTRIES, DATA_PATH

user_country_map = {}

def set_user_country(user_id: str, country_code: str):
    if country_code in AVAILABLE_COUNTRIES:
        user_country_map[user_id] = AVAILABLE_COUNTRIES[country_code]
        return True
    return False

def get_user_country(user_id: str) -> str:
    return user_country_map.get(user_id)

def load_horarios(user_id: str):
    country_folder = get_user_country(user_id)
    if not country_folder:
        return []
    file_path = DATA_PATH / country_folder / 'horarios.json'
    return json.loads(file_path.read_text(encoding='utf-8')) if file_path.exists() else []

def load_direcciones(user_id: str):
    country_folder = get_user_country(user_id)
    if not country_folder:
        return []
    file_path = DATA_PATH / country_folder / 'direcciones.json'
    return json.loads(file_path.read_text(encoding='utf-8')) if file_path.exists() else []

def load_faqs(user_id: str):
    country_folder = get_user_country(user_id)
    if not country_folder:
        return []
    file_path = DATA_PATH / country_folder / 'faqs.json'
    return json.loads(file_path.read_text(encoding='utf-8')) if file_path.exists() else []
