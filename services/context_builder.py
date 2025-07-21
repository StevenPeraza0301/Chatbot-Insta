import re
import unicodedata
from datetime import datetime
from utils.country_selector import load_faqs, load_direcciones, load_horarios, get_user_country

URL_CENTROS = {
    "cr": "https://www.instacredit.com/centros_de_negocio/",
    "pa": "https://www.instacredit.com.pa/centros_de_negocio/",
    "nic": "https://www.instacredit.com.ni/centros_de_negocio/",
    "slv": "https://www.instacredit.sv/centros_de_negocio/"
}

def get_centros_url(user_id: str) -> str:
    country = get_user_country(user_id)
    return URL_CENTROS.get(country, "https://www.instacredit.com/centros_de_negocio/")

def normalize_tokens(text: str) -> list:
    text = text.lower()
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[!¡.,;:?¿\\\-]', '', text)
    tokens = text.split()
    tokens = [t[:-1] if t.endswith('s') and len(t) > 3 else t for t in tokens]
    return tokens


DIR_SYNONYMS = [
    'dirección', 'direccion', 'ubicación', 'ubicacion', 'dónde', 'donde',
    'ubicado', 'ubicada', 'sitio', 'localización', 'localizacion', 'zona',
    'sucursal', 'oficina'
]
HOR_SYNONYMS = ['horario', 'horarios', 'abre', 'cierra', 'horas']

# --- Funciones de apoyo ---
def generar_saludo_local():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "¡Buenos días!"
    elif 12 <= hour < 18:
        return "¡Buenas tardes!"
    else:
        return "¡Buenas noches!"

def buscar_faqs_relevantes(user_msg: str, user_id: str):
    faqs = load_faqs(user_id)
    relacionados = []
    user_tokens = normalize_tokens(user_msg)

    for faq in faqs:
        keyword_list = faq.get("keywords", [])
        keyword_tokens = []
        for kw in keyword_list:
            keyword_tokens.extend(normalize_tokens(kw))

        if any(t in user_tokens for t in keyword_tokens):
            respuesta = faq['respuesta']
            # Reemplazar enlaces HTML mal formateados (doble anidamiento)
            respuesta = re.sub(r'<a href="(<a href="[^"]+">[^<]+</a>)"[^>]*>[^<]+</a>', r'\1', respuesta)
            # Reemplazar URLs en texto plano con un enlace corto si es posible
            respuesta = re.sub(r'<a href="([^"]+)"[^>]*>\1</a>', r'<a href="\1" target="_blank">Ver enlace</a>', respuesta)
            relacionados.append(f"{faq['tipo']}: {respuesta}")

    return relacionados

def buscar_direcciones(user_msg: str, user_id: str):
    direcciones = load_direcciones(user_id)
    tokens = normalize_tokens(user_msg)
    relacionados = []

    for d in direcciones:
        zona_tokens = normalize_tokens(d.get("zona", ""))
        keywords = d.get("keywords", [])
        keywords_normalized = d.get("keywords_normalized", [])

        keywords_combined = zona_tokens + keywords + keywords_normalized
        keywords_combined_normalized = set(normalize_tokens(" ".join(keywords_combined)))

        if any(k in tokens for k in keywords_combined_normalized):
            relacionados.append(f"{d['zona']}: {d['direccion']}. Waze: <a href=\"{d['waze']}\" target=\"_blank\">Ver en Waze</a>")

    if not relacionados:
        url = get_centros_url(user_id)
        relacionados.append(f"No encontré la dirección que buscas. Podés consultarla en: <a href=\"{url}\" target=\"_blank\">Centros de Negocio</a>")
    return relacionados

def buscar_horarios(user_msg: str, user_id: str):
    horarios = load_horarios(user_id)
    relacionados = []
    for h in horarios:
        if h.get('CDN', '').lower() in user_msg:
            relacionados.append(f"{h['CDN']}: lun-vie {h['Horario lunes a viernes']}, sáb {h['Sabados']}, dom {h['domingos']}")
    if not relacionados:
        url = get_centros_url(user_id)
        relacionados.append(f"No encontré el horario solicitado. Podés consultarlo en: <a href=\"{url}\" target=\"_blank\">Centros de Negocio</a>")
    return relacionados

# --- Contexto inteligente ---
def build_context(message: str, user_id: str) -> str:
    contexto = []

    faqs = buscar_faqs_relevantes(message, user_id)
    if faqs:
        contexto.append("FAQs relevantes:")
        contexto.extend(faqs)

    if any(w in message for w in DIR_SYNONYMS):
        direcciones = buscar_direcciones(message, user_id)
        if direcciones:
            contexto.append("\nDirecciones encontradas:")
            contexto.extend(direcciones)

    if any(w in message for w in HOR_SYNONYMS):
        horarios = buscar_horarios(message, user_id)
        if horarios:
            contexto.append("\nHorarios disponibles:")
            contexto.extend(horarios)

    if not contexto:
        return ""

    saludo = generar_saludo_local()
    return saludo + "\n" + "\n".join(contexto)
