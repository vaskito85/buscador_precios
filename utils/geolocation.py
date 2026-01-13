# utils/geolocation.py
"""
Módulo centralizado de geolocalización. 
Maneja la obtención de ubicación desde el navegador sin recargas de página.
"""
import streamlit as st
from typing import Optional, Tuple
import streamlit.components.v1 as components
import json

def get_user_location_via_html() -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Obtiene ubicación usando HTML + JavaScript puro (más compatible con Streamlit Cloud).
    Usa el Geolocation API del navegador.
    
    Returns:
        Tuple[lat, lon, error_msg]
    """
    
    # Crear HTML con JavaScript que se comunique con Streamlit
    geolocation_html = """
    <div id="geo-container" style="padding: 10px; border-radius: 8px; background: #f0f0f0; margin: 10px 0;">
        <button id="geo-btn" style="
            background: #4CAF50; color: white; border: none; border-radius: 8px;
            padding: 10px 16px; font-size: 14px; cursor: pointer; font-weight: bold;">
            📍 Obtener ubicación
        </button>
        <span id="geo-status" style="margin-left: 10px; color: #888; font-size: 13px; vertical-align: middle;"></span>
        <div id="geo-result" style="display: none; margin-top: 10px; padding: 10px; background: #e8f5e9; border-radius: 4px; border-left: 4px solid #4CAF50;">
            <strong>Ubicación obtenida: </strong><br/>
            Latitud: <span id="lat-result">-</span><br/>
            Longitud: <span id="lon-result">-</span>
        </div>
    </div>
    
    <script>
    (function(){
        const btn = document.getElementById('geo-btn');
        const statusEl = document.getElementById('geo-status');
        const resultDiv = document.getElementById('geo-result');
        const latResult = document.getElementById('lat-result');
        const lonResult = document.getElementById('lon-result');
        
        function setStatus(msg, color='#888', type='info') {
            statusEl.textContent = msg;
            statusEl.style.color = color;
            if (type === 'error') {
                statusEl.style.fontWeight = 'bold';
            }
        }
        
        function onSuccess(pos) {
            const latitude = pos.coords.latitude;
            const longitude = pos.coords. longitude;
            setStatus(`✅ Ubicación obtenida`, '#4CAF50', 'success');
            latResult.textContent = latitude.toFixed(6);
            lonResult.textContent = longitude.toFixed(6);
            resultDiv.style.display = 'block';
            
            // Guardar en sessionStorage para que Streamlit lo lea
            sessionStorage.setItem('user_lat', latitude);
            sessionStorage.setItem('user_lon', longitude);
        }
        
        function onError(err) {
            const errors = {
                1: '❌ Permiso denegado.  Habilita la geolocalización en ajustes del navegador.',
                2: '⚠️ Posición no disponible. Intenta en otra ubicación.',
                3: '⏱️ Tiempo agotado. Intenta de nuevo.',
            };
            const msg = errors[err.code] || '❌ Error de geolocalización. ';
            setStatus(msg, '#d9534f', 'error');
        }
        
        btn. addEventListener('click', function(){
            if (! navigator.geolocation) {
                setStatus('❌ Geolocalización no soportada', '#d9534f', 'error');
                return;
            }
            setStatus('Obteniendo ubicación...', '#FFA500');
            btn.disabled = true;
            navigator.geolocation.getCurrentPosition(onSuccess, onError, {
                enableHighAccuracy:  true,
                timeout: 10000,
                maximumAge: 0
            });
        });
    })();
    </script>
    """
    
    components.html(geolocation_html, height=150, scrolling=False)
    
    return None, None, None


def set_location_from_gps(lat_key:  str, lon_key: str) -> bool:
    """
    Obtiene la ubicación del usuario y la guarda en session_state.
    Muestra mensajes de error/éxito al usuario.
    
    Args:
        lat_key: clave de session_state para latitud
        lon_key: clave de session_state para longitud
    
    Returns:
        True si la ubicación se obtuvo exitosamente, False en caso contrario
    """
    st.info("📍 Haz clic en el botón para obtener tu ubicación.  El navegador te pedirá permiso.")
    
    # Mostrar el componente HTML
    get_user_location_via_html()
    
    st.caption("⚠️ Después de hacer clic, espera a que aparezca tu ubicación.  Luego haz clic en el botón de abajo para confirmar.")
    
    # Botón de confirmación manual
    if st.button("✅ Confirmar ubicación obtenida", key=f"confirm_geo_{lat_key}"):
        import json
        
        # Intentar obtener de sessionStorage (no funcionará directamente, alternativa:  input manual)
        col1, col2 = st.columns(2)
        with col1:
            lat_input = st.text_input("Latitud (si aparece, cópiala aquí):", key=f"lat_input_{lat_key}")
        with col2:
            lon_input = st.text_input("Longitud (si aparece, cópiala aquí):", key=f"lon_input_{lon_key}")
        
        if lat_input and lon_input:
            try:
                lat = float(lat_input)
                lon = float(lon_input)
                st.session_state[lat_key] = str(lat)
                st.session_state[lon_key] = str(lon)
                st. success(f"✅ Ubicación guardada: {lat:. 4f}, {lon:.4f}")
                st.rerun()
                return True
            except ValueError: 
                st.error("❌ Valores inválidos.  Usa números decimales.")
                return False
    
    return False