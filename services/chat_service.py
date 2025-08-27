# chat_service.py (RAG estricto + interpretación + grounding + entrenamiento continuo)

import requests
import re
import difflib
import json
import os
from datetime import datetime
from typing import Optional, Tuple, List

from services.history_manager import (
    get_user_history, update_history, reset_user_history,
    get_context, set_context
)
from services.context_builder import build_context, top_faq_answer, rank_faqs
from utils.country_selector import get_user_country, set_user_country
from config import MODEL_NAME

# ---------------------------------
# Configuración de umbrales y LLM
# ---------------------------------
LLM_THRESHOLD = 0.9  # Usar Mistral solo si la predicción tiene score < 0.9
SHOW_INTERPRETATION = True  # Muestra la línea de interpretación basada SOLO en 'pregunta' del dataset
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

# Términos sensibles que NO deben aparecer si no están en el contexto
FORBIDDEN_TERMS = {
    "hipotecario", "hipoteca", "hipotecarios",
    "automotriz", "auto", "vehicular",
    "empresarial", "empresa", "negocio",
    "tarjeta de crédito", "tarjeta crédito"
}

# ---------------------------------
# Países y mensajes base (ES-CR)
# ---------------------------------
COUNTRY_CODES = {
    "1": "CR",
    "2": "NIC",
    "3": "PA",
    "4": "SLV",
    # Aceptar también entradas textuales
    "cr": "CR", "crc": "CR", "costa rica": "CR", "🇨🇷": "CR",
    "nic": "NIC", "ni": "NIC", "nicaragua": "NIC", "🇳🇮": "NIC",
    "pa": "PA", "panama": "PA", "panamá": "PA", "🇵🇦": "PA",
    "slv": "SLV", "sv": "SLV", "el salvador": "SLV", "salvador": "SLV", "🇸🇻": "SLV"
}

WELCOME_MESSAGE = (
    "¡Bienvenido! ¿Desde qué país nos visitas?\n"
    "1️⃣ Costa Rica 🇨🇷\n"
    "2️⃣ Nicaragua 🇳🇮\n"
    "3️⃣ Panamá 🇵🇦\n"
    "4️⃣ El Salvador 🇸🇻\n"
    "Por favor respondé con el número (1, 2, 3 o 4) o el nombre del país."
)

COURTESY_KEYWORDS = {
    "gracias": "¡Con mucho gusto! ¿Te puedo ayudar en algo más? 😊",
    "hola": "¡Hola! ¿En qué puedo ayudarte hoy?",
    "buenos días": "¡Buenos días! ¿Cómo puedo asistirte?",
    "buenas tardes": "¡Buenas tardes! ¿Necesitás ayuda con algo?",
    "buenas noches": "¡Buenas noches! ¿Te ayudo con horarios o direcciones?",
    "adiós": "¡Hasta luego! Fue un gusto ayudarte. 👋",
    "chao": "¡Chao! ¡Que tengas un excelente día! 👋"
}

# Frases que no queremos que el modelo devuelva (bloqueo/hard filters)
BLOCKLIST_SNIPPETS = [
    "soy un asistente de ai", "puedo ayudarte con programación", "no tengo información sobre ti",
    "puedo ayudarte con temas generales", "estoy aquí para ayudarte", "según internet",
    "encontré en la web", "puedes buscar en google", "paypal", "tarjeta crédito", "interbancario",
    "asistente virtual", "como modelo de lenguaje", "no tengo acceso a internet"
]

# ---------------------------------
# Rutas de logs para entrenamiento
# ---------------------------------
LOG_DIR = "logs"
TRAIN_FILE = os.path.join(LOG_DIR, "training_data.jsonl")  # para mejorar keywords/intenciones
LAST_PRED_FILE = os.path.join(LOG_DIR, "last_predictions.json")  # estado por usuario
NOCTX_FILE = os.path.join(LOG_DIR, "no_context_log.json")

# ---------------------------------
# Utilidades varias
# ---------------------------------
def _normalize_basic(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip().lower())

def _is_only_emojis(text: str) -> bool:
    return bool(re.fullmatch(r'[\W_]+', text.strip()))

def _map_country_freeform(message: str) -> Optional[str]:
    msg = _normalize_basic(message)
    if msg in COUNTRY_CODES:
        return COUNTRY_CODES[msg]
    labels = ["costa rica", "nicaragua", "panama", "panamá", "el salvador", "salvador", "cr", "ni", "pa", "sv", "slv"]
    best, score = None, 0.0
    for lab in labels:
        r = difflib.SequenceMatcher(None, msg, lab).ratio()
        if r > score:
            best, score = lab, r
    if best and score >= 0.72:
        return COUNTRY_CODES.get(best, None)
    return None

def is_country_selection(message: str) -> bool:
    return _map_country_freeform(message) is not None

def enrich_links(text: str) -> str:
    """Envuelve URLs en <a> salvo que ya estén en un <a>."""
    def _repl(m):
        url = m.group(0)
        left = text[max(0, m.start()-3):m.start()]
        right = text[m.end():min(len(text), m.end()+4)]
        if left.endswith('="') or left.endswith('>') or right.startswith('</a'):
            return url
        return f'<a href="{url}" target="_blank">{url}</a>'
    return re.sub(r'(https?://[^\s<]+)', _repl, text)

