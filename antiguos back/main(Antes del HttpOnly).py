import os
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

# Comando para activar venv: .\venv\Scripts\activate
# Comando para ejecutar: uvicorn main:app --reload

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar cliente de Supabase
url: str = os.environ.get("VITE_SUPABASE_URL")
key: str = os.environ.get("VITE_SUPABASE_ANON_KEY")
supabase: Client = create_client(url, key)

# --- ESQUEMAS DE DATOS ---

# Para el Login solo necesitamos email y password
class LoginSchema(BaseModel):
    email: str
    password: str

# Para el Registro añadimos el campo username que envías desde React
class SignupSchema(BaseModel):
    email: str
    password: str
    username: str 

# --- RUTAS ---

@app.post("/auth/login")
async def login(datos: LoginSchema):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": datos.email,
            "password": datos.password
        })
        
        return {
            "access_token": response.session.access_token,
            "user": response.user
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail="Credenciales incorrectas")

@app.post("/auth/signup")
async def signup(datos: SignupSchema):
    try:
        # Usamos 'options' para guardar el username en la metadata del usuario
        response = supabase.auth.sign_up({
            "email": datos.email,
            "password": datos.password,
            "options": {
                "data": {
                    "display_name": datos.username,
                    "level": 1,
                    "gold": 0
                }
            }
        })
        
        if response.user is None:
            raise Exception("Error al crear el usuario en Supabase")

        return {
            "message": "Usuario creado con éxito", 
            "id": response.user.id
        }
    except Exception as e:
        # Limpiamos el error para que sea legible en el front
        error_msg = str(e)
        if "already registered" in error_msg:
            error_msg = "El email ya está registrado"
        raise HTTPException(status_code=400, detail=f"Error al registrar: {error_msg}")

@app.post("/auth/logout")
async def logout():
    try:
        supabase.auth.sign_out() 
        return {"message": "Sesión cerrada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@app.get("/hunter/profile")
async def get_my_profile(authorization: Optional[str] = Header(None)):
    print(f"HEADER RECIBIDO: {authorization}") # 1. Ver si llega el header
    
    if not authorization:
        raise HTTPException(status_code=401, detail="No hay token")

    try:
        token = authorization.replace("Bearer ", "")
        # 2. Intentar validar el usuario
        user_response = supabase.auth.get_user(token)
        user_id = user_response.user.id
        print(f"USUARIO AUTENTICADO ID: {user_id}")

        # 3. Intentar traer la fila
        response = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
        print(f"DATOS DE LA TABLA: {response.data}")

        return response.data
    except Exception as e:
        print(f"ERROR DETECTADO: {str(e)}") # AQUÍ VERÉIS EL ERROR REAL
        raise HTTPException(status_code=401, detail=f"Error interno: {str(e)}")