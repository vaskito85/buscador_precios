
# Ruta: utils/geocoding.py
import os
import requests
import streamlit as st

def _get_google_api_key():
    # 1) Streamlit secrets
    try:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        pass
    # 2) Variables de entorno
    return os.getenv("GOOGLE_MAPS_API_KEY")

def geocode_address(address: str):
    """
    Geocodifica una dirección a (lat, lon) usando Google Geocoding.
    Retorna (lat, lon) o (None, None) si falla.
    """
    api_key = _get_google_api_key()
    if not api_key:
        return None, None

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key, "language": "es"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None, None
        loc = data["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    except Exception:
        return None, None

def places_nearby(lat: float, lon: float, radius_m: int, keyword: str = None, place_type: str = None):
    """
    Consulta Google Places 'Nearby Search' y devuelve una lista de locales cercanos:
    [{ 'name': ..., 'address': ..., 'lat': ..., 'lon': ... }, ...]
    Puedes filtrar con keyword (ej. 'supermercado') o type (ej. 'supermarket').
    """
    api_key = _get_google_api_key()
    if not api_key or lat is None or lon is None:
        return []

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius": int(radius_m),
        "key": api_key,
        "language": "es",
    }
    if keyword:
        params["keyword"] = keyword
    if place_type:
        params["type"] = place_type

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        out = []
        for item in results:
            name = item.get("name")
            vicinity = item.get("vicinity") or item.get("formatted_address") or ""
            loc = item.get("geometry", {}).get("location", {})
            lt, ln = loc.get("lat"), loc.get("lng")
            if name and lt is not None and ln is not None:
                out.append({"name": name, "address": vicinity, "lat": float(lt), "lon": float(ln)})
        return out
    except Exception:
        return []
``
