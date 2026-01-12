
# app.py
import time
from typing import List, Dict
from collections import defaultdict

import streamlit as st

from utils.supabase_client import get_supabase
from utils.helpers import (
    normalize_product, prettify_product, parse_coord,
    confidence_label, confidence_class,
)
from utils.geolocation_providers import (
    geocode_address_google, places_nearby_google,
    geocode_address_osm, places_nearby_osm
)

# =========================
# Configuración general
# =========================
st.set_page_config(page_title="Precios Cercanos", layout="wide")

# Cargar CSS externo (styles.css)
try:
    with open("styles.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("styles.css no encontrado. Subilo al repo.")

# Conexión a Supabase
supabase = get_supabase()

# =========================
# Estado de sesión (inicial)
# =========================
st.session_state.setdefault("session", None)
st.session_state.setdefault("user_email", None)
st.session_state.setdefault("auth_msg", None)

# Navegación (incluye nueva página "Locales")
SECCIONES_BASE = ["Login", "Cargar Precio", "Lista de Precios", "Alertas", "Locales"]
st.session_state.setdefault("nav", "Login")

# Realtime (polling local)
st.session_state.setdefault("notif_auto", True)
st.session_state.setdefault("last_notif_id", 0)
st.session_state.setdefault("logs", [])
st.session_state.setdefault("otp_last_send", 0.0)

# =========================
# Helpers de sesión/seguridad
# =========================
def add_log(level: str, msg: str):
    st.session_state.logs.append({"level": level, "msg": msg, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})

def get_user_id():
    sess = st.session_state.get("session")
    return getattr(getattr(sess, "user", None), "id", None)

def is_admin() -> bool:
    uid = get_user_id()
    if not uid:
        return False
    try:
        row = supabase.table("admins").select("user_id").eq("user_id", uid).limit(1).execute()
        return bool(row.data)
    except Exception:
        return False

def require_auth() -> bool:
    if not (st.session_state.session and get_user_id()):
        st.session_state.auth_msg = "Tu sesión no está activa. Iniciá sesión para continuar."
        st.session_state.nav = "Login"
        st.rerun()
        return False
    return True

def set_location_from_gps(lat_key: str, lon_key: str):
    """Obtiene ubicación con streamlit-geolocation y setea lat/lon + query params."""
    try:
        from streamlit_geolocation import geolocation
        loc = geolocation()
        if isinstance(loc, dict) and "lat" in loc and "lon" in loc and loc["lat"] and loc["lon"]:
            st.session_state[lat_key] = str(loc["lat"])
            st.session_state[lon_key] = str(loc["lon"])
            # Reflejar en URL (desde servidor)
            st.query_params.lat = str(loc["lat"])
            st.query_params.lon = str(loc["lon"])
            st.success("📍 Ubicación actual establecida.")
        else:
            st.warning("No se pudo obtener tu ubicación (permiso denegado o sin datos).")
    except Exception as e:
        st.warning(f"No se pudo acceder al GPS del navegador: {e}")

# =========================
# Sidebar + navegación
# =========================
SECCIONES = SECCIONES_BASE + (["Admin"] if is_admin() else [])
st.sidebar.title("🧭 Navegación")
page = st.sidebar.radio("Secciones", SECCIONES, index=SECCIONES.index(st.session_state["nav"]))

if st.session_state.session:
    st.sidebar.success(f"Conectado: {st.session_state.user_email}")
    if st.sidebar.button("Cerrar sesión"):
        supabase.auth.sign_out()
        st.session_state.session = None
        st.session_state.user_email = None
        st.session_state.nav = "Login"
        st.rerun()

# Modo debug solo si sos admin
if is_admin():
    st.sidebar.checkbox("🧪 Modo debug", key="debug", value=False)
else:
    st.session_state["debug"] = False

if page != st.session_state["nav"]:
    st.session_state["nav"] = page

# =========================
# PÁGINA LOGIN (OTP)
# =========================
if page == "Login":
    st.title("🔐 Login (OTP por email)")
    if st.session_state.auth_msg:
        st.info(st.session_state.auth_msg)
        st.session_state.auth_msg = None

    col_email, col_otp = st.columns(2)
    email = col_email.text_input("Email", placeholder="tu@correo.com")
    otp = col_otp.text_input("Código OTP", placeholder="123456")

    COOLDOWN_SEC = 60
    now = time.time()
    elapsed = now - st.session_state.otp_last_send
    cooldown_active = elapsed < COOLDOWN_SEC
    remaining = max(0, int(COOLDOWN_SEC - elapsed))

    if cooldown_active:
        st.button(f"Enviar código (OTP) — Esperá {remaining}s", disabled=True)
        st.caption("Evitemos reenvíos seguidos para que el correo no lo marque como spam.")
    else:
        if st.button("Enviar código (OTP)"):
            if not email or "@" not in email:
                st.error("Email inválido.")
            else:
                try:
                    supabase.auth.sign_in_with_otp({"email": email})
                    st.session_state.otp_last_send = time.time()
                    st.info("✅ Código enviado. Revisá tu email.")
                except Exception as e:
                    st.error(f"No pudimos enviar el OTP: {e}")

    if st.button("Validar código"):
        try:
            session = supabase.auth.verify_otp({"email": email, "token": otp, "type": "email"})
            st.session_state.session = session
            st.session_state.user_email = email
            st.success("¡Listo! Sesión iniciada.")
            st.session_state["nav"] = "Cargar Precio"
            st.rerun()
        except Exception as e:
            st.error(f"No pudimos validar el código: {e}")

# =========================
# PÁGINA CARGAR PRECIO
# =========================
elif page == "Cargar Precio":
    if not require_auth():
        st.stop()

    st.title("🛒 Registrar precio")

    # Prefill desde query params
    if "lat" in st.query_params:
        st.session_state["lat_txt"] = st.query_params["lat"]
    if "lon" in st.query_params:
        st.session_state["lon_txt"] = st.query_params["lon"]

    # Ubicación + Radio (km/metros)
    st.subheader("Tu ubicación")
    col_lat, col_lon, col_unit, col_rad = st.columns([1, 1, 0.8, 1.2])
    lat_txt = col_lat.text_input("Latitud", key="lat_txt", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", key="lon_txt", placeholder="-62.2663")
    unit = col_unit.selectbox("Unidad de radio", ["Kilómetros", "Metros"], index=0)
    if unit == "Kilómetros":
        radius_value = col_rad.slider("Radio (km)", 1, 15, 5)
        radius_m = int(radius_value * 1000)
    else:
        radius_value = col_rad.slider("Radio (m)", 50, 500, 200, step=50)
        radius_m = int(radius_value)

    # Botón GPS nativo (Cloud-safe)
    if st.button("📍 Usar mi ubicación actual (GPS)"):
        set_location_from_gps("lat_txt", "lon_txt")

    # Parseo
    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)

    # Búsqueda de locales cercanos (DB)
    nearby_options: List[Dict] = []
    store_choice = None
    if lat is not None and lon is not None:
        try:
            res = supabase.rpc(
                "nearby_stores",
                {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_m) / 1000.0}
            ).execute()
            nearby_options = res.data or []
        except Exception as e:
            st.info("Aún no hay locales cercanos o hubo un error con la búsqueda.")
            add_log("ERROR", f"nearby_stores: {e}")

    st.subheader("Local")

    # Selector de categorías OSM para sugerencias externas
    OSM_CATEGORIES = {
        "Supermercados": ("shop", "supermarket"),
        "Almacenes": ("shop", "convenience"),
        "Farmacias": ("amenity", "pharmacy"),
        "Verdulerías": ("shop", "greengrocer"),
        "Panaderías": ("shop", "bakery"),
        "Kioscos": ("shop", "kiosk"),
    }

    with st.expander("🔍 Sugerencias cercanas (Google/OSM)", expanded=False):
        kw = st.text_input("Filtro (Google) opcional, ej.: 'supermercado'")
        t = st.text_input("Tipo (Google) opcional, ej.: 'supermarket'")
        osm_choice = st.selectbox("Categoría OSM (para Overpass)", list(OSM_CATEGORIES.keys()))
        if st.button("Buscar locales cercanos"):
            if lat is None or lon is None:
                st.error("Definí latitud/longitud (GPS o manual).")
            else:
                g_places = places_nearby_google(lat, lon, radius_m, keyword=kw or None, place_type=t or None)
                if not g_places:
                    key, value = OSM_CATEGORIES[osm_choice]
                    g_places = places_nearby_osm(lat, lon, radius_m, key=key, value=value)
                if not g_places:
                    st.info("No se encontraron sugerencias.")
                else:
                    for idx, pl in enumerate(g_places, start=1):
                        st.write(f"{idx}. **{pl['name']}** — {pl['address']}")
                        if st.button(f"Agregar este local #{idx}", key=f"add_place_{idx}"):
                            try:
                                ins = supabase.rpc(
                                    "insert_store",
                                    {
                                        "p_name": pl["name"],
                                        "p_address": pl["address"],
                                        "p_lat": float(pl["lat"]),
                                        "p_lon": float(pl["lon"]),
                                    }
                                ).execute()
                                store_choice = (ins.data or [{}])[0].get("id")
                                st.session_state["store_choice"] = store_choice
                                st.success("Local agregado y seleccionado.")
                            except Exception as e:
                                st.error(f"No se pudo crear el local: {e}")
                                add_log("ERROR", f"Insert store (sugerencia): {e}")

    # Selección desde DB
    if nearby_options:
        labels = {s["id"]: f"{s['name']} ({int(s['meters'])} m)" for s in nearby_options}
        ids = list(labels.keys())
        selected_id = st.selectbox("Elegí un local cercano", ids, format_func=lambda x: labels[x])
        store_choice = selected_id
    else:
        st.info("No encontramos locales cerca de tu ubicación. Podés crear uno nuevo.")
        tabs = st.tabs(["📍 Por dirección", "➕ Crear manual (lat/lon)"])
        with tabs[0]:
            new_store_name_a = st.text_input("Nombre del local", key="new_store_name_a")
            new_store_address_a = st.text_input("Dirección", key="new_store_address_a", placeholder="Calle y número, ciudad")
            if st.button("Buscar coordenadas y guardar"):
                if not new_store_name_a or not new_store_address_a:
                    st.error("Ingresá nombre y dirección.")
                else:
                    g_lat, g_lon = geocode_address_google(new_store_address_a)
                    if not g_lat or not g_lon:
                        g_lat, g_lon = geocode_address_osm(new_store_address_a)
                    if g_lat is None or g_lon is None:
                        st.error("No se pudo geocodificar la dirección (sin resultados).")
                    else:
                        try:
                            ins = supabase.rpc(
                                "insert_store",
                                {"p_name": new_store_name_a, "p_address": new_store_address_a, "p_lat": float(g_lat), "p_lon": float(g_lon)}
                            ).execute()
                            store_choice = (ins.data or [{}])[0].get("id")
                            st.session_state["store_choice"] = store_choice
                            st.success(f"Local creado y seleccionado (lat={g_lat}, lon={g_lon}).")
                        except Exception as e:
                            st.error(f"No se pudo crear el local: {e}")
                            add_log("ERROR", f"Insert store (geocode): {e}")

        with tabs[1]:
            new_store_name = st.text_input("Nombre del local", key="new_store_name")
            new_store_address = st.text_input("Dirección (opcional)", key="new_store_address")
            lat_new = st.text_input("Latitud del local", key="lat_new", placeholder="-38.7180")
            lon_new = st.text_input("Longitud del local", key="lon_new", placeholder="-62.2700")
            if st.button("Guardar local"):
                if not new_store_name:
                    st.error("Ingresá el nombre del local.")
                else:
                    lat_n = parse_coord(lat_new)
                    lon_n = parse_coord(lon_new)
                    if lat_n is None or lon_n is None:
                        st.error("Ingresá latitud y longitud válidas.")
                    else:
                        try:
                            ins = supabase.rpc(
                                "insert_store",
                                {"p_name": new_store_name, "p_address": new_store_address, "p_lat": float(lat_n), "p_lon": float(lon_n)}
                            ).execute()
                            store_choice = (ins.data or [{}])[0].get("id")
                            st.session_state["store_choice"] = store_choice
                            st.success("Local creado y seleccionado.")
                        except Exception as e:
                            st.error(f"No se pudo crear el local: {e}")
                            add_log("ERROR", f"Insert store (manual): {e}")

    st.subheader("Producto y precio")
    product_name_input = st.text_input("Nombre del producto")
    price = st.number_input("Precio", min_value=0.0, step=0.01, format="%.2f")
    currency = st.selectbox("Moneda", ["ARS", "USD", "EUR"])

    if st.button("Registrar precio"):
        if not product_name_input:
            st.error("Ingresá el nombre del producto.")
            st.stop()

        if not store_choice and "store_choice" in st.session_state:
            store_choice = st.session_state["store_choice"]

        if not store_choice:
            st.error("Seleccioná un local o creá uno nuevo.")
            st.stop()

        # Asegurarnos de tener lat/lon del usuario; si no, usamos las del local:
        lat = parse_coord(st.session_state.get("lat_txt", ""))
        lon = parse_coord(st.session_state.get("lon_txt", ""))

        if lat is None or lon is None:
            try:
                srow = supabase.table("stores").select("id, lat, lon").eq("id", store_choice).single().execute()
                lat = srow.data["lat"]
                lon = srow.data["lon"]
            except Exception:
                st.error("No hay coordenadas del usuario ni del local seleccionadas.")
                st.stop()

        user_id = get_user_id()
        if not user_id:
            st.error("Tu sesión expiró. Iniciá sesión nuevamente.")
            st.session_state.nav = "Login"
            st.rerun()

        product_name = normalize_product(product_name_input)

        try:
            pid_res = supabase.rpc("upsert_product", {"p_name": product_name, "p_currency": currency}).execute()
            product_id = pid_res.data[0]["id"] if pid_res.data else None
            if not product_id:
                raise RuntimeError("upsert_product no devolvió id")
        except Exception as e:
            st.error(f"No se pudo crear/obtener el producto: {e}")
            add_log("ERROR", f"upsert_product: {e}")
            st.stop()

        try:
            supabase.table("sightings").insert(
                {
                    "user_id": user_id,
                    "product_id": product_id,
                    "store_id": store_choice,
                    "price": float(price),
                    "lat": float(lat),
                    "lon": float(lon),
                }
            ).execute()
            st.success("✅ Precio registrado. ¡Gracias por tu aporte!")
        except Exception as e:
            st.error(f"Error al registrar el precio: {e}")
            add_log("ERROR", f"Insert sighting: {e}")

