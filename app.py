
import streamlit as st
from utils.supabase_client import get_supabase
from typing import List, Dict

st.set_page_config(page_title="Precios Cercanos", layout="wide")

# Cargar CSS externo
try:
    with open("style.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("style.css no encontrado. Asegurate de subirlo al repositorio.")

supabase = get_supabase()

# Estado de sesión
if "session" not in st.session_state:
    st.session_state.session = None

# Sidebar para navegación
page = st.sidebar.radio("Navegación", ["Login", "Cargar Precio", "Lista de Precios", "Alertas"]) 

# ---------------- Página Login ----------------
if page == "Login":
    st.title("🔐 Login")
    st.write("Ingresá tu email para recibir un código (OTP) y acceder sin contraseña.")

    email = st.text_input("Email")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Enviar código (OTP)"):
            try:
                supabase.auth.sign_in_with_otp({"email": email})
                st.info("Te enviamos un código por email. Ingresalo para iniciar sesión.")
            except Exception as e:
                st.error(f"No pudimos enviar el código: {e}")
    with col2:
        otp = st.text_input("Código OTP", placeholder="123456")
        if st.button("Validar código"):
            try:
                session = supabase.auth.verify_otp({"email": email, "token": otp, "type": "email"})
                st.session_state.session = session
                st.success("¡Listo! Sesión iniciada.")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"No pudimos validar el código: {e}")

    if st.session_state.session:
        st.caption(f"Conectado como: {st.session_state.session.user.email}")

