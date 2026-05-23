import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Variables de entorno
URL: str = os.environ.get("VITE_SUPABASE_URL")
SERVICE_KEY: str = os.environ.get("VITE_SUPABASE_SERVICE_ROLE_KEY")

# Clientes globales
supabase_db: Client = create_client(URL, SERVICE_KEY)
supabase_auth: Client = create_client(URL, SERVICE_KEY)