# =========================
# PÁGINA LISTA DE PRECIOS
# =========================
elif page == "Lista de Precios":
    st.title("📋 Precios cercanos")

    if "lat" in st.query_params:
        st.session_state["lat_txt_lp"] = st.query_params["lat"]
    if "lon" in st.query_params:
        st.session_state["lon_txt_lp"] = st.query_params["lon"]

    col_lat, col_lon, col_unit, col_rad = st.columns([1, 1, 0.8, 1.2])
    lat_txt = col_lat.text_input("Latitud", key="lat_txt_lp", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", key="lon_txt_lp", placeholder="-62.2663")
    unit = col_unit.selectbox("Unidad de radio", ["Kilómetros", "Metros"], index=0, key="unit_lp")
    if unit == "Kilómetros":
        radius_value = col_rad.slider("Radio (km)", 1, 15, 5, key="rad_km_lp")
        radius_m = int(radius_value * 1000)
    else:
        radius_value = col_rad.slider("Radio (m)", 50, 500, 200, step=50, key="rad_m_lp")
        radius_m = int(radius_value)

    # Botón GPS
    if st.button("📍 Usar mi ubicación actual (GPS)", key="gps_lp"):
        set_location_from_gps("lat_txt_lp", "lon_txt_lp")

    st.subheader("Filtros y orden")
    filter_text = st.text_input("Filtrar producto", placeholder="Ej.: leche, yerba, arroz")
    order_by = st.radio("Ordenar por", ["Fecha (reciente)", "Precio ascendente", "Precio descendente"], horizontal=True)
    max_cards = st.number_input("Máximo de tarjetas a mostrar", min_value=10, max_value=200, value=50, step=10)

    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)

    try:
        if lat is not None and lon is not None:
            st.query_params.lat = str(lat)
            st.query_params.lon = str(lon)
    except Exception:
        pass

    if lat is None or lon is None:
        st.info("Ingresá latitud y longitud para ver precios cercanos (podés usar el botón 📍).")
        st.stop()

    try:
        stores = supabase.rpc(
            "nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_m) / 1000.0}
        ).execute().data or []
    except Exception as e:
        st.error(f"Error buscando locales cercanos: {e}")
        add_log("ERROR", f"nearby_stores: {e}")
        st.stop()

    if not stores:
        st.info("No hay locales cerca aún.")
        st.stop()

    store_ids = [s["id"] for s in stores]
    sightings = supabase.table("sightings").select(
        "id, product_id, store_id, price, created_at, is_validated"
    ).in_("store_id", store_ids).execute().data

    if not sightings:
        st.info("Aún no hay precios cargados en estos locales.")
        st.stop()

    product_ids = list({s["product_id"] for s in sightings})
    products = supabase.table("products").select("id, name, currency").in_("id", product_ids).execute().data
    prod_map = {p["id"]: {"name": p["name"], "currency": p["currency"]} for p in products}
    store_map = {s["id"]: s for s in stores}

    grouped = defaultdict(list)
    for s in sightings:
        grouped[(s["product_id"], s["store_id"])].append(s)

    entries = []
    for (pid, sid), items in grouped.items():
        items_sorted = sorted(items, key=lambda x: x["created_at"], reverse=True)
        latest = items_sorted[0]
        count = len(items)
        label = confidence_label(count)
        css_class = confidence_class(count)
        prod = prod_map.get(pid, {"name": f"producto {pid}", "currency": "ARS"})
        store = store_map.get(sid, {"name": f"Local {sid}", "meters": None})
        display_name = prettify_product(prod["name"])
        meters_str = f"{int(store['meters'])} m" if store.get("meters") is not None else ""
        entries.append({
            "pid": pid, "sid": sid, "display_name": display_name, "raw_name": prod["name"],
            "currency": prod["currency"], "store_name": store["name"], "meters_str": meters_str,
            "latest_price": latest["price"], "latest_date": latest["created_at"],
            "count": count, "label": label, "css_class": css_class,
        })

    if filter_text:
        ft_norm = normalize_product(filter_text)
        ft_lower = filter_text.strip().lower()
        entries = [e for e in entries if (ft_norm in e["raw_name"]) or (ft_lower in e["display_name"].lower())]

    if order_by == "Fecha (reciente)":
        entries.sort(key=lambda e: e["latest_date"], reverse=True)
    elif order_by == "Precio ascendente":
        entries.sort(key=lambda e: (e["currency"], float(e["latest_price"])))
    else:
        entries.sort(key=lambda e: (e["currency"], float(e["latest_price"])), reverse=True)

    entries = entries[:max_cards]
    if not entries:
        st.info("No hay resultados con los filtros actuales.")
    else:
        for e in entries:
            st.markdown(
                f"""
                ###### {e['display_name']} — {e['store_name']} {e['meters_str']}
                Precio: {e['latest_price']} {e['currency']}  
                <span class="confidence-tag {e['css_class']}">{e['label']}</span><br/>
                Última actualización: {e['latest_date']}
                """,
                unsafe_allow_html=True,
            )

