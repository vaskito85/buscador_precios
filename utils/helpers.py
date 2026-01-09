
# utils/helpers.py
import re

UNITS_MAP = {"lt": "l", "l": "l", "kg": "kg", "gr": "g", "g": "g", "ml": "ml"}
COMMON_WORDS_CAP = {"leche", "yerba", "arroz", "aceite", "azúcar", "fideos", "harina", "café", "te", "té"}

def normalize_product(name: str) -> str:
    """Versión canónica del nombre para DB: lower, trim, colapsa espacios, normaliza unidades y elimina puntuación."""
    if not name:
        return ""
    s = name.strip().lower()
    s = " ".join(s.split())  # colapsar espacios múltiples
    s = re.sub(r"(\d+)\s*(lt|l|kg|gr|g|ml)\b", lambda m: f"{m.group(1)} {UNITS_MAP[m.group(2)]}", s)
    s = " ".join(s.split())
    tokens = s.split()
    s = " ".join([UNITS_MAP[t] if t in UNITS_MAP else t for t in tokens])
    s = re.sub(r"[.,;:]+", "", s)
    return s

def prettify_product(name: str) -> str:
    """Presentación del nombre en UI: capitaliza palabras comunes, mantiene unidades en minúscula."""
    if not name:
        return ""
    tokens = name.split()
    pretty = []
    for t in tokens:
        if t in UNITS_MAP.values():  # unidades
            pretty.append(t)
        elif t in COMMON_WORDS_CAP:
            pretty.append(t.capitalize())
        else:
            pretty.append(t[0].upper() + t[1:] if len(t) > 1 else t.upper())
    return " ".join(pretty)

def parse_coord(txt: str):
    try:
        return float(txt)
    except:
        return None

def confidence_label(count: int) -> str:
    if count == 1:
        return "Reportado por 1 persona (puede variar)"
    if 2 <= count <= 3:
        return f"Confirmado por {count} personas (confianza media)"
    return f"Confirmado por {count} personas (alta confianza)"

def confidence_class(count: int) -> str:
    if count == 1:
        return "confidence-red"
    if 2 <= count <= 3:
        return "confidence-yellow"
    return "confidence-green"
