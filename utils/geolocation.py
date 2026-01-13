# utils/geolocation.py
"""
Módulo centralizado de geolocalización.  
Maneja la obtención de ubicación desde el navegador sin recargas de página.
"""
import streamlit as st
from typing import Optional, Tuple

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
        
        # DEBUG: Ver qué responde exactamente
        st.session_state.setdefault("_geo_debug", location)
        
        # Si es None o vacío
        if location is None:
            return None, None, "❌ El navegador no respondió (verifica permisos de ubicación)"
        
        if not isinstance(location, dict):
            return None, None, f"❌ Respuesta inválida: {type(location).__name__}"
        
        # Caso 1: Error en la respuesta
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
                
                return None, None, error_messages. get(error_code, f"❌ Error {error_code}: {error_msg}")
            elif isinstance(error, str):
                return None, None, f"❌ {error}"
        
        # Caso 2: Coordenadas en location. coords (formato estándar)
        if "coords" in location:
            coords = location. get("coords")
            if isinstance(coords, dict):
                lat = coords.get("latitude")
                lon = coords.get("longitude")
                
                if lat is not None and lon is not None: 
                    try:
                        lat_f = float(lat)
                        lon_f = float(lon)
                        return lat_f, lon_f, None
                    except (ValueError, TypeError) as e:
                        return None, None, f"❌ Coordenadas inválidas: {e}"
        
        # Caso 3: Coordenadas directas (algunos navegadores)
        if "latitude" in location and "longitude" in location:
            lat = location. get("latitude")
            lon = location.get("longitude")
            
            if lat is not None and lon is not None:
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                    return lat_f, lon_f, None
                except (ValueError, TypeError) as e:
                    return None, None, f"❌ Coordenadas inválidas: {e}"
        
        # Caso 4: Diccionario vacío o sin datos útiles
        return None, None, f"❌ No se obtuvieron coordenadas válidas.  Respuesta: {location}"
    
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
    st.info("📍 Por favor, autoriza el acceso a tu ubicación cuando el navegador lo solicite.")
    
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