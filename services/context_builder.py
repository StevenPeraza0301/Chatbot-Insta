# context_builder.py (RAG estricto + interpretación basada en preguntas del dataset)
import re
import difflib
import unicodedata
import hashlib
import random
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Costa_Rica")  # Ajustable por país si lo deseas
except Exception:
    _TZ = None

from utils.country_selector import load_faqs, load_direcciones, load_horarios, get_user_country

URL_CENTROS = {
    "cr": "https://www.instacredit.com/centros_de_negocio/",
    "pa": "https://www.instacredit.com.pa/centros_de_negocio/",
    "nic": "https://www.instacredit.com.ni/centros_de_negocio/",
    "slv": "https://www.instacredit.sv/centros_de_negocio/"
}

def get_centros_url(user_id: str) -> str:
    country = (get_user_country(user_id) or "").lower()
    return URL_CENTROS.get(country, URL_CENTROS["cr"])

# ------------------------
# Normalización y tokens
# ------------------------
_PUNC_RE = re.compile(r"[!¡.,;:?¿\-\(\)\[\]\{\}<>\"'`/\\]")

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')
    text = _PUNC_RE.sub(" ", text)
    text = re.sub(r"(.)\1{2,}", r"\1", text)  # holaaa -> hola
    text = re.sub(r"\s+", " ", text).strip()
    return text

def normalize_tokens(text: str) -> List[str]:
    text = _normalize_text(text)
    tokens = text.split()
    # singularización ligera
    tokens = [t[:-1] if t.endswith('s') and len(t) > 3 else t for t in tokens]
    return tokens

# ------------------------
# Scoring semántico simple
# ------------------------
def _token_overlap_score(user_tokens: List[str], key_tokens: List[str]) -> float:
    if not user_tokens or not key_tokens:
        return 0.0
    u = set(user_tokens)
    k = set(key_tokens)
    inter = len(u.intersection(k))
    return inter / max(1, min(len(u), len(k)))

def _fuzzy_max_avg(user_tokens: List[str], key_tokens: List[str]) -> float:
    if not user_tokens or not key_tokens:
        return 0.0
    sims = []
    for ut in user_tokens:
        best = 0.0
        for kt in key_tokens:
            r = difflib.SequenceMatcher(None, ut, kt).ratio()
            if r > best:
                best = r
        sims.append(best)
    return sum(sims) / max(1, len(sims))

def _phrase_hit(user_text: str, phrases: List[str]) -> bool:
    for p in phrases:
        pnorm = _normalize_text(p)
        if pnorm and pnorm in user_text:
            return True
    return False

def score_match(user_msg: str, user_tokens: List[str], faq: Dict[str, Any]) -> float:
    """
    Combina:
      - solapamiento de tokens con keywords + pregunta + intención + subtipo + tipo
      - fuzzy promedio
      - bonus por frase exacta e indicios de intención
    """
    kw_list: List[str] = faq.get("keywords", [])
    pregunta: str = faq.get("pregunta", "")
    intencion: str = faq.get("intencion", "")
    subtipo: str = faq.get("subtipo", "")
    tipo: str = faq.get("tipo", "")

    key_tokens: List[str] = []
    for kw in kw_list:
        key_tokens += normalize_tokens(kw)
    key_tokens += normalize_tokens(pregunta)
    key_tokens += normalize_tokens(intencion.replace("_", " "))
    key_tokens += normalize_tokens(subtipo)
    key_tokens += normalize_tokens(tipo)

    overlap = _token_overlap_score(user_tokens, key_tokens)           # 0..1
    fuzzy = _fuzzy_max_avg(user_tokens, key_tokens)                   # 0..1

    user_norm = _normalize_text(user_msg)
    phrase_bonus = 0.15 if _phrase_hit(user_norm, kw_list + [pregunta]) else 0.0

    intent_hint = 0.0
    if intencion:
        for part in intencion.replace("_", " ").split():
            if part in user_norm:
                intent_hint += 0.03
        intent_hint = min(intent_hint, 0.12)

    score = (0.55 * overlap) + (0.35 * fuzzy) + phrase_bonus + intent_hint
    return min(score, 1.0)