def detectar_cortesia(user_msg: str) -> Optional[str]:
    msg = _normalize_basic(user_msg)
    msg = re.sub(r'[!¡.,;:?¿]', '', msg)
    tokens = msg.split()
    if not tokens or _is_only_emojis(user_msg):
        return None

    cortesias = list(COURTESY_KEYWORDS.keys())
    mensaje_corto = len(tokens) <= 4

    mejor_match = None
    mejor_score = 0.0

    for frase in cortesias:
        frase_tokens = frase.split()
        coincidencias = 0
        for token in tokens:
            for ft in frase_tokens:
                score = difflib.SequenceMatcher(None, token, ft).ratio()
                if score >= 0.75:
                    coincidencias += 1
                    break
        ratio = coincidencias / max(1, len(frase_tokens))
        if ratio >= 0.75 and ratio > mejor_score:
            mejor_match = frase
            mejor_score = ratio

    if mejor_match and mensaje_corto:
        return COURTESY_KEYWORDS[mejor_match]
    return None

def _ensure_logdir():
    os.makedirs(LOG_DIR, exist_ok=True)

def record_training_sample(sample: dict):
    """Guarda interacciones para entrenar (jsonl)."""
    _ensure_logdir()
    sample["ts"] = datetime.utcnow().isoformat()
    with open(TRAIN_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")

def set_last_prediction(user_id: str, pred: dict):
    """Guarda última predicción por usuario (para feedback)."""
    _ensure_logdir()
    data = {}
    if os.path.exists(LAST_PRED_FILE):
        try:
            with open(LAST_PRED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    data[user_id] = pred
    with open(LAST_PRED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_last_prediction(user_id: str) -> Optional[dict]:
    if not os.path.exists(LAST_PRED_FILE):
        return None
    try:
        with open(LAST_PRED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            return data.get(user_id)
    except Exception:
        return None

def detect_negative_feedback(user_msg: str) -> bool:
    m = _normalize_basic(user_msg)
    negatives = [
        "no", "no es eso", "eso no era", "incorrecto", "equivocado",
        "no me sirve", "no responde", "no aplica", "nada que ver"
    ]
    return any(m == n or n in m for n in negatives)

def log_no_context_question(question: str, answer: str):
    _ensure_logdir()
    data: List[dict] = []
    if os.path.exists(NOCTX_FILE):
        try:
            with open(NOCTX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or []
        except json.JSONDecodeError:
            data = []
    data.append({"question": question, "answer": answer, "ts": datetime.utcnow().isoformat()})
    with open(NOCTX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def call_ollama(messages: list) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0}
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "Lo siento, no recibí respuesta.")
    except Exception as e:
        print(f"Error llamando a Ollama: {e}")
        return f"Error al contactar con Ollama: {e}"

def sanitize_model_output(text: str) -> Tuple[str, bool]:
    if not text:
        return "", True
    t = text.strip()
    low = t.lower()

    if "error al contactar con ollama" in low:
        return t, True

    if any(snippet in low for snippet in BLOCKLIST_SNIPPETS):
        return t, True

    generic_patterns = [
        r"no (tengo|tengo suficiente) información",
        r"no puedo ayudarte con eso",
        r"no estoy seguro",
        r"no encontr[ée] información",
        r"no recib[ií] respuesta"
    ]
    if any(re.search(p, low) for p in generic_patterns):
        return t, True

    return t, False

def response_grounded_in_context(model_text: str, context: str) -> bool:
    low = model_text.lower()
    ctx = context.lower()
    for term in FORBIDDEN_TERMS:
        if term in low and term not in ctx:
            return False
    urls = re.findall(r'https?://[^\s<>"\)]+', model_text, flags=re.I)
    for u in urls:
        if u.lower() not in ctx:
            return False
    return True

# ---------------------------------
# Construcción de mensajes a LLM
# ---------------------------------
def build_ollama_messages(user_id: str, context: str, history: list, user_msg: str) -> list:
    system_rules = (
        "Eres un asistente que responde únicamente en español y SOLO con la información incluida en el CONTEXTO.\n"
        "Prohibido inventar, asumir o añadir datos no presentes en el contexto.\n"
        "No inventes tipos de productos, tasas, requisitos, montos ni políticas si no están explícitos.\n"
        "Si el contexto no contiene la respuesta, contesta exactamente:\n"
        "'Lo siento, no encontré información para ayudarte con eso. ¿Podés reformular tu pregunta?'\n"
        "Si el contexto incluye enlaces o acciones (CTAs), inclúyelos tal cual, sin modificarlos.\n"
        "Responde breve, clara y literalmente con base en los datos del contexto."
    )
    return [
        {"role": "system", "content": system_rules},
        {"role": "system", "content": context},
        *history,
        {"role": "user", "content": user_msg}
    ]

# ---------------------------------
# Comandos de sesión
# ---------------------------------
def _maybe_handle_command(user_id: str, user_msg: str) -> Optional[str]:
    msg = _normalize_basic(user_msg)
    if msg in {"reiniciar", "reset", "limpiar", "borrar"}:
        reset_user_history(user_id)
        set_context(user_id, "")
        set_last_prediction(user_id, None)
        return "He reiniciado tu sesión. ¿Desde qué país nos visitas?\n" + WELCOME_MESSAGE
    if msg in {"cambiar pais", "cambiar país", "menu", "menú", "pais", "país"}:
        reset_user_history(user_id)
        set_context(user_id, "")
        set_user_country(user_id, None)
        set_last_prediction(user_id, None)
        return WELCOME_MESSAGE
    return None

# ---------------------------------
# Flujo principal
# ---------------------------------
def handle_message(user_id: str, user_msg: str, channel='web') -> str:
    # Feedback negativo: registra desaciertos del último turno
    if detect_negative_feedback(user_msg):
        last = get_last_prediction(user_id)
        if last:
            record_training_sample({
                "label": "negative",
                "user_id": user_id,
                "country": get_user_country(user_id),
                "user_msg": last.get("user_msg"),
                "selected": last.get("selected"),
                "alternatives": last.get("alternatives"),
                "note": "user_neg_feedback"
            })
        return "Gracias por avisar. ¿Podés decirme con qué tema específico necesitás ayuda para mejorar la respuesta?"

    # Comandos rápidos
    cmd = _maybe_handle_command(user_id, user_msg)
    if cmd:
        return cmd

    user_country = get_user_country(user_id)

    # Selección de país
    if not user_country:
        if is_country_selection(user_msg):
            new_code = _map_country_freeform(user_msg)
            set_user_country(user_id, new_code)
            reset_user_history(user_id)
            set_last_prediction(user_id, None)
            print(f"[info] Usuario {user_id} eligió país {new_code}")
            return "¡Gracias! Ahora podés preguntarme lo que necesités. 😊"
        else:
            return WELCOME_MESSAGE

    # Cortesías
    respuesta_cortesia = detectar_cortesia(user_msg)
    if respuesta_cortesia:
        return respuesta_cortesia

    # Contexto actualizado (para LLM si se usa)
    nuevo_contexto = build_context(user_msg, user_id)
    if nuevo_contexto.strip():
        set_context(user_id, nuevo_contexto)

    context = get_context(user_id)

    # Si no hay contexto utilizable, guardamos y devolvemos fallback
    if context.strip() == "":
        fallback = "Lo siento, no encontré información para ayudarte con eso. ¿Podés reformular tu pregunta?"
        log_no_context_question(user_msg, fallback)
        update_history(user_id, user_msg, fallback)
        set_last_prediction(user_id, None)
        return fallback

    # *** DECISIÓN DE RESPUESTA ***
    # Intentamos clasificar y responder directo del dataset
    answer_html, score, faq_id, intent, canon_question = top_faq_answer(
        user_msg, user_id, min_score=0.0
    )

    if answer_html and score >= LLM_THRESHOLD:
        # Guardamos candidatos para entrenamiento
        ranked = rank_faqs(user_msg, user_id)[:3]
        alts = [{"faq_id": f.get("id"), "intencion": f.get("intencion"), "score": float(s)} for s, f in ranked]

        record_training_sample({
            "label": "auto",
            "user_id": user_id,
            "country": user_country,
            "user_msg": user_msg,
            "selected": {"faq_id": faq_id, "intencion": intent, "score": float(score)},
            "alternatives": alts
        })
        set_last_prediction(user_id, {
            "user_msg": user_msg,
            "selected": {"faq_id": faq_id, "intencion": intent, "score": float(score)},
            "alternatives": alts
        })

        # Interpretación SOLO basada en 'pregunta' del dataset (sin prefijos)
        interpretation = ""
        if SHOW_INTERPRETATION and canon_question:
            interpretation = f"Interpreté tu consulta como: {canon_question}.\n\n"

        final_msg = f"{interpretation}{answer_html}"
        if channel == 'web':
            final_msg = enrich_links(final_msg)

        update_history(user_id, user_msg, final_msg)
        return final_msg

    # --- Uso de Mistral cuando el score es menor al umbral ---
    set_last_prediction(user_id, None)
    history, expired = get_user_history(user_id)
    messages = build_ollama_messages(user_id, context, history, user_msg)
    bot_msg = call_ollama(messages)

    # Sanitizar y validar grounding
    bot_msg, bloqueado = sanitize_model_output(bot_msg)
    if not bloqueado:
        if not response_grounded_in_context(bot_msg, context):
            bloqueado = True

    if bloqueado or bot_msg.strip() == "":
        log_no_context_question(user_msg, bot_msg.strip())
        bot_msg = "Lo siento, no encontré información para ayudarte con eso. ¿Podés reformular tu pregunta?"

    update_history(user_id, user_msg, bot_msg)

    if channel == 'web':
        bot_msg = enrich_links(bot_msg)

    if expired:
        return "Tu sesión ha expirado por inactividad. He reiniciado la conversación. 😊\n\n" + bot_msg

    return bot_msg
