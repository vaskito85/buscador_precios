
# app.py
import re
import streamlit as st
import streamlit.components.v1 as components
from typing import List, Dict
from collections import defaultdict
from utils.supabase_client import get_supabase

# Configuración general
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

# -------------------- Helpers de normalización --------------------
UNITS_MAP = {
    "lt": "l",
    "l": "l",
    "kg": "kg",
    "gr": "g",
    "g": "g",
    "ml": "ml"
}
COMMON_WORDS_CAP = {"leche", "yerba", "arroz", "aceite", "azúcar", "fideos", "harina", "café", "te", "té"}

def normalize_product(name: str) -> str:
    """
    Genera una versión canónica del nombre de producto para guardar/buscar en DB.
    - minúsculas
    - trim
    - colapsa espacios
    - normaliza unidades y espacio entre número y unidad (e.g., "1L" -> "1 l", "500ml" -> "500 ml")
    - reemplaza 'lt' por 'l', 'gr' por 'g', etc.
    """
    if not name:
        return ""
    s = name.strip().lower()
    # colapsar espacios múltiples
    s = " ".join(s.split())

    # normalizar unidades pegadas a números: "1l", "500ml", "1kg", "250gr"
    s = re.sub(r"(\d+)\s*(lt|l|kg|gr|g|ml)\b", lambda m: f"{m.group(1)} {UNITS_MAP[m.group(2)]}", s)

    # colapsar por si quedaron dobles espacios
    s = " ".join(s.split())

    # normalizar tokens sueltos de unidades
    tokens = s.split()
    norm_tokens = []
    for t in tokens:
        if t in UNITS_MAP:
            norm_tokens.append(UNITS_MAP[t])
        else:
            norm_tokens.append(t)
    s = " ".join(norm_tokens)

    # remover puntuación común
    s = re.sub(r"[.,;:]+", "", s)

    return s

def prettify_product(name: str) -> str:
    """
    Mejora la presentación del nombre normalizado para UI:
    - Capitaliza la primera letra de palabras comunes
    - Mantiene unidades en minúscula
    """
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

# -------------------- Otros helpers --------------------
def parse_coord(txt: str):
    try:
        return float(txt)
    except:
        return None

def get_user_id():
    sess = st.session_state.get("session")
    return getattr(getattr(sess, "user", None), "id", None)

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

# Sidebar
st.sidebar.title("🧭 Navegación")
page = st.sidebar.radio("Secciones", ["Login", "Cargar Precio", "Lista de Precios", "Alertas"])

if st.session_state.session:
    st.sidebar.success(f"Conectado: {st.session_state.user_email}")
    if st.sidebar.button("Cerrar sesión"):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        st.session_state.session = None
        st.session_state.user_email = None
        st.rerun()

# -------------------- Página Login (OTP) --------------------
if page == "Login":
    st.title("🔐 Login (OTP por email)")
    st.write("Ingresá tu email. Te enviaremos un **código OTP de 6 dígitos** por correo. Pegalo aquí para iniciar sesión.")

    email = st.text_input("Email", placeholder="tu@correo.com")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Enviar código (OTP)"):
            if not email or "@" not in email:
                st.error("Email inválido.")
            else:
                try:
                    supabase.auth.sign_in_with_otp({"email": email})
                    st.info("✅ Código enviado. Revisá tu email y pegalo en el campo de la derecha.")
                except Exception as e:
                    st.error(f"No pudimos enviar el OTP: {e}")

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
                st.rerun()
            except Exception as e:
                st.error(f"No pudimos validar el código: {e}")

    if st.session_state.session:
        st.caption(f"Conectado como: {st.session_state.user_email}")

# -------------------- Página Cargar Precio --------------------
elif page == "Cargar Precio":
    st.title("🛒 Registrar precio")
    if not st.session_state.session:
        st.warning("Iniciá sesión primero en la sección Login.")
        st.stop()

    # Ubicación (manual + botón de geolocalización)
    st.subheader("Tu ubicación")
    col_lat, col_lon, col_rad = st.columns([1, 1, 1])
    lat_txt = col_lat.text_input("Latitud", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio de búsqueda de locales (km)", 1, 15, 5)

    # Botón "Usar mi ubicación"
    try:
        components.html(
            open("components/geolocation.html", "r", encoding="utf-8").read(),
            height=80
        )
    except Exception:
        st.caption("Tip: agregá components/geolocation.html para usar el GPS del navegador.")

    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)
    nearby_options: List[Dict] = []
    store_choice = None

    if lat is not None and lon is not None:
        try:
            res = supabase.rpc(
                "nearby_stores",
                {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}
            ).execute()
            nearby_options = res.data or []
        except Exception:
            st.info("Aún no hay locales cercanos o hubo un error con la búsqueda.")

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
            st.stop()

        # Normalizar nombre antes de guardar/buscar
        product_name = normalize_product(product_name_input)

        # Crear producto (optimista) o buscar por UNIQUE(name, currency)
        try:
            product_res = supabase.table("products").insert({
                "name": product_name,
                "currency": currency
            }).execute()
            product_id = product_res.data[0]["id"]
        except Exception:
            existing = (
                supabase.table("products")
                .select("id")
                .eq("name", product_name)
                .eq("currency", currency)
                .limit(1)
                .execute()
                .data
            )
            if existing:
                product_id = existing[0]["id"]
            else:
                st.error("No se pudo crear ni encontrar el producto.")
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

