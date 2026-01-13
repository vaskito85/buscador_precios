# utils/geolocation.py
"""
Módulo centralizado de geolocalización. 
Maneja la obtención de ubicación desde el navegador sin recargas de página.
"""
import streamlit as st
from typing import Optional, Tuple, Dict, Any

def get_user_location() -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Obtiene la ubicación del usuario usando streamlit-js-eval.
    
    Returns:
        Tuple[lat, lon, error_msg] donde:
        - lat, lon: coordenadas (float) o None
        - error_msg:  mensaje de error (str) o None si fue exitoso
    
    Error codes:
        1:  PERMISSION_DENIED - Usuario denegó el permiso
        2: POSITION_UNAVAILABLE - Posición no disponible
        3: TIMEOUT - Tiempo agotado
        -1: Otra excepción
    """
    try:
        from streamlit_js_eval import get_geolocation
    except ImportError:
        return None, None, "❌ streamlit-js-eval no está instalado"
    
    try:
        location = get_geolocation()
        
        if not isinstance(location, dict):
            return None, None, "❌ Respuesta inválida del navegador"
        
        # Manejo de errores
        if "error" in location:
            error = location. get("error")
            if isinstance(error, dict):
                error_code = error.get("code", -1)
                error_msg = error.get("message", "Error desconocido")
                
                error_messages = {
                    1: "❌ Permiso denegado.  Habilita la geolocalización en los ajustes del navegador.",
                    2: "⚠️ Tu posición no está disponible en este momento.  Intenta en otra ubicación.",
                    3: "⏱️ Tiempo agotado.  Intenta de nuevo.",
                }
                
                return None, None, error_messages. get(error_code, f"❌ Error {error_code}:  {error_msg}")
        
        # Extrae coordenadas si están disponibles
        coords = location.get("coords")
        if isinstance(coords, dict):
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            
            if lat is not None and lon is not None:
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                    return lat_f, lon_f, None
                except (ValueError, TypeError):
                    return None, None, "❌ Coordenadas inválidas"
        
        return None, None, "❌ No se obtuvieron coordenadas válidas"
    
    except Exception as e:
        return None, None, f"❌ Error al obtener ubicación: {str(e)}"


def set_location_from_gps(lat_key: str, lon_key: str) -> bool:
    """
    Obtiene la ubicación del usuario y la guarda en session_state.
    Muestra mensajes de error/éxito al usuario.
    
    Args:
        lat_key: clave de session_state para latitud
        lon_key: clave de session_state para longitud
    
    Returns:
        True si la ubicación se obtuvo exitosamente, False en caso contrario
    """
    with st.spinner("📍 Obteniendo tu ubicación..."):
        lat, lon, error_msg = get_user_location()
    
    if error_msg:
        st.error(error_msg)
        return False
    
    if lat is not None and lon is not None: 
        st.session_state[lat_key] = str(lat)
        st.session_state[lon_key] = str(lon)
        st.success(f"✅ Ubicación obtenida:  {lat:. 4f}, {lon:.4f}")
        return True
    
    return False


def get_fallback_input() -> Tuple[Optional[float], Optional[float]]:
    """
    Alternativa manual si la geolocalización automática falla.
    El usuario puede ingresar la ubicación manualmente.
    
    Returns:
        Tuple[lat, lon] o (None, None) si no ingresa datos válidos
    """
    st.info("📍 Si el GPS no funciona, puedes ingresar tu ubicación manualmente.")
    
    col1, col2 = st. columns(2)
    with col1:
        lat_txt = st.text_input("Latitud manual", placeholder="-38.7183")
    with col2:
        lon_txt = st.text_input("Longitud manual", placeholder="-62.2663")
    
    if lat_txt and lon_txt: 
        try:
            return float(lat_txt), float(lon_txt)
        except ValueError:
            st.warning("⚠️ Latitud/Longitud inválidas. Usa números decimales.")
    
    return None, None