
# utils/geolocation_providers.py
import os
import requests
import streamlit as st

# =========================
# Google Maps
# =========================
def _get_google_api_key():
    try:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        return os.getenv("GOOGLE_MAPS_API_KEY")

def geocode_address_google(address: str):
    """
    Geocodifica una dirección usando Google Geocoding.
    Retorna (lat, lon) o (None, None) si falla o no hay API Key.
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

def places_nearby_google(lat: float, lon: float, radius_m: int, keyword=None, place_type=None):
    """
    Nearby Search (Google Places). Retorna lista de dicts:
    [{"name":..., "address":..., "lat":..., "lon":...}, ...]
    """
    api_key = _get_google_api_key()
    if not api_key:
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

# =========================
# OpenStreetMap (Nominatim + Overpass)
# =========================
def geocode_address_osm(address: str):
    """
    Geocodifica con Nominatim (OSM). Retorna (lat, lon) o (None, None) si falla.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "PreciosCercanosApp/1.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None, None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None, None

def places_nearby_osm(lat: float, lon: float, radius_m: int, key: str = "shop", value: str = "supermarket"):
    """
    Busca locales cercanos con Overpass API filtrando por key/value (OSM).
    Ej.: key="shop", value="supermarket" | key="amenity", value="pharmacy"
    Retorna lista de dicts: [{"name","address","lat","lon"}]
    """
    query = f"""
    [out:json];
    node{key}={value};
    out;
    """
    url = "https://overpass-api.de/api/interpreter"
    headers = {"User-Agent": "PreciosCercanosApp/1.0"}
    try:
        r = requests.post(url, data=query.encode("utf-8"), headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        elements = data.get("elements", [])
        out = []
        for el in elements:
            name = el.get("tags", {}).get("name", "Local sin nombre")
            addr = el.get("tags", {}).get("addr:street", "")
            out.append({"name": name, "address": addr, "lat": el["lat"], "lon": el["lon"]})
        return out
    except Exception:
        return []
``
