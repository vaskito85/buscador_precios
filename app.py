
# app.py
import time
from typing import List, Dict
from collections import defaultdict

import streamlit as st
from utils.supabase_client import get_supabase
from utils.helpers import (
    normalize_product,
    prettify_product,
    parse_coord,
    confidence_label,
    confidence_class,
)

# =========================
# Geolocalización embebida (HTML + JS)
# =========================
# 👉 Este HTML NO recarga la página: actualiza directamente los inputs "Latitud" y "Longitud"
#    y dispara un evento 'input' para que Streamlit haga rerun SIN perder la sesión.
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
  const btn = document.getElementById('geo-btn');
  const statusEl = document.getElementById('geo-status');

  function setStatus(msg, color='#888') {
    statusEl.textContent = msg;
    statusEl.style.color = color;
  }

  function setInputValue(label, value) {
    try {
      const selector = `input[aria-label="${label}"]`;
      const el = document.querySelector(selector);
      if (!el) {
        setStatus(`No se encontró el campo: ${label}`, '#d9534f');
        return;
      }
      el.value = value;
      // Disparar evento 'input' para que Streamlit capte el cambio y haga rerun
      const evt = new Event('input', { bubbles: true });
      el.dispatchEvent(evt);
    } catch (e) {
      console.error(e);
      setStatus('Error escribiendo en los campos', '#d9534f');
    }
  }

  function onSuccess(pos) {
    const { latitude, longitude } = pos.coords;
    const lat = Number(latitude.toFixed(6));
    const lon = Number(longitude.toFixed(6));
    setStatus(`Lat: ${lat}, Lon: ${lon} (OK)`, '#4CAF50');
    // 👉 Escribir directamente en los inputs de Streamlit (sin recargar)
    setInputValue("Latitud", String(lat));
    setInputValue("Longitud", String(lon));
  }

  function onError(err) {
    console.warn(err);
    switch(err.code){
      case err.PERMISSION_DENIED:
        setStatus('Permiso denegado. Habilitá el acceso a ubicación.', '#d9534f'); break;
      case err.POSITION_UNAVAILABLE:
        setStatus('Posición no disponible.', '#d9534f'); break;
      case err.TIMEOUT:
        setStatus('Tiempo excedido obteniendo la ubicación.', '#d9534f'); break;
      default:
        setStatus('Error de geolocalización.', '#d9534f');
    }
  }

  btn.addEventListener('click', function(){
    setStatus('Obteniendo ubicación…');
    if (!navigator.geolocation) {
      setStatus('Geolocalización no soportada por el navegador.', '#d9534f');
      return;
    }
    navigator.geolocation.getCurrentPosition(onSuccess, onError, {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 0
    });
  });
})();
</script>
"""

# =========================
# Configuración general
# =========================
st.set_page_config(page_title="Precios Cercanos", layout="wide")

# Cargar CSS externo (styles.css)
try:
    with open("styles.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("styles.css no encontrado. Asegurate de subirlo al repositorio con ese nombre.")

# Conexión a Supabase
supabase = get_supabase()

# =========================
# Estado de sesión (inicial)
# =========================
st.session_state.setdefault("session", None)
st.session_state.setdefault("user_email", None)
st.session_state.setdefault("auth_msg", None)

# Navegación (fuente de verdad)
SECCIONES = ["Login", "Cargar Precio", "Lista de Precios", "Alertas", "Admin"]
st.session_state.setdefault("nav", "Login")

# Realtime (polling local)
st.session_state.setdefault("notif_auto", True)
st.session_state.setdefault("last_notif_id", 0)  # último id procesado (para polling)
st.session_state.setdefault("logs", [])
st.session_state.setdefault("otp_last_send", 0.0)

# =========================
# Mini logging (sidebar)
# =========================
def add_log(level: str, msg: str):
    st.session_state.logs.append(
        {"level": level, "msg": msg, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    )

st.sidebar.checkbox("🧪 Modo debug", key="debug", value=False)
if st.session_state.debug and st.session_state.logs:
    with st.sidebar.expander("Logs recientes", expanded=False):
        for entry in reversed(st.session_state.logs[-20:]):
            st.write(f"[{entry['ts']}] {entry['level']}: {entry['msg']}")

# =========================
# Helpers de sesión/seguridad
# =========================
def get_user_id():
    sess = st.session_state.get("session")
    return getattr(getattr(sess, "user", None), "id", None)

def require_auth() -> bool:
    """Verifica sesión y user_id. Si no hay, redirige a Login y muestra mensaje."""
    user_id = get_user_id()
    if not (st.session_state.session and user_id):
        st.session_state.auth_msg = "Tu sesión no está activa. Iniciá sesión para continuar."
        st.session_state.nav = "Login"
        st.rerun()
        return False
    return True

# =========================
# Sidebar + navegación
# =========================
st.sidebar.title("🧭 Navegación")
page = st.sidebar.radio("Secciones", SECCIONES, index=SECCIONES.index(st.session_state["nav"]))

if st.session_state.session:
    st.sidebar.success(f"Conectado: {st.session_state.user_email}")

if st.sidebar.button("Cerrar sesión"):
    try:
        supabase.auth.sign_out()
        add_log("INFO", "Sign out OK")
    except Exception as e:
        add_log("ERROR", f"Sign out: {e}")
    st.session_state.session = None
    st.session_state.user_email = None
    st.session_state.nav = "Login"
    st.rerun()

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

    st.write(
        "Ingresá tu email. Te enviaremos un **código OTP de 6 dígitos** por correo. "
        "Pegalo aquí para iniciar sesión."
    )

    col_email, col_otp = st.columns(2)
    email = col_email.text_input("Email", placeholder="tu@correo.com")
    otp = col_otp.text_input("Código OTP", placeholder="123456")

    COOLDOWN_SEC = 60
    now = time.time()
    elapsed = now - st.session_state.otp_last_send
    cooldown_active = elapsed < COOLDOWN_SEC
    remaining = max(0, int(COOLDOWN_SEC - elapsed))

    btn_col = st.columns(2)
    with btn_col[0]:
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
                        st.info("✅ Código enviado. Revisá tu email y pegalo en el campo de la derecha.")
                        add_log("INFO", f"OTP enviado a {email}")
                    except Exception as e:
                        st.error(f"No pudimos enviar el OTP: {e}")
                        add_log("ERROR", f"Enviar OTP: {e}")

    with btn_col[1]:
        if st.button("Validar código"):
            try:
                session = supabase.auth.verify_otp({"email": email, "token": otp, "type": "email"})
                st.session_state.session = session
                st.session_state.user_email = email
                st.success("¡Listo! Sesión iniciada.")
                add_log("INFO", f"Login OK: {email}")
                st.session_state["nav"] = "Cargar Precio"
                st.rerun()
            except Exception as e:
                st.error(f"No pudimos validar el código: {e}")
                add_log("ERROR", f"Validar OTP: {e}")

    if st.session_state.session:
        st.caption(f"Conectado como: {st.session_state.user_email}")

# =========================
# PÁGINA CARGAR PRECIO
# =========================
elif page == "Cargar Precio":
    if not require_auth():
        st.stop()

    st.title("🛒 Registrar precio")

    # Prefill SIEMPRE desde query params (si existen)
    if "lat" in st.query_params:
        st.session_state["lat_txt"] = st.query_params["lat"]
    if "lon" in st.query_params:
        st.session_state["lon_txt"] = st.query_params["lon"]

    # Ubicación
    st.subheader("Tu ubicación")
    col_lat, col_lon, col_rad = st.columns([1, 1, 1])
    lat_txt = col_lat.text_input("Latitud", key="lat_txt", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", key="lon_txt", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio de búsqueda de locales (km)", 1, 15, 5)

    # Botón “Usar mi ubicación” (embebido, sin recarga)
    st.markdown("**Usar mi ubicación actual**")
    st.html(GEOLOCATION_HTML, unsafe_allow_javascript=True)

    # Parseo
    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)

    # 👉 Sin recarga: si ya tenemos lat/lon válidos, reflejamos en la URL (st.query_params)
    #    Esto NO reinicia la app y mantiene sesión.
    try:
        if lat is not None and lon is not None:
            st.query_params.lat = str(lat)
            st.query_params.lon = str(lon)
    except Exception:
        pass

    # Búsqueda de locales cercanos
    nearby_options: List[Dict] = []
    store_choice = None
    if lat is not None and lon is not None:
        try:
            res = supabase.rpc(
                "nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}
            ).execute()
            nearby_options = res.data or []
        except Exception as e:
            st.info("Aún no hay locales cercanos o hubo un error con la búsqueda.")
            add_log("ERROR", f"nearby_stores: {e}")

    st.subheader("Local")
    if nearby_options:
        labels = {s["id"]: f"{s['name']} ({int(s['meters'])} m)" for s in nearby_options}
        ids = list(labels.keys())
        selected_id = st.selectbox("Elegí un local cercano", ids, format_func=lambda x: labels[x])
        store_choice = selected_id
    else:
        st.info("No encontramos locales cerca de tu ubicación. Podés crear uno nuevo.")

    with st.expander("🧭 Crear local nuevo"):
        new_store_name = st.text_input("Nombre del local")
        new_store_address = st.text_input("Dirección (opcional)")
        if st.button("Guardar local"):
            if not new_store_name:
                st.error("Ingresá el nombre del local.")
            elif lat is None or lon is None:
                st.error("Definí latitud y longitud para crear el local (Usar mi ubicación o escribir manual).")
            else:
                try:
                    store_ins = supabase.table("stores").insert(
                        {"name": new_store_name, "address": new_store_address, "lat": float(lat), "lon": float(lon)}
                    ).execute()
                    store_choice = store_ins.data[0]["id"]
                    st.session_state["store_choice"] = store_choice
                    st.success("Local creado y seleccionado.")
                except Exception as e:
                    st.error(f"No se pudo crear el local: {e}")
                    add_log("ERROR", f"Insert store: {e}")

    st.subheader("Producto y precio")
    product_name_input = st.text_input("Nombre del producto")
    price = st.number_input("Precio", min_value=0.0, step=0.01, format="%.2f")
    currency = st.selectbox("Moneda", ["ARS", "USD", "EUR"])

    col_actions = st.columns(3)
    with col_actions[2]:
        if st.button("Limpiar selección"):
            for k in ("lat_txt", "lon_txt", "store_choice"):
                if k in st.session_state:
                    del st.session_state[k]
            try:
                st.query_params.clear()
            except Exception:
                pass
            st.success("Selección limpiada. Volvé a ingresar ubicación/local.")
            st.rerun()

    if st.button("Registrar precio"):
        if not product_name_input:
            st.error("Ingresá el nombre del producto.")
            st.stop()
        if not store_choice and "store_choice" in st.session_state:
            store_choice = st.session_state["store_choice"]
        if not store_choice:
            st.error("Seleccioná un local o creá uno nuevo.")
            st.stop()

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
                {"user_id": user_id, "product_id": product_id, "store_id": store_choice,
                 "price": float(price), "lat": float(lat), "lon": float(lon)}
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

    # Prefill SIEMPRE desde query params (si existen)
    if "lat" in st.query_params:
        st.session_state["lat_txt_lp"] = st.query_params["lat"]
    if "lon" in st.query_params:
        st.session_state["lon_txt_lp"] = st.query_params["lon"]

    col_lat, col_lon, col_rad = st.columns([1, 1, 1])
    lat_txt = col_lat.text_input("Latitud", key="lat_txt_lp", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", key="lon_txt_lp", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio (km)", 1, 15, 5)

    # Botón “Usar mi ubicación” (embebido, sin recarga)
    st.html(GEOLOCATION_HTML, unsafe_allow_javascript=True)

    # Filtros y orden
    st.subheader("Filtros y orden")
    filter_text = st.text_input("Filtrar producto", placeholder="Ej.: leche, yerba, arroz")
    order_by = st.radio("Ordenar por", ["Fecha (reciente)", "Precio ascendente", "Precio descendente"], horizontal=True)
    max_cards = st.number_input("Máximo de tarjetas a mostrar", min_value=10, max_value=200, value=50, step=10)

    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)

    # Sin recarga: reflejar en URL si hay lat/lon
    try:
        if lat is not None and lon is not None:
            st.query_params.lat = str(lat)
            st.query_params.lon = str(lon)
    except Exception:
        pass

    if lat is None or lon is None:
        st.info("Ingresá latitud y longitud para ver precios cercanos.")
        st.stop()

    try:
        stores = supabase.rpc(
            "nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}
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
        entries.append(
            {
                "pid": pid,
                "sid": sid,
                "display_name": display_name,
                "raw_name": prod["name"],
                "currency": prod["currency"],
                "store_name": store["name"],
                "meters_str": meters_str,
                "latest_price": latest["price"],
                "latest_date": latest["created_at"],
                "count": count,
                "label": label,
                "css_class": css_class,
            }
        )

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
##### {e['display_name']} — {e['store_name']} {e['meters_str']}

Precio: {e['latest_price']} {e['currency']}
<span class="confidence-tag {e['css_class']}">{e['label']}</span>
Última actualización: {e['latest_date']}
                """,
                unsafe_allow_html=True,
            )

# =========================
# PÁGINA ALERTAS (Polling cada 5s)
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
                {"user_id": get_user_id(), "product_id": product_id,
                 "target_price": float(target_price) if target_price else None,
                 "radius_km": float(radius_km), "active": True}
            ).execute()
            st.success("✅ Alerta creada. Te avisaremos cuando haya precios **validados** más baratos cerca.")
        except Exception as e:
            st.error(f"No pudimos crear la alerta: {e}")
            add_log("ERROR", f"Insert alert: {e}")

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
        add_log("ERROR", f"List notifications: {e}")

    st.divider()
    st.subheader("Notificaciones en tiempo real (polling cada 5s)")

    @st.fragment(run_every="5s")
    def notif_fragment():
        """Consulta periódicamente nuevas notificaciones y muestra toasts."""
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

