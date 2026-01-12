
# app.py
import time
from typing import List, Dict
from collections import defaultdict

import streamlit as st
import streamlit.components.v1 as components

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
# Geolocalización HTML+JS (embebido)
# =========================
GEOLOCATION_HTML = """
<div style="margin: 8px 0;">
  <button id="geo-btn" style="
    background:#4CAF50;color:#fff;border:none;border-radius:8px;
    padding:10px 16px;font-size:16px;cursor:pointer;">
    📍 Usar mi ubicación actual
  </button>
  <span id="geo-status" style="margin-left:10px;color:#888;font-size:14px;"></span>
</div>
<script>
(function(){
  const statusEl = document.getElementById('geo-status');
  const btn = document.getElementById('geo-btn');

  function setStatus(msg, color='#888'){
    statusEl.textContent = msg;
    statusEl.style.color = color;
  }

  function setStreamlitInputs(lat, lon){
    try {
      const inputs = Array.from(parent.document.querySelectorAll('input'));
      const candidates = inputs.filter(el => {
        const lbl = (el.getAttribute('aria-label') || '').toLowerCase();
        const ph  = (el.getAttribute('placeholder') || '').toLowerCase();
        return lbl.includes('latitud') || lbl.includes('longitud') || ph.includes('latitud') || ph.includes('longitud');
      });
      let latInput = candidates.find(el => (el.getAttribute('aria-label')||'').toLowerCase().includes('latitud')) ||
                     candidates.find(el => (el.getAttribute('placeholder')||'').toLowerCase().includes('latitud'));
      let lonInput = candidates.find(el => (el.getAttribute('aria-label')||'').toLowerCase().includes('longitud')) ||
                     candidates.find(el => (el.getAttribute('placeholder')||'').toLowerCase().includes('longitud'));
      if (latInput) {
        latInput.value = String(lat);
        latInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (lonInput) {
        lonInput.value = String(lon);
        lonInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } catch(e) {
      console.warn('No se pudo setear inputs de Streamlit', e);
    }
  }

  function updateQueryParams(lat, lon){
    try {
      const url = new URL(parent.location.href);
      url.searchParams.set('lat', String(lat));
      url.searchParams.set('lon', String(lon));
      parent.history.replaceState({}, '', url.toString());
    } catch(e){
      console.warn('No se pudo actualizar la URL', e);
    }
  }

  function onSuccess(pos){
    const { latitude, longitude } = pos.coords;
    const lat = Number(latitude.toFixed(6));
    const lon = Number(longitude.toFixed(6));
    setStatus(`Lat: ${lat}, Lon: ${lon} (OK)`, '#4CAF50');
    setStreamlitInputs(lat, lon);
    updateQueryParams(lat, lon);
  }

  function onError(err){
    console.warn(err);
    switch(err.code){
      case err.PERMISSION_DENIED:
        setStatus('Permiso denegado. Habilitá acceso a ubicación.', '#d9534f'); break;
      case err.POSITION_UNAVAILABLE:
        setStatus('Posición no disponible.', '#d9534f'); break;
      case err.TIMEOUT:
        setStatus('Tiempo excedido obteniendo la ubicación.', '#d9534f'); break;
      default:
        setStatus('Error de geolocalización.', '#d9534f');
    }
  }

  function requestLocation(){
    setStatus('Obteniendo ubicación…');
    if (!navigator.geolocation){
      setStatus('Geolocalización no soportada por el navegador.', '#d9534f');
      return;
    }
    navigator.geolocation.getCurrentPosition(onSuccess, onError, {
      enableHighAccuracy: true, timeout: 10000, maximumAge: 0
    });
  }

  btn.addEventListener('click', requestLocation);
  const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (isMobile) {
    requestLocation();
  }
})();
</script>
"""

# =========================
# Configuración general
# =========================
st.set_page_config(page_title="Precios Cercanos", layout="wide")