# ---------------- Página Cargar Precio ----------------
elif page == "Cargar Precio":
    st.title("🛒 Registrar precio")

    if not st.session_state.session:
        st.warning("Iniciá sesión primero en la sección Login.")
        st.stop()

    # Geolocalización (manual por ahora)
    st.subheader("Tu ubicación")
    col_lat, col_lon, col_rad = st.columns([1,1,1])
    lat = col_lat.text_input("Latitud", placeholder="-38.7183")
    lon = col_lon.text_input("Longitud", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio de búsqueda de locales (km)", 1, 15, 5)

    # Sugerir locales cercanos (RPC)
    nearby_options: List[Dict] = []
    store_choice = None
    if lat and lon:
        try:
            res = supabase.rpc("nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}).execute()
            nearby_options = res.data or []
        except Exception as e:
            st.info("Aún no hay locales cercanos o hubo un error con la búsqueda.")

    st.subheader("Local")
    if nearby_options:
        labels = {s['id']: f"{s['name']} ({int(s['meters'])} m)" for s in nearby_options}
        ids = list(labels.keys())
        selected_id = st.selectbox("Elegí un local cercano", ids, format_func=lambda x: labels[x])
        store_choice = selected_id
    else:
        st.info("No encontramos locales cerca de tu ubicación. Podés crear uno nuevo.")

    with st.expander("Crear local nuevo"):
        new_store_name = st.text_input("Nombre del local")
        new_store_address = st.text_input("Dirección (opcional)")
        if st.button("Guardar local"):
            try:
                store_ins = supabase.table("stores").insert({
                    "name": new_store_name,
                    "address": new_store_address,
                    "lat": float(lat) if lat else None,
                    "lon": float(lon) if lon else None
                }).execute()
                store_choice = store_ins.data[0]["id"]
                st.success("Local creado.")
            except Exception as e:
                st.error(f"No se pudo crear el local: {e}")

    st.subheader("Producto y precio")
    product_name = st.text_input("Nombre del producto")
    price = st.number_input("Precio", min_value=0.0, step=0.01, format="%.2f")
    currency = st.selectbox("Moneda", ["ARS", "USD", "EUR"])

    if st.button("Registrar precio"):
        try:
            # Upsert de producto por (name, currency)
            product_res = supabase.table("products").insert({
                "name": product_name,
                "currency": currency
            }).execute()
            # En Supabase, el upsert requiere on_conflict; según el cliente, podemos manejar duplicados con try-except.
            product_id = product_res.data[0]["id"]
        except Exception:
            # Buscar producto existente
            existing = supabase.table("products").select("id").eq("name", product_name).eq("currency", currency).limit(1).execute().data
            if existing:
                product_id = existing[0]["id"]
            else:
                st.error("No se pudo crear ni encontrar el producto.")
                st.stop()
        
        if not store_choice:
            st.error("Seleccioná un local o creá uno nuevo.")
            st.stop()

        try:
            sighting_res = supabase.table("sightings").insert({
                "user_id": st.session_state.session.user.id,
                "product_id": product_id,
                "store_id": store_choice,
                "price": float(price),
                "lat": float(lat),
                "lon": float(lon)
            }).execute()
            st.success("✅ Precio registrado. Gracias por tu aporte!")
        except Exception as e:
            st.error(f"Error al registrar el precio: {e}")

# ---------------- Página Lista de Precios ----------------
elif page == "Lista de Precios":
    st.title("📋 Precios cercanos")

    # Parámetros de ubicación
    col_lat, col_lon, col_rad = st.columns([1,1,1])
    lat = col_lat.text_input("Latitud", placeholder="-38.7183")
    lon = col_lon.text_input("Longitud", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio (km)", 1, 15, 5)

    if not (lat and lon):
        st.info("Ingresá latitud y longitud para ver precios cercanos.")
        st.stop()

    # 1) Obtener locales cercanos
    stores = []
    try:
        stores = supabase.rpc("nearby_stores", {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}).execute().data or []
    except Exception as e:
        st.error(f"Error buscando locales cercanos: {e}")
        st.stop()

    if not stores:
        st.info("No hay locales cerca aún.")
        st.stop()

    store_ids = [s['id'] for s in stores]

    # 2) Traer avistamientos de esos locales (últimos 14 días)
    sightings = supabase.table("sightings").select("id, product_id, store_id, price, created_at, is_validated").in_("store_id", store_ids).execute().data
    if not sightings:
        st.info("Aún no hay precios cargados en estos locales.")
        st.stop()

    # 3) Traer nombres de productos y locales para mapear
    product_ids = list({s['product_id'] for s in sightings})
    products = supabase.table("products").select("id, name, currency").in_("id", product_ids).execute().data
    prod_map = {p['id']: {"name": p['name'], "currency": p['currency']} for p in products}
    store_map = {s['id']: s for s in stores}

    # 4) Agrupar por (product_id, store_id) y contar reportes -> color
    from collections import defaultdict
    grouped = defaultdict(list)
    for s in sightings:
        grouped[(s['product_id'], s['store_id'])].append(s)

    def confidence_color(count: int) -> str:
        if count == 1: return "red"
        if 2 <= count <= 3: return "orange"  # amarillo
        return "green"

    def confidence_label(count: int) -> str:
        if count == 1:
            return "Reportado por 1 persona (puede variar)"
        if 2 <= count <= 3:
            return f"Confirmado por {count} personas (confianza media)"
        return f"Confirmado por {count} personas (alta confianza)"

    # 5) Mostrar
    for (pid, sid), items in grouped.items():
        # Último precio registrado
        items_sorted = sorted(items, key=lambda x: x['created_at'], reverse=True)
        latest = items_sorted[0]
        count = len(items)
        color = confidence_color(count)
        label = confidence_label(count)
        prod = prod_map.get(pid, {"name": f"Producto {pid}", "currency": "ARS"})
        store = store_map.get(sid, {"name": f"Local {sid}", "meters": None})

        # Bloque visual
        st.markdown(f"""
        <div style='padding:10px; border:1px solid #eee; border-radius:8px; margin-bottom:10px;'>
            <h4 style='margin:0 0 6px 0'>{prod['name']} — {store['name']}</h4>
            <div style='font-size:18px;'>Precio: <strong>{latest['price']} {prod['currency']}</strong></div>
            <div class='confidence-tag confidence-{'red' if color=='red' else ('yellow' if color=='orange' else 'green')}'>{label}</div>
            <div style='font-size:12px; color:#666; margin-top:4px;'>Última actualización: {latest['created_at']}</div>
        </div>
        """, unsafe_allow_html=True)

# ---------------- Página Alertas ----------------
elif page == "Alertas":
    st.title("🔔 Alertas de precio")

    if not st.session_state.session:
        st.warning("Iniciá sesión primero en la sección Login.")
        st.stop()

    st.subheader("Crear alerta")
    product_name = st.text_input("Producto")
    target_price = st.number_input("Alertarme si el precio es menor o igual a…", min_value=0.0, step=0.01, format="%.2f")
    radius_km = st.slider("Radio de alerta (km)", 1, 20, 5)

    if st.button("Activar alerta"):
        try:
            # Buscar o crear producto
            prod_q = supabase.table("products").select("id, currency").eq("name", product_name).limit(1).execute().data
            if not prod_q:
                prod_ins = supabase.table("products").insert({"name": product_name, "currency": "ARS"}).execute()
                product_id = prod_ins.data[0]["id"]
            else:
                product_id = prod_q[0]["id"]

            supabase.table("alerts").insert({
                "user_id": st.session_state.session.user.id,
                "product_id": product_id,
                "target_price": float(target_price) if target_price else None,
                "radius_km": float(radius_km),
                "active": True
            }).execute()
            st.success("✅ Alerta creada. Te avisaremos en esta página cuando haya precios válidos más baratos cerca.")
        except Exception as e:
            st.error(f"No pudimos crear la alerta: {e}")

    st.subheader("Mis notificaciones")
    try:
        notes = supabase.table("notifications").select("id, alert_id, sighting_id, created_at").eq("user_id", st.session_state.session.user.id).order("created_at", desc=True).execute().data
        if not notes:
            st.info("Todavía no hay notificaciones.")
        else:
            for n in notes:
                st.write(f"🔔 Notificación #{n['id']} — avistamiento {n['sighting_id']} — {n['created_at']}")
    except Exception as e:
        st.error(f"Error al cargar notificaciones: {e}")
``
