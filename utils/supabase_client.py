
# utils/supabase_client.py
from supabase import create_client
import os
import streamlit as st

# Cachea el cliente para evitar recrearlo.
@st.cache_resource
def get_supabase():
    url = None
    key = None

    # 1) Streamlit secrets
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
    except Exception:
        pass

    # 2) Variables de entorno (modo local)
    if not url:
        url = os.getenv("SUPABASE_URL")
    if not key:
        key = os.getenv("SUPABASE_ANON_KEY")

    if not url or not key:
        raise RuntimeError(
            "No se encontraron credenciales de Supabase. "
            "Definí SUPABASE_URL y SUPABASE_ANON_KEY en Streamlit secrets o variables de entorno."
        )
    return create_client(url, key)