try:
    with open("styles.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("styles.css no encontrado.")

supabase = get_supabase()

# Estado de sesión
st.session_state.setdefault("session", None)
st.session_state.setdefault("user_email", None)
st.session_state.setdefault("auth_msg", None)
st.session_state.setdefault("nav", "Login")
st.session_state.setdefault("notif_auto", True)
st.session_state.setdefault("last_notif_id", 0)
st.session_state.setdefault("logs", [])
st.session_state.setdefault("otp_last_send", 0.0)

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

# Sidebar
SECCIONES_BASE = ["Login", "Cargar Precio", "Lista de Precios", "Alertas"]
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

if is_admin():
    st.sidebar.checkbox("🧪 Modo debug", key="debug", value=False)
else:
    st.session_state["debug"] = False

if page != st.session_state["nav"]:
    st.session_state["nav"] = page

# =========================
# Página LOGIN
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
    else:
        if st.button("Enviar código (OTP)"):
            if not email or "@" not in email:
                st.error("Email inválido.")
            else:
                supabase.auth.sign_in_with_otp({"email": email})
                st.session_state.otp_last_send = time.time()
                st.info("✅ Código enviado. Revisá tu email.")

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
# Página CARGAR PRECIO
# =========================
elif page == "Cargar Precio":
    if not require_auth():
        st.stop()

    st.title("🛒 Registrar precio")
    col_lat, col_lon, col_unit, col_rad = st.columns([1, 1, 0.8, 1.2])
    lat_txt = col_lat.text_input("Latitud", key="lat_txt", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", key="lon_txt", placeholder="-62.2663")
    unit = col_unit.selectbox("Unidad de radio", ["Kilómetros", "Metros"], index=0)
    radius_value = col_rad.slider("Radio", 1 if unit == "Kilómetros" else 50, 15 if unit == "Kilómetros" else 500, 5 if unit == "Kilómetros" else 200, step=(1 if unit == "Kilómetros" else 50))
    radius_m = radius_value * (1000 if unit == "Kilómetros" else 1)

    components.html(GEOLOCATION_HTML, height=0)
    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)

    st.subheader("Local")
    with st.expander("🔍 Sugerencias cercanas"):
        if st.button("Buscar locales cercanos"):
            if lat is None or lon is None:
                st.error("Definí latitud/longitud.")
            else:
                g_places = places_nearby_google(lat, lon, radius_m) or places_nearby_osm(lat, lon, radius_m)
                if not g_places:
                    st.info("No se encontraron sugerencias.")
                else:
                    for idx, pl in enumerate(g_places, start=1):
                        st.write(f"{idx}. **{pl['name']}** — {pl['address']}")
                        if st.button(f"Agregar este local #{idx}", key=f"add_place_{idx}"):
                            ins = supabase.rpc("insert_store", {"p_name": pl["name"], "p_address": pl["address"], "p_lat": pl["lat"], "p_lon": pl["lon"]}).execute()
                            st.session_state["store_choice"] = ins.data[0]["id"]
                            st.success("Local agregado y seleccionado.")

    tabs = st.tabs(["📍 Por dirección", "➕ Manual"])
    with tabs[0]:
        new_store_name_a = st.text_input("Nombre del local")
        new_store_address_a = st.text_input("Dirección")
        if st.button("Buscar y guardar"):
            g_lat, g_lon = geocode_address_google(new_store_address_a) or geocode_address_osm(new_store_address_a)
            if g_lat and g_lon:
                ins = supabase.rpc("insert_store", {"p_name": new_store_name_a, "p_address": new_store_address_a, "p_lat": g_lat, "p_lon": g_lon}).execute()
                st.session_state["store_choice"] = ins.data[0]["id"]
                st.success("Local creado y seleccionado.")
            else:
                st.error("No se pudo geocodificar la dirección.")

    with tabs[1]:
        new_store_name = st.text_input("Nombre del local (manual)")
        lat_new = st.text_input("Latitud del local")
        lon_new = st.text_input("Longitud del local")
        if st.button("Guardar local manual"):
            lat_n = parse_coord(lat_new)
            lon_n = parse_coord(lon_new)
            if lat_n and lon_n:
                ins = supabase.rpc("insert_store", {"p_name": new_store_name, "p_address": "", "p_lat": lat_n, "p_lon": lon_n}).execute()
                st.session_state["store_choice"] = ins.data[0]["id"]
                st.success("Local creado y seleccionado.")
            else:
                st.error("Lat/Lon inválidos.")

    st.subheader("Producto y precio")
    product_name_input = st.text_input("Nombre del producto")
    price = st.number_input("Precio", min_value=0.0, step=0.01)
    currency = st.selectbox("Moneda", ["ARS", "USD", "EUR"])
    if st.button("Registrar precio"):
        product_name = normalize_product(product_name_input)
        pid_res = supabase.rpc("upsert_product", {"p_name": product_name, "p_currency": currency}).execute()
        product_id = pid_res.data[0]["id"]
        supabase.table("sightings").insert({"user_id": get_user_id(), "product_id": product_id, "store_id": st.session_state.get("store_choice"), "price": float(price), "lat": float(lat), "lon": float(lon)}).execute()
        st.success("✅ Precio registrado.")