# ------------------------
# Variantes de respuesta y CTAs
# ------------------------
def pick_response_variant(respuestas: List[str], user_id: str, user_msg: str) -> str:
    if not respuestas:
        return ""
    key = hashlib.sha256((user_id + "||" + user_msg).encode("utf-8")).hexdigest()
    seed = int(key[:8], 16)
    rnd = random.Random(seed)
    return rnd.choice(respuestas)

def render_acciones(acciones: List[Dict[str, str]]) -> str:
    if not acciones:
        return ""
    htmls = []
    for a in acciones:
        label = a.get("label", "Abrir enlace")
        url = a.get("url", "#")
        htmls.append(f'<a href="{url}" target="_blank">{label}</a>')
    return " • ".join(htmls)

def fix_links_html(text: str) -> str:
    text = re.sub(r'<a href="(<a href="[^"]+">[^<]+</a>)"[^>]*>[^<]+</a>', r'\1', text)
    text = re.sub(r'<a href="([^"]+)"[^>]*>\1</a>', r'<a href="\1" target="_blank">Ver enlace</a>', text)
    return text

def generar_saludo_local() -> str:
    now = datetime.now(_TZ) if _TZ else datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        return "¡Buenos días!"
    elif 12 <= hour < 18:
        return "¡Buenas tardes!"
    else:
        return "¡Buenas noches!"

# ------------------------
# Ranking y respuestas
# ------------------------
def rank_faqs(user_msg: str, user_id: str) -> List[Tuple[float, Dict[str, Any]]]:
    """Retorna lista [(score, faq_dict)] ordenada desc por score."""
    faqs: List[Dict[str, Any]] = load_faqs(user_id) or []
    if not isinstance(faqs, list):
        return []
    user_tokens = normalize_tokens(user_msg)
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for faq in faqs:
        if "respuestas" not in faq and "respuesta" in faq:
            r = faq.get("respuesta", "")
            faq["respuestas"] = [r] if r else []
        s = score_match(user_msg, user_tokens, faq)
        if s > 0:
            scored.append((s, faq))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored

def buscar_faqs_relevantes(user_msg: str, user_id: str, top_k: int = 4, min_score: float = 0.38) -> List[str]:
    """
    Devuelve lista de respuestas listas para mostrar (SIN prefijos tipo/subtipo).
    """
    scored = rank_faqs(user_msg, user_id)
    if not scored:
        return []
    mejores = [x for x in scored[:top_k] if x[0] >= min_score]

    relacionados: List[str] = []
    for score, faq in mejores:
        variante = pick_response_variant(faq.get("respuestas", []), user_id, user_msg)
        variante = fix_links_html(variante)
        acciones_html = render_acciones(faq.get("acciones", []))
        if acciones_html:
            relacionados.append(f"{variante} {acciones_html}")
        else:
            relacionados.append(f"{variante}")
    return relacionados

def top_faq_answer(user_msg: str, user_id: str, min_score: float = 0.45) -> Tuple[Optional[str], float, Optional[str], Optional[str], Optional[str]]:
    """
    Devuelve (answer_html, score, faq_id, intencion, pregunta_canon) de la mejor FAQ
    o (None, 0, None, None, None) si no supera min_score.
    """
    scored = rank_faqs(user_msg, user_id)
    if not scored:
        return (None, 0.0, None, None, None)
    best_ans: Tuple[Optional[str], float, Optional[str], Optional[str], Optional[str]] = (None, 0.0, None, None, None)
    for s, faq in scored:
        if s < min_score:
            continue
        variante = pick_response_variant(faq.get("respuestas", []), user_id, user_msg)
        variante = fix_links_html(variante)
        acciones_html = render_acciones(faq.get("acciones", []))
        html = f"{variante}" + (f" {acciones_html}" if acciones_html else "")
        if s > best_ans[1]:
            best_ans = (html, s, faq.get("id"), faq.get("intencion"), faq.get("pregunta"))
    return best_ans

