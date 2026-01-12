
# Ruta: utils/osm_client.py
import requests

def geocode_address_osm(address: str):
    """
    Geocodifica una dirección usando Nominatim (OpenStreetMap).
    Retorna (lat, lon) o (None, None) si falla.
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
    Busca locales cercanos usando Overpass API.
    Por defecto busca supermercados, pero podés cambiar key/value.
    Retorna lista de dicts: [{name, address, lat, lon}, ...]
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