# =========================
# NUEVA PÁGINA: LOCALES
# =========================
elif page == "Locales":
    if not require_auth():
        st.stop()

    st.title("🧾 Locales (supermercados) cargados")

    if "lat" in st.query_params:
        st.session_state["lat_txt_loc"] = st.query_params["lat"]
    if "lon" in st.query_params:
        st.session_state["lon_txt_loc"] = st.query_params["lon"]

    col_lat, col_lon, col_unit, col_rad = st.columns([1, 1, 0.8, 1.2])
    lat_txt = col_lat.text_input("Latitud", key="lat_txt_loc", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", key="lon_txt_loc", placeholder="-62.2663")
    unit = col_unit.selectbox("Unidad de radio", ["Kilómetros", "Metros"], index=0, key="unit_loc")
    if unit == "Kilómetros":
        radius_value = col_rad.slider("Radio (km)", 1, 15, 5, key="rad_km_loc")
        radius_m = int(radius_value * 1000)
    else:
        radius_value = col_rad.slider("Radio (m)", 50, 500, 200, step=50, key="rad_m_loc")
        radius_m = int(radius_value)

    if st.button("📍 Usar mi ubicación actual (GPS)", key="gps_loc"):
        set_location_from_gps("lat_txt_loc", "lon_txt_loc")

    # Filtros para lista (DB)
    st.subheader("Filtrar y ordenar")
    f_name = st.text_input("Nombre / Dirección contiene…", key="f_name")
    order = st.radio("Ordenar por", ["Distancia", "Nombre"], horizontal=True)

    # Bloque 1: locales (DB) cercanos
    st.markdown("### Locales en la base (cercanos)")
    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)
    if lat is None or lon is None:
        st.info("Definí lat/lon para ver locales cercanos.")
    else:
        try:
            rows = supabase.rpc(
                "nearby_stores",
                {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_m) / 1000.0}
            ).execute().data or []
        except Exception as e:
            rows = []
            st.warning(f"No se pudo consultar locales cercanos: {e}")

        if f_name:
            term = f_name.strip().lower()
            rows = [r for r in rows if term in (r.get("name","") or "").lower() or term in (r.get("address","") or "").lower()]

        if order == "Nombre":
            rows.sort(key=lambda r: (r.get("name","") or "").lower())
        else:
            rows.sort(key=lambda r: float(r.get("meters") or 0.0))

        if not rows:
            st.info("No hay locales cercanos en tu DB dentro del radio.")
        else:
            for r in rows:
                meters = int(r.get("meters") or 0)
                st.write(f"• **{r['name']}** — {r.get('address','')}  — {meters} m (id={r['id']})")

    st.divider()

    # Bloque 2: Sugerencias externas (Google/OSM)
    st.markdown("### Sugerencias externas (Google/OSM) para importar")
    OSM_CATEGORIES = {
        "Supermercados": ("shop", "supermarket"),
        "Almacenes": ("shop", "convenience"),
        "Farmacias": ("amenity", "pharmacy"),
        "Verdulerías": ("shop", "greengrocer"),
        "Panaderías": ("shop", "bakery"),
        "Kioscos": ("shop", "kiosk"),
    }
    kw = st.text_input("Filtro (Google) opcional, ej.: 'supermercado'", key="kw_loc")
    t = st.text_input("Tipo (Google) opcional, ej.: 'supermarket'", key="type_loc")
    osm_choice = st.selectbox("Categoría OSM", list(OSM_CATEGORIES.keys()))

    if st.button("Buscar sugerencias cercanas"):
        if lat is None or lon is None:
            st.error("Definí lat/lon primero.")
        else:
            places_ext = places_nearby_google(lat, lon, radius_m, keyword=kw or None, place_type=t or None)
            if not places_ext:
                key, value = OSM_CATEGORIES[osm_choice]
                places_ext = places_nearby_osm(lat, lon, radius_m, key=key, value=value)

            if not places_ext:
                st.info("No se encontraron sugerencias externas.")
            else:
                for idx, pl in enumerate(places_ext, start=1):
                    st.write(f"{idx}. **{pl['name']}** — {pl['address']}")
                    if st.button(f"Importar #{idx} a la DB", key=f"import_ext_{idx}"):
                        try:
                            ins = supabase.rpc("insert_store", {
                                "p_name": pl["name"], "p_address": pl["address"],
                                "p_lat": float(pl["lat"]), "p_lon": float(pl["lon"])
                            }).execute()
                            st.success("Local importado a la DB.")
                        except Exception as e:
                            st.error(f"No se pudo importar: {e}")

