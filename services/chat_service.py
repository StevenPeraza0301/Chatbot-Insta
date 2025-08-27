import requests
import re
import difflib
import json
import os
from services.history_manager import get_user_history, update_history, reset_user_history, get_context, set_context
from services.context_builder import build_context
from utils.country_selector import get_user_country, set_user_country
from config import MODEL_NAME

# TODO: Extraer WELCOME_MESSAGE y COURTESY_KEYWORDS a un archivo messages_es.py para traducción y reutilización

COUNTRY_CODES = {
    "1": "CR",
    "2": "NIC",
    "3": "PA",
    "4": "SLV"
}

WELCOME_MESSAGE = (
    "¡Bienvenido! ¿Desde qué país nos visitas?\n"
    "1️⃣ Costa Rica 🇨🇷\n"
    "2️⃣ Nicaragua 🇳🇮\n"
    "3️⃣ Panamá 🇵🇦\n"
    "4️⃣ El Salvador 🇸🇻\n"
    "Por favor responde con el número (1, 2, 3 o 4)."
)

COURTESY_KEYWORDS = {
    "gracias": "¡Con mucho gusto! ¿Te puedo ayudar en algo más? 😊",
    "hola": "¡Hola! ¿En qué puedo ayudarte hoy?",
    "buenos días": "¡Buenos días! ¿Cómo puedo asistirte?",
    "buenas tardes": "¡Buenas tardes! ¿Necesitás ayuda con algo?",
    "buenas noches": "¡Buenas noches! ¿Te ayudo con horarios o direcciones?",
    "adiós": "¡Hasta luego! Fue un gusto ayudarte. 👋",
    "chao": "¡Chao! Que tengas un excelente día. 👋"
}


def log_no_context_question(question, answer):
    try:
        os.makedirs("logs", exist_ok=True)
        log_file = os.path.join("logs", "no_context_log.json")
        print(f"[log] Intentando guardar pregunta sin contexto en {log_file}")

        data = []

        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    print(f"[log] Cargado log existente con {len(data)} entradas")
                except json.JSONDecodeError:
                    print("[log] JSON corrupto o vacío, iniciando nuevo log")
                    data = []

        data.append({"question": question, "answer": answer})

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"[log] Guardado exitoso. Total actual: {len(data)} preguntas sin contexto.")

    except Exception as e:
        print(f"[error] Fallo al guardar no_context_log.json: {e}")


def detectar_cortesia(user_msg: str) -> str | None:
    msg = user_msg.strip().lower()
    msg = re.sub(r'[!¡.,;:?¿]', '', msg)
    tokens = msg.split()
    if not tokens:
        return None

    cortesias = list(COURTESY_KEYWORDS.keys())
    mensaje_corto = len(tokens) <= 3

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
        ratio = coincidencias / len(frase_tokens)
        if ratio >= 0.75 and ratio > mejor_score:
            mejor_match = frase
            mejor_score = ratio

    if mejor_match and mensaje_corto:
        return COURTESY_KEYWORDS[mejor_match]

    return None


def is_country_selection(message: str) -> bool:
    return message.strip() in COUNTRY_CODES


def enrich_links(text: str) -> str:
    return re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank">\1</a>', text)


def call_ollama(messages: list) -> str:
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0}
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "Lo siento, no recibí respuesta.")
    except Exception as e:
        print(f"Error llamando a Ollama: {e}")
        return f"Error al contactar con Ollama: {e}"


def handle_message(user_id: str, user_msg: str, channel='web') -> str:
    user_country = get_user_country(user_id)

    if not user_country:
        if is_country_selection(user_msg):
            set_user_country(user_id, COUNTRY_CODES[user_msg.strip()])
            reset_user_history(user_id)
            print(f"[info] Usuario {user_id} eligió país {COUNTRY_CODES[user_msg.strip()]}")
            return "¡Gracias! Ahora puedes preguntarme lo que necesites. 😊"
        else:
            return WELCOME_MESSAGE

    respuesta_cortesia = detectar_cortesia(user_msg)
    if respuesta_cortesia:
        return respuesta_cortesia

    nuevo_contexto = build_context(user_msg, user_id)
    if nuevo_contexto.strip():
        set_context(user_id, nuevo_contexto)

    context = get_context(user_id)
    if context.strip() == "":
        fallback = "Lo siento, no encontré información para ayudarte con eso. ¿Podés reformular tu pregunta?"
        log_no_context_question(user_msg, fallback)
        update_history(user_id, user_msg, fallback)
        return fallback

    history, expired = get_user_history(user_id)

    messages = build_ollama_messages(user_id, context, history, user_msg)

    bot_msg = call_ollama(messages)

    frases_bloqueo = [
        "soy un asistente de ai", "puedo ayudarte con programación", "no tengo información sobre ti",
        "puedo ayudarte con temas generales", "estoy aquí para ayudarte", "según internet",
        "encontré en la web", "puedes buscar en google", "paypal", "tarjeta crédito", "interbancario"
    ]

    bloqueado = any(f in bot_msg.lower() for f in frases_bloqueo)
    if (
        bloqueado
        or "no encontré información para ayudarte" in bot_msg.lower()
        or bot_msg.strip() == ""
        or bot_msg.strip().lower() == "lo siento, no recibí respuesta."
    ):
        log_no_context_question(user_msg, bot_msg.strip())
        bot_msg = "Lo siento, no encontré información para ayudarte con eso. ¿Podés reformular tu pregunta?"

    update_history(user_id, user_msg, bot_msg)

    if channel == 'web':
        bot_msg = enrich_links(bot_msg)

    if expired:
        return "Tu sesión ha expirado por inactividad. He reiniciado la conversación. 😊\n\n" + bot_msg

    return bot_msg


def build_ollama_messages(user_id: str, context: str, history: list, user_msg: str) -> list:
    return [
        {
            "role": "system",
            "content": (
                "Eres un asistente útil que responde únicamente en español y solo con los datos proporcionados en el contexto del país correspondiente. "
                "No debes inventar ni ampliar información. "
                "Si el contexto no contiene los datos necesarios, responde con: "
                "'Lo siento, no encontré información para ayudarte con eso. ¿Podés reformular tu pregunta?'"
            )
        },
        {"role": "system", "content": context},
        *history,
        {"role": "user", "content": user_msg}
    ]