# -------------------- Página Lista de Precios --------------------
elif page == "Lista de Precios":
    st.title("📋 Precios cercanos")
    col_lat, col_lon, col_rad = st.columns([1, 1, 1])
    lat_txt = col_lat.text_input("Latitud", placeholder="-38.7183")
    lon_txt = col_lon.text_input("Longitud", placeholder="-62.2663")
    radius_km = col_rad.slider("Radio (km)", 1, 15, 5)

    # Controles UX nuevos: filtro, orden y límite
    st.subheader("Filtros y orden")
    filter_text = st.text_input("Filtrar producto", placeholder="Ej.: leche, yerba, arroz")
    order_by = st.radio(
        "Ordenar por",
        ["Fecha (reciente)", "Precio ascendente", "Precio descendente"],
        horizontal=True
    )
    max_cards = st.number_input("Máximo de tarjetas a mostrar", min_value=10, max_value=200, value=50, step=10)

    # Botón "Usar mi ubicación"
    try:
        components.html(
            open("components/geolocation.html", "r", encoding="utf-8").read(),
            height=80
        )
    except Exception:
        st.caption("Tip: agregá components/geolocation.html para usar el GPS del navegador.")

    lat = parse_coord(lat_txt)
    lon = parse_coord(lon_txt)
    if lat is None or lon is None:
        st.info("Ingresá latitud y longitud para ver precios cercanos.")
        st.stop()

    # 1) Locales cercanos
    try:
        stores = supabase.rpc(
            "nearby_stores",
            {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}
        ).execute().data or []
    except Exception as e:
        st.error(f"Error buscando locales cercanos: {e}")
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

    # 5) Preparar lista de entradas con agregados (latest, count, etc.)
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
            "pid": pid,
            "sid": sid,
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

    # 6) Filtro por producto (case-insensitive, usando nombre normalizado y prettify)
    if filter_text:
        ft_norm = normalize_product(filter_text)
        ft_lower = filter_text.strip().lower()
        entries = [
            e for e in entries
            if (ft_norm in e["raw_name"]) or (ft_lower in e["display_name"].lower())
        ]

    # 7) Orden
    if order_by == "Fecha (reciente)":
        entries.sort(key=lambda e: e["latest_date"], reverse=True)
    elif order_by == "Precio ascendente":
        entries.sort(key=lambda e: (e["currency"], float(e["latest_price"])))
    else:  # "Precio descendente"
        entries.sort(key=lambda e: (e["currency"], float(e["latest_price"])), reverse=True)

    # 8) Límite de tarjetas
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

# -------------------- Página Alertas --------------------
elif page == "Alertas":
    st.title("🔔 Alertas de precio")
    if not st.session_state.session:
        st.warning("Iniciá sesión primero en la sección Login.")
        st.stop()

    user_id = get_user_id()
    if not user_id:
        st.error("Tu sesión expiró. Iniciá sesión nuevamente.")
        st.stop()

    st.subheader("Crear alerta")
    product_name_input = st.text_input("Producto")
    target_price = st.number_input("Alertarme si el precio es menor o igual a…", min_value=0.0, step=0.01, format="%.2f")
    radius_km = st.slider("Radio de alerta (km)", 1, 20, 5)

    if st.button("Activar alerta"):
        try:
            # Normalizar antes de buscar/crear
            product_name = normalize_product(product_name_input)

            # Buscar o crear producto con nombre normalizado
            prod_q = (
                supabase.table("products")
                .select("id, currency")
                .eq("name", product_name)
                .limit(1)
                .execute()
                .data
            )
            if not prod_q:
                prod_ins = supabase.table("products").insert({"name": product_name, "currency": "ARS"}).execute()
                product_id = prod_ins.data[0]["id"]
            else:
                product_id = prod_q[0]["id"]

            supabase.table("alerts").insert({
                "user_id": user_id,
                "product_id": product_id,
                "target_price": float(target_price) if target_price else None,
                "radius_km": float(radius_km),
                "active": True
            }).execute()

            st.success("✅ Alerta creada. Te avisaremos cuando haya precios **validados** más baratos cerca.")
        except Exception as e:
            st.error(f"No pudimos crear la alerta: {e}")

    st.subheader("Mis notificaciones")
    try:
        notes = supabase.table("notifications").select(
            "id, alert_id, sighting_id, created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).execute().data

        if not notes:
            st.info("Todavía no hay notificaciones.")
        else:
            for n in notes:
                st.write(f"🔔 Notificación #{n['id']} — avistamiento {n['sighting_id']} — {n['created_at']}")
    except Exception as e:
        st.error(f"Error al cargar notificaciones: {e}")

