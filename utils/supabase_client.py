from supabase import create_client
import streamlit as st

# Obtiene cliente de Supabase usando secrets de Streamlit Cloud
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)
