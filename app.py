
# app.py
import time
import streamlit as st
import streamlit.components.v1 as components
from typing import List, Dict
from collections import defaultdict
from utils.supabase_client import get_supabase
from utils.helpers import (
    normalize_product, prettify_product, parse_coord,
    confidence_label, confidence_class
)

# =========================
# Configuración general
# =========================
st.set_page_config(page_title="Precios Cercanos", layout="wide")

# Cargar CSS externo (styles.css) correctamente
try:
    with open("styles.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("styles.css no encontrado. Asegurate de subirlo al repositorio con ese nombre.")

# Conexión a Supabase
supabase = get_supabase()

# Estado de sesión
st.session_state.setdefault("session", None)
st.session_state.setdefault("user_email", None)

# Estado para navegación programática (session-guard)
st.session_state.setdefault("nav", "Login")
st.session_state.setdefault("auth_msg", None)

# Estado para cooldown OTP y logging
st.session_state.setdefault("otp_last_send", 0.0)
st.session_state.setdefault("logs", [])

# Estado para Realtime
st.session_state.setdefault("rt_subscribed", False)
st.session_state.setdefault("rt_channel", None)
st.session_state.setdefault("rt_events", [])  # cola de eventos entrantes

# =========================
# Mini logging (sidebar)
# =========================
def add_log(level: str, msg: str):
    """Agregar un log simple en memoria."""
    st.session_state.logs.append({"level": level, "msg": msg, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})

st.sidebar.checkbox("🧪 Modo debug", key="debug", value=False)
if st.session_state.debug and st.session_state.logs:
    with st.sidebar.expander("Logs recientes", expanded=False):
        for entry in reversed(st.session_state.logs[-20:]):
            st.write(f"[{entry['ts']}] {entry['level']}: {entry['msg']}")

# =========================
# Otros helpers
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
page = st.sidebar.radio("Secciones", ["Login", "Cargar Precio", "Lista de Precios", "Alertas", "Admin"], key="nav")

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

# =========================
# PÁGINA LOGIN (OTP)
# =========================
if page == "Login":
    st.title("🔐 Login (OTP por email)")
    if st.session_state.auth_msg:
        st.info(st.session_state.auth_msg)
        st.session_state.auth_msg = None

    st.write("Ingresá tu email. Te enviaremos un **código OTP de 6 dígitos** por correo. Pegalo aquí para iniciar sesión.")
    email = st.text_input("Email", placeholder="tu@correo.com")

    # Cooldown OTP (60s)
    COOLDOWN_SEC = 60
    now = time.time()
    elapsed = now - st.session_state.otp_last_send
    cooldown_active = elapsed < COOLDOWN_SEC
    remaining = max(0, int(COOLDOWN_SEC - elapsed))

    col1, col2 = st.columns(2)
    with col1:
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

    with col2:
        otp = st.text_input("Código OTP", placeholder="123456")
        if st.button("Validar código"):
            try:
                session = supabase.auth.verify_otp({
                    "email": email,
                    "token": otp,
                    "type": "email"
                })
                st.session_state.session = session
                st.session_state.user_email = email
                st.success("¡Listo! Sesión iniciada.")
                add_log("INFO", f"Login OK: {email}")
                st.session_state.nav = "Cargar Precio"  # redirige a la siguiente sección útil
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

    # Ubicación (manual + botón de geolocalización)
    st.subheader("Tu ubicación")
    col_lat, col_lon, col_rad = st.columns([1, 1, 1])
    lat_txt = col_lat.text_input("Latitud", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio de búsqueda de locales (km)", 1, 15, 5)

    # Botón "Usar mi ubicación"
    try:
        components.html(open("components/geolocation.html", "r", encoding="utf-8").read(), height=80)
    except Exception:
        st.caption("Tip: agregá components/geolocation.html para usar el GPS del navegador.")

    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)
    nearby_options: List[Dict] = []
    store_choice = None

    if lat is not None and lon is not None:
        try:
            res = supabase.rpc("nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}).execute()
            nearby_options = res.data or []
        except Exception as e:
            st.info("Aún no hay locales cercanos o hubo un error con la búsqueda.")
            add_log("ERROR", f"nearby_stores: {e}")

    st.subheader("Local")
    if nearby_options:
        labels = {s['id']: f"{s['name']} ({int(s['meters'])} m)" for s in nearby_options}
        ids = list(labels.keys())
        selected_id = st.selectbox("Elegí un local cercano", ids, format_func=lambda x: labels[x])
        store_choice = selected_id
    else:
        st.info("No encontramos locales cerca de tu ubicación. Podés crear uno nuevo.")
        with st.expander("🧪 Crear local nuevo"):
            new_store_name = st.text_input("Nombre del local")
            new_store_address = st.text_input("Dirección (opcional)")
            if st.button("Guardar local"):
                if not new_store_name:
                    st.error("Ingresá el nombre del local.")
                elif lat is None or lon is None:
                    st.error("Definí latitud y longitud para crear el local.")
                else:
                    try:
                        store_ins = supabase.table("stores").insert({
                            "name": new_store_name,
                            "address": new_store_address,
                            "lat": float(lat),
                            "lon": float(lon)
                        }).execute()
                        store_choice = store_ins.data[0]["id"]
                        st.success("Local creado.")
                    except Exception as e:
                        st.error(f"No se pudo crear el local: {e}")
                        add_log("ERROR", f"Insert store: {e}")

    st.subheader("Producto y precio")
    product_name_input = st.text_input("Nombre del producto")
    price = st.number_input("Precio", min_value=0.0, step=0.01, format="%.2f")
    currency = st.selectbox("Moneda", ["ARS", "USD", "EUR"])

    if st.button("Registrar precio"):
        if not product_name_input:
            st.error("Ingresá el nombre del producto.")
            st.stop()
        if not store_choice:
            st.error("Seleccioná un local o creá uno nuevo.")
            st.stop()
        if lat is None or lon is None:
            st.error("Ingresá latitud y longitud válidas.")
            st.stop()

        user_id = get_user_id()
        if not user_id:
            st.error("Tu sesión expiró. Iniciá sesión nuevamente.")
            st.session_state.nav = "Login"
            st.rerun()

        # Normalizar nombre antes de guardar/buscar
        product_name = normalize_product(product_name_input)

        # Upsert atómico por RPC
        try:
            pid_res = supabase.rpc("upsert_product", {"p_name": product_name, "p_currency": currency}).execute()
            product_id = pid_res.data[0]["id"] if pid_res.data else None
            if not product_id:
                raise RuntimeError("upsert_product no devolvió id")
        except Exception as e:
            st.error(f"No se pudo crear/obtener el producto: {e}")
            add_log("ERROR", f"upsert_product: {e}")
            st.stop()

        # Insertar avistamiento
        try:
            supabase.table("sightings").insert({
                "user_id": user_id,
                "product_id": product_id,
                "store_id": store_choice,
                "price": float(price),
                "lat": float(lat),
                "lon": float(lon)
            }).execute()
            st.success("✅ Precio registrado. ¡Gracias por tu aporte!")
        except Exception as e:
            st.error(f"Error al registrar el precio: {e}")
            add_log("ERROR", f"Insert sighting: {e}")

# =========================
# PÁGINA LISTA DE PRECIOS
# =========================
elif page == "Lista de Precios":
    st.title("📋 Precios cercanos")
    col_lat, col_lon, col_rad = st.columns([1, 1, 1])
    lat_txt = col_lat.text_input("Latitud", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio (km)", 1, 15, 5)

    # Filtros y orden
    st.subheader("Filtros y orden")
    filter_text = st.text_input("Filtrar producto", placeholder="Ej.: leche, yerba, arroz")
    order_by = st.radio("Ordenar por", ["Fecha (reciente)", "Precio ascendente", "Precio descendente"], horizontal=True)
    max_cards = st.number_input("Máximo de tarjetas a mostrar", min_value=10, max_value=200, value=50, step=10)

    # Botón "Usar mi ubicación"
    try:
        components.html(open("components/geolocation.html", "r", encoding="utf-8").read(), height=80)
    except Exception:
        st.caption("Tip: agregá components/geolocation.html para usar el GPS del navegador.")

    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)
    if lat is None or lon is None:
        st.info("Ingresá latitud y longitud para ver precios cercanos.")
        st.stop()

    # 1) Locales cercanos
    try:
        stores = supabase.rpc("nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}).execute().data or []
    except Exception as e:
        st.error(f"Error buscando locales cercanos: {e}")
        add_log("ERROR", f"nearby_stores: {e}")
        st.stop()

    if not stores:
        st.info("No hay locales cerca aún.")
        st.stop()

    store_ids = [s['id'] for s in stores]

    # 2) Avistamientos recientes en esos locales
    sightings = supabase.table("sightings").select(
        "id, product_id, store_id, price, created_at, is_validated"
    ).in_("store_id", store_ids).execute().data

    if not sightings:
        st.info("Aún no hay precios cargados en estos locales.")
        st.stop()

    # 3) Mapear productos y locales
    product_ids = list({s['product_id'] for s in sightings})
    products = supabase.table("products").select("id, name, currency").in_("id", product_ids).execute().data
    prod_map = {p['id']: {"name": p['name'], "currency": p['currency']} for p in products}
    store_map = {s['id']: s for s in stores}

    # 4) Agrupar por (product_id, store_id)
    grouped = defaultdict(list)
    for s in sightings:
        grouped[(s['product_id'], s['store_id'])].append(s)

    # 5) Preparar entradas
    entries = []
    for (pid, sid), items in grouped.items():
        items_sorted = sorted(items, key=lambda x: x['created_at'], reverse=True)
        latest = items_sorted[0]
        count = len(items)
        label = confidence_label(count)
        css_class = confidence_class(count)

        prod = prod_map.get(pid, {"name": f"producto {pid}", "currency": "ARS"})
        store = store_map.get(sid, {"name": f"Local {sid}", "meters": None})

        display_name = prettify_product(prod['name'])
        meters_str = f"{int(store['meters'])} m" if store.get("meters") is not None else ""

        entries.append({
            "pid": pid, "sid": sid,
            "display_name": display_name,
            "raw_name": prod['name'],
            "currency": prod['currency'],
            "store_name": store['name'],
            "meters_str": meters_str,
            "latest_price": latest['price'],
            "latest_date": latest['created_at'],
            "count": count,
            "label": label,
            "css_class": css_class
        })

    # 6) Filtro por producto
    if filter_text:
        ft_norm = normalize_product(filter_text)
        ft_lower = filter_text.strip().lower()
        entries = [e for e in entries if (ft_norm in e["raw_name"]) or (ft_lower in e["display_name"].lower())]

    # 7) Orden
    if order_by == "Fecha (reciente)":
        entries.sort(key=lambda e: e["latest_date"], reverse=True)
    elif order_by == "Precio ascendente":
        entries.sort(key=lambda e: (e["currency"], float(e["latest_price"])))
    else:  # "Precio descendente"
        entries.sort(key=lambda e: (e["currency"], float(e["latest_price"])), reverse=True)

    # 8) Límite
    entries = entries[:max_cards]

    # 9) Render
    if not entries:
        st.info("No hay resultados con los filtros actuales.")
    else:
        for e in entries:
            st.markdown(f"""
            <div class="block">
              <h4>{e['display_name']} — {e['store_name']} {e['meters_str']}</h4>
              <div>Precio: <strong>{e['latest_price']}</strong> {e['currency']}</div>
              <span class="confidence-tag {e['css_class']}">{e['label']}</span><br/>
              <span class="small-muted">Última actualización: {e['latest_date']}</span>
            </div>
            """, unsafe_allow_html=True)

# =========================
# PÁGINA ALERTAS (Realtime)
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

            supabase.table("alerts").insert({
                "user_id": get_user_id(),
                "product_id": product_id,
                "target_price": float(target_price) if target_price else None,
                "radius_km": float(radius_km),
                "active": True
            }).execute()

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
    st.subheader("Notificaciones en tiempo real")
    def subscribe_notifications(uid: str):
        if st.session_state.rt_subscribed:
            return
        try:
            ch = supabase.channel(f"notifications_user_{uid}")
            ch.on(
                "postgres_changes",
                {"event": "INSERT", "schema": "public", "table": "notifications", "filter": f"user_id=eq.{uid}"},
                lambda payload: st.session_state.rt_events.append(payload)
            )
            ch.subscribe()
            st.session_state.rt_channel = ch
            st.session_state.rt_subscribed = True
            st.success("🔴 Suscripción en vivo activa. Te avisaremos cuando llegue una nueva notificación.")
            add_log("INFO", "Realtime subscribed")
        except Exception as e:
            st.warning("No pudimos establecer la suscripción en vivo. Usaremos actualización automática cada 5 segundos.")
            add_log("ERROR", f"Realtime subscribe: {e}")

    subscribe_notifications(user_id)
    
# =====================
# Auto-actualización con fragments (cada 5s)
# =====================
st.session_state.setdefault("notif_auto", True)

@st.fragment(run_every="5s")
def notif_fragment():
    """Procesa eventos de notificaciones en tiempo real y muestra toasts."""
    processed = 0
    while st.session_state.rt_events:
        payload = st.session_state.rt_events.pop(0)
        new_row = payload.get("new", {}) if isinstance(payload, dict) else {}
        nid = new_row.get("id")
        sid = new_row.get("sighting_id")
        created = new_row.get("created_at")
        st.toast(f"🔔 Nueva notificación #{nid} — avistamiento {sid} — {created}", icon="🔔")
        processed += 1
    if processed == 0:
        st.caption("Sin notificaciones nuevas por el momento.")

# Muestra el fragmento solo si la auto-actualización está activa
if st.session_state.notif_auto:
    notif_fragment()
else:
    st.info("⏸️ Auto-actualización pausada. Podés reanudarla cuando quieras.")

# Controles
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

# Botón adicional para detener la suscripción en vivo a Supabase (Realtime)
cols_stop = st.columns(2)
if cols_stop[0].button("Detener suscripción en vivo"):
    try:
        if st.session_state.rt_channel:
            st.session_state.rt_channel.unsubscribe()
        st.session_state.rt_subscribed = False
        st.session_state.rt_channel = None
        st.success("⏹️ Suscripción en vivo detenida.")
    except Exception as e:
        st.error(f"No pudimos detener la suscripción: {e}")
elif page == "Admin":
    if not require_auth():
        st.stop()

    st.title("⚙️ Panel de configuración (Settings)")

    # Mostrar valores actuales
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
        tol_pct = st.number_input("Tolerancia precio (±%)", min_value=0.0, max_value=100.0, value=float(current["validation_price_tolerance_pct"]*100.0), step=0.1)
    with col2:
        win_days = st.number_input("Ventana (días)", min_value=1, max_value=90, value=int(current["validation_window_days"]), step=1)
    with col3:
        min_matches = st.number_input("Mín. coincidencias", min_value=1, max_value=20, value=int(current["validation_min_matches"]), step=1)

    st.caption("Para actualizar se requiere permiso de administrador (tabla public.admins).")

    if st.button("Actualizar parámetros"):
        try:
            # RPC con chequeo de administrador en backend
            uid = get_user_id()
            res = supabase.rpc("update_settings", {
                "p_tolerance": float(tol_pct) / 100.0,
                "p_window_days": int(win_days),
                "p_min_matches": int(min_matches)
            }).execute()
            st.success("✅ Parámetros actualizados.")
        except Exception as e:
            st.error(f"No pudimos actualizar los parámetros: {e}")
            st.info("Verificá que tu user_id esté en la tabla public.admins.")
``