# =========================
# PÁGINA ALERTAS
# =========================
elif page == "Alertas":
    if not require_auth():
        st.stop()

    st.title("🔔 Alertas de precio")

    st.subheader("Crear alerta")
    product_name_input = st.text_input("Producto")
    target_price = st.number_input("Alertarme si el precio es menor o igual a…", min_value=0.0, step=0.01, format="%.2f")
    radius_km = st.slider("Radio de alerta (km)", 1, 20, 5)

    if st.button("Activar alerta"):
        try:
            product_name = normalize_product(product_name_input)
            pid_res = supabase.rpc("upsert_product", {"p_name": product_name, "p_currency": "ARS"}).execute()
            product_id = pid_res.data[0]["id"] if pid_res.data else None
            if not product_id:
                raise RuntimeError("upsert_product no devolvió id")

            supabase.table("alerts").insert(
                {
                    "user_id": get_user_id(),
                    "product_id": product_id,
                    "target_price": float(target_price) if target_price else None,
                    "radius_km": float(radius_km),
                    "active": True,
                }
            ).execute()
            st.success("✅ Alerta creada.")
        except Exception as e:
            st.error(f"No pudimos crear la alerta: {e}")

    st.subheader("Mis notificaciones")
    user_id = get_user_id()
    try:
        notes = supabase.table("notifications").select("id, alert_id, sighting_id, created_at").eq("user_id", user_id).order("created_at", desc=True).execute().data
        if not notes:
            st.info("Todavía no hay notificaciones.")
        else:
            for n in notes:
                st.write(f"🔔 Notificación #{n['id']} — avistamiento {n['sighting_id']} — {n['created_at']}")
    except Exception as e:
        st.error(f"Error al cargar notificaciones: {e}")

    st.divider()
    st.subheader("Notificaciones en tiempo real (polling cada 5s)")

    @st.fragment(run_every="5s")
    def notif_fragment():
        try:
            last_id = st.session_state.get("last_notif_id", 0)
            q = supabase.table("notifications").select("id, sighting_id, created_at").eq("user_id", user_id)
            if last_id > 0:
                q = q.gt("id", last_id)
            rows = q.order("id", desc=False).limit(50).execute().data or []
            for r in rows:
                nid = r["id"]
                sid = r["sighting_id"]
                created = r["created_at"]
                st.toast(f"🔔 Nueva notificación #{nid} — avistamiento {sid} — {created}", icon="🔔")
                if nid > st.session_state["last_notif_id"]:
                    st.session_state["last_notif_id"] = nid
            if not rows:
                st.caption("Sin notificaciones nuevas por el momento.")
        except Exception as e:
            st.warning(f"No se pudo consultar notificaciones: {e}")

    if st.session_state.notif_auto:
        notif_fragment()
    else:
        st.info("⏸️ Auto-actualización pausada. Podés reanudarla cuando quieras.")

    cols_rt = st.columns(3)
    with cols_rt[0]:
        if st.button("Actualizar ahora"):
            st.rerun()
    with cols_rt[1]:
        if st.session_state.notif_auto and st.button("Pausar auto-actualización"):
            st.session_state.notif_auto = False
            st.success("⏸️ Auto-actualización pausada.")
    with cols_rt[2]:
        if (not st.session_state.notif_auto) and st.button("Reanudar auto-actualización"):
            st.session_state.notif_auto = True
            st.success("▶️ Auto-actualización reanudada.")