# ------------------------
# Direcciones y horarios
# ------------------------
DIR_SYNONYMS = [
    'direccion', 'ubicacion', 'donde', 'ubicado', 'ubicada', 'sitio',
    'localizacion', 'zona', 'sucursal', 'oficina', 'waze', 'mapa'
]
HOR_SYNONYMS = ['horario', 'horarios', 'abre', 'cierra', 'hora', 'apertura', 'cierre']

def _contains_any_synonym(user_msg: str, syns: List[str]) -> bool:
    norm = normalize_tokens(user_msg)
    return any(s in norm for s in syns)

def tokens_match(user_tokens: list, keyword_tokens: list, threshold: float = 0.85) -> bool:
    for ut in user_tokens:
        for kt in keyword_tokens:
            if difflib.SequenceMatcher(None, ut, kt).ratio() >= threshold:
                return True
    return False

def buscar_direcciones(user_msg: str, user_id: str) -> List[str]:
    direcciones = load_direcciones(user_id) or []
    tokens = normalize_tokens(user_msg)
    relacionados: List[str] = []

    for d in direcciones:
        zona_tokens = normalize_tokens(d.get("zona", ""))
        keywords = d.get("keywords", [])
        keywords_normalized = d.get("keywords_normalized", [])

        kw_norm: List[str] = []
        for k in keywords + keywords_normalized:
            kw_norm += normalize_tokens(k)

        keywords_combined_normalized = list(set(zona_tokens + kw_norm))

        if tokens_match(tokens, keywords_combined_normalized, threshold=0.82):
            waze = d.get('waze', '').strip()
            waze_html = f' Waze: <a href="{waze}" target="_blank">Ver en Waze</a>' if waze else ""
            relacionados.append(f"{d.get('zona','Zona')}: {d.get('direccion','(sin dirección)')}.{waze_html}")

    if not relacionados:
        url = get_centros_url(user_id)
        relacionados.append(f"No encontré la dirección que buscás. Podés consultarla en: <a href=\"{url}\" target=\"_blank\">Centros de Negocio</a>")
    return relacionados

def buscar_horarios(user_msg: str, user_id: str) -> List[str]:
    horarios = load_horarios(user_id) or []
    tokens = normalize_tokens(user_msg)
    relacionados: List[str] = []
    for h in horarios:
        cdn_tokens = normalize_tokens(h.get('CDN', ''))
        if tokens_match(tokens, cdn_tokens, threshold=0.82):
            lv = h.get('Horario lunes a viernes', h.get('lunes_viernes', ''))
            sa = h.get('Sabados', h.get('sabado', ''))
            do = h.get('domingos', h.get('domingo', ''))
            relacionados.append(f"{h.get('CDN','Sucursal')}: lun-vie {lv}, sáb {sa}, dom {do}")
    if not relacionados:
        url = get_centros_url(user_id)
        relacionados.append(f"No encontré el horario solicitado. Podés consultarlo en: <a href=\"{url}\" target=\"_blank\">Centros de Negocio</a>")
    return relacionados

# ------------------------
# Contexto inteligente (para LLM si se usa)
# ------------------------
def build_context(message: str, user_id: str) -> str:
    contexto: List[str] = []

    faqs = buscar_faqs_relevantes(message, user_id)
    if faqs:
        contexto.append("FAQs relevantes:")
        contexto.extend(faqs)

    if _contains_any_synonym(message, DIR_SYNONYMS):
        direcciones = buscar_direcciones(message, user_id)
        if direcciones:
            contexto.append("\nDirecciones encontradas:")
            contexto.extend(direcciones)

    if _contains_any_synonym(message, HOR_SYNONYMS):
        horarios = buscar_horarios(message, user_id)
        if horarios:
            contexto.append("\nHorarios disponibles:")
            contexto.extend(horarios)

    if not contexto:
        return ""

    saludo = generar_saludo_local()
    return saludo + "\n" + "\n".join(contexto)