# =========================
# PÁGINA ADMIN (Settings)
# =========================
elif page == "Admin":
    if not require_auth():
        st.stop()
    if not is_admin():
        st.error("No tenés permisos de administrador.")
        st.stop()

    st.title("⚙️ Panel de configuración (Settings)")

    try:
        rows = supabase.table("settings").select("*").eq("id", 1).execute().data
        if not rows:
            st.warning("No existe la fila de settings (id=1). Ejecutá settings_schema.sql.")
            st.stop()
        current = rows[0]
    except Exception as e:
        st.error(f"No se pudo leer settings: {e}")
        st.stop()

    col1, col2, col3 = st.columns(3)
    with col1:
        tol_pct = st.number_input(
            "Tolerancia precio (±%)", min_value=0.0, max_value=100.0,
            value=float(current["validation_price_tolerance_pct"] * 100.0), step=0.1
        )
    with col2:
        win_days = st.number_input(
            "Ventana (días)", min_value=1, max_value=90,
            value=int(current["validation_window_days"]), step=1
        )
    with col3:
        min_matches = st.number_input(
            "Mín. coincidencias", min_value=1, max_value=20,
            value=int(current["validation_min_matches"]), step=1
        )

    st.caption("Para actualizar se requiere permiso de administrador (tabla public.admins).")
    if st.button("Actualizar parámetros"):
        try:
            supabase.rpc(
                "update_settings",
                {"p_tolerance": float(tol_pct) / 100.0, "p_window_days": int(win_days), "p_min_matches": int(min_matches)},
            ).execute()
            st.success("✅ Parámetros actualizados.")
        except Exception as e:
            st.error(f"No pudimos actualizar los parámetros: {e}")
            st.info("Verificá que tu user_id esté en la tabla public.admins.")