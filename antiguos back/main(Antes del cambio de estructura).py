import os
from fastapi import FastAPI, HTTPException, Response, Request, Cookie
from pydantic import BaseModel
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
import math

# Comando para activar venv: .\venv\Scripts\activate
# Comando para ejecutar: uvicorn main:app --reload

load_dotenv()

app = FastAPI(title="Solo Leveling API - System")

# --- CONFIGURACIÓN DE CORS ---
ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DE SUPABASE (MOTOR OPTIMIZADO) ---
URL: str = os.environ.get("VITE_SUPABASE_URL")
SERVICE_KEY: str = os.environ.get("VITE_SUPABASE_SERVICE_ROLE_KEY")

# Cliente inicial para BBDD
supabase_db: Client = create_client(URL, SERVICE_KEY)

# Cliente inicial para Auth
supabase_auth: Client = create_client(URL, SERVICE_KEY)

# --- ESQUEMAS ---
class LoginSchema(BaseModel):
    email: str
    password: str

class SignupSchema(BaseModel):
    email: str
    password: str
    username: str 

class UpdateStatsSchema(BaseModel):
    strength: int = 0
    agility: int = 0
    vitality: int = 0
    intelligence: int = 0
    sense: int = 0

class UpdateActiveTitleSchema(BaseModel):
    title_id: int

# --- HELPERS ---
def check_level_up(profile: dict):
    # Creamos una copia para trabajar y rastrear si hubo cambios
    new_data = {
        "level": profile["level"],
        "experience": profile["experience"],
        "exp_next_level": profile["exp_next_level"],
        "stat_points": profile["stat_points"],
        "hp_max": profile["hp_max"],
        "mp_max": profile["mp_max"]
    }
    
    leveled_up = False

    # Bucle While: Mientras tengamos EXP para subir, seguimos procesando
    while new_data["experience"] >= new_data["exp_next_level"]:
        leveled_up = True
        
        # 1. Consumimos la EXP necesaria y subimos nivel
        new_data["experience"] -= new_data["exp_next_level"]
        new_data["level"] += 1
        
        # 2. Recompensas por nivel
        new_data["stat_points"] += 5
        
        # 3. Escalar stats de salud/maná (Opcional: +20 HP y +10 MP por nivel)
        new_data["hp_max"] += 20
        new_data["mp_max"] += 10
        
        # 4. Calcular el NUEVO umbral (Cada nivel es un 20% más difícil)
        # Fórmula: nivel_nuevo * 100 * (1.2 ^ (nivel_nuevo - 1))
        new_data["exp_next_level"] = math.floor(
            new_data["level"] * 100 * (1.2 ** (new_data["level"] - 1))
        )

    if leveled_up:
        # Si subió al menos un nivel, devolvemos el paquete completo de actualización
        return {
            "level": new_data["level"],
            "experience": new_data["experience"],
            "exp_next_level": new_data["exp_next_level"],
            "stat_points": new_data["stat_points"],
            "hp_max": new_data["hp_max"],
            "hp_current": new_data["hp_max"], # Curación total al subir
            "mp_max": new_data["mp_max"],
            "mp_current": new_data["mp_max"], # Maná total al subir
            "fatigue": 0,                     # Reset de fatiga
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    
    return None

# --- RUTAS DE AUTENTICACIÓN ---

@app.get("/auth/verify")
async def verify_session(hunter_session: Optional[str] = Cookie(None)):
    if not hunter_session: 
        raise HTTPException(status_code=401)
    try:
        supabase_auth.auth.get_user(hunter_session)
        return {"authenticated": True}
    except: 
        raise HTTPException(status_code=401)

@app.post("/auth/signup")
async def signup(datos: SignupSchema, response: Response):
    try:
        auth_response = supabase_auth.auth.sign_up({
            "email": datos.email,
            "password": datos.password,
            "options": {
                "data": {
                    "display_name": datos.username
                }
            }
        })
        if auth_response.user is None:
            raise Exception("Error al crear el usuario")

        if auth_response.session:
            token = auth_response.session.access_token
            response.set_cookie(
                key="hunter_session", value=token,
                httponly=True, max_age=3600 * 24, samesite="lax", secure=False, path="/"
            )
            return {"status": "success", "message": "Cazador registrado e identificado", "user": auth_response.user}
        
        # En caso de que pida confirmación por email (fallback)
        return {"status": "pending", "message": "Usuario creado. Verifica tu email."}
        # return {"message": "Usuario creado con éxito", "id": response.user.id}
    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg:
            error_msg = "El email ya está registrado"
        raise HTTPException(status_code=400, detail=f"Error al registrar: {error_msg}")

@app.post("/auth/login")
async def login(datos: LoginSchema, response: Response):
    try:
        auth_response = supabase_auth.auth.sign_in_with_password({
            "email": datos.email, "password": datos.password
        })
        token = auth_response.session.access_token
        response.set_cookie(
            key="hunter_session", value=token,
            httponly=True, max_age=3600 * 24, samesite="lax", secure=False, path="/"
        )
        return {"status": "success", "user": auth_response.user}
    except:
        raise HTTPException(status_code=400, detail="Error de identificación")

@app.post("/auth/logout")
async def logout(response: Response):
    try:
        # Intentamos cerrar sesión en Supabase
        try: supabase_auth.auth.sign_out()
        except: pass
        
        # Borramos la cookie del navegador
        response.delete_cookie(key="hunter_session", path="/", samesite="lax", httponly=True)
        return {"message": "Sesión cerrada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- RUTAS DE JUEGO (PROTEGIDAS Y RÁPIDAS) ---

@app.get("/hunter/profile")
async def get_my_profile(hunter_session: Optional[str] = Cookie(None)):
    if not hunter_session:
        raise HTTPException(status_code=401, detail="Sesión no encontrada")

    try:
        # 1. Validar identidad
        user = supabase_auth.auth.get_user(hunter_session)
        user_id = user.user.id

        # 2. Obtener cliente (reutilizado)
        profile = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute()
        return profile.data

    except Exception as e:
        print(f"SISTEMA ERROR PROFILE: {str(e)}")
        raise HTTPException(status_code=401, detail="Error al acceder al Nexo")

@app.post("/hunter/update-stats")
async def update_hunter_stats(datos: UpdateStatsSchema, hunter_session: Optional[str] = Cookie(None)):
    if not hunter_session:
        raise HTTPException(status_code=401, detail="Sesión no encontrada")

    try:
        # 1. Validar identidad
        user = supabase_auth.auth.get_user(hunter_session)
        user_id = user.user.id

        # 2. Obtener datos actuales del perfil
        profile_res = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute()
        profile = profile_res.data

        # 3. Validar puntos a gastar
        puntos_a_gastar = sum([datos.strength, datos.agility, datos.vitality, datos.intelligence, datos.sense])
        if puntos_a_gastar <= 0 or profile["stat_points"] < puntos_a_gastar:
            raise HTTPException(status_code=400, detail="Puntos insuficientes")

        # 4. Preparar diccionario de actualización básica
        nuevos_stats = {
            "strength": profile["strength"] + datos.strength,
            "agility": profile["agility"] + datos.agility,
            "vitality": profile["vitality"] + datos.vitality,
            "intelligence": profile["intelligence"] + datos.intelligence,
            "sense": profile["sense"] + datos.sense,
            "stat_points": profile["stat_points"] - puntos_a_gastar,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        # 5. Lógica de VITALIDAD (Aditiva simple: +15 HP por punto)
        if datos.vitality > 0:
            aumento_hp = datos.vitality * 15
            nuevo_hp_max = profile["hp_max"] + aumento_hp
            
            nuevos_stats["hp_max"] = nuevo_hp_max
            
            # Curación condicional
            if profile["hp_current"] >= profile["hp_max"]:
                nuevos_stats["hp_current"] = nuevo_hp_max
            else:
                nuevos_stats["hp_current"] = profile["hp_current"]

        # 6. Lógica de INTELIGENCIA (Aditiva simple: +5 MP por punto)
        if datos.intelligence > 0:
            aumento_mp = datos.intelligence * 5
            nuevo_mp_max = profile["mp_max"] + aumento_mp
            
            nuevos_stats["mp_max"] = nuevo_mp_max
            
            # Curación condicional
            if profile["mp_current"] >= profile["mp_max"]:
                nuevos_stats["mp_current"] = nuevo_mp_max
            else:
                nuevos_stats["mp_current"] = profile["mp_current"]

        # 7. Guardar cambios en Supabase
        update_res = supabase_db.table("profiles").update(nuevos_stats).eq("id", user_id).execute()
        
        return {"status": "success", "new_stats": update_res.data[0]}

    except Exception as e:
        if isinstance(e, HTTPException): raise e
        print(f"ERROR UPDATE STATS: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al sincronizar estadísticas")

@app.get("/hunter/titles")
async def get_all_game_titles(hunter_session: Optional[str] = Cookie(None)):
    if not hunter_session:
        raise HTTPException(status_code=401, detail="Sesión no válida")

    try:
        # 1. Obtener ID del usuario
        user = supabase_auth.auth.get_user(hunter_session)
        user_id = user.user.id

        # 2. Obtener TODOS los títulos del catálogo
        all_titles_res = supabase_db.table("titles").select("*").execute()
        all_titles = all_titles_res.data

        # 3. Obtener los IDs de los títulos que el cazador ya desbloqueó
        unlocked_res = (
            supabase_db.table("hunter_titles")
            .select("title_id")
            .eq("hunter_id", user_id)
            .execute()
        )
        # Creamos un set de IDs para búsqueda rápida: {1, 2, 5}
        unlocked_ids = {item["title_id"] for item in unlocked_res.data}

        # 4. Combinar la información
        # Añadimos la propiedad 'is_unlocked' a cada objeto
        for title in all_titles:
            title["is_unlocked"] = title["id"] in unlocked_ids

        return all_titles

    except Exception as e:
        print(f"DEBUG ERROR TITLES: {str(e)}")
        raise HTTPException(status_code=500, detail="Error en el sistema de títulos")

@app.patch("/hunter/active-title")
async def update_active_title(datos: UpdateActiveTitleSchema, hunter_session: Optional[str] = Cookie(None)):
    """
    Cambia el título activo del cazador. 
    Verifica primero que el cazador posea el título en la tabla intermedia.
    """
    if not hunter_session:
        raise HTTPException(status_code=401, detail="Sesión no encontrada")

    try:
        # 1. Validar identidad
        user = supabase_auth.auth.get_user(hunter_session)
        user_id = user.user.id

        # 2. VERIFICACIÓN DE SEGURIDAD: ¿El cazador tiene este título desbloqueado?
        # Consultamos la tabla intermedia hunter_titles
        check_ownership = (
            supabase_db.table("hunter_titles")
            .select("*")
            .eq("hunter_id", user_id)
            .eq("title_id", datos.title_id)
            .execute()
        )

        if not check_ownership.data:
            raise HTTPException(
                status_code=403, 
                detail="SISTEMA: No has desbloqueado este título todavía."
            )

        # 3. ACTUALIZAR el active_title_id en el perfil del cazador
        update_res = (
            supabase_db.table("profiles")
            .update({
                "active_title_id": datos.title_id,
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
            .eq("id", user_id)
            .execute()
        )

        return {
            "status": "success", 
            "message": "Título equipado correctamente",
            "active_title_id": datos.title_id
        }

    except Exception as e:
        if isinstance(e, HTTPException): raise e
        print(f"SISTEMA ERROR TITULOS: {str(e)}")
        raise HTTPException(status_code=500, detail="Error en la sincronización del título")
    
@app.get("/hunter/missions")
async def get_hunter_missions(hunter_session: Optional[str] = Cookie(None)):
    """
    Obtiene todas las misiones del cazador en un formato plano (JSON Total).
    Incluye lógica de inyección de misión diaria.
    """
    if not hunter_session:
        raise HTTPException(status_code=401, detail="Sesión no encontrada")

    try:
        # 1. Identificar al cazador
        user = supabase_auth.auth.get_user(hunter_session)
        user_id = user.user.id
        hoy = datetime.now(timezone.utc).date()

        # 2. Lógica de Misión Diaria (Verificación e Inyección)
        check_daily = (
            supabase_db.table("hunter_missions")
            .select("id, started_at, missions!inner(mission_type)")
            .eq("hunter_id", user_id)
            .eq("missions.mission_type", "daily")
            .execute()
        )

        tiene_diaria_hoy = any(
            datetime.fromisoformat(m["started_at"]).date() == hoy 
            for m in check_daily.data
        )

        if not tiene_diaria_hoy:
            daily_catalog = supabase_db.table("missions").select("id").eq("mission_type", "daily").limit(1).execute()
            if daily_catalog.data:
                supabase_db.table("hunter_missions").insert({
                    "hunter_id": user_id,
                    "mission_id": daily_catalog.data[0]["id"],
                    "status": "active",
                    "current_progress": 0
                }).execute()

        # 3. Obtener todas las misiones con JOIN
        res = (
            supabase_db.table("hunter_missions")
            .select("""
                id,
                current_progress,
                status,
                started_at,
                completed_at,
                missions (
                    id,
                    title,
                    description,
                    mission_type,
                    target_type,
                    target_value,
                    reward_exp,
                    reward_gold,
                    reward_items
                )
            """)
            .eq("hunter_id", user_id)
            .order("started_at", desc=True)
            .execute()
        )

        # 4. PROCESADO PARA "JSON TOTAL" (Aplanamiento completo)
        final_missions = []
        for item in res.data:
            # Extraemos los datos del catálogo de misiones
            catalog_info = item.pop("missions")
            
            # Combinamos todo en un solo nivel
            # El ID que prevalece es el de 'hunter_missions' (la instancia)
            # pero guardamos el 'mission_id' original por si acaso
            flattened = {
                "instance_id": item["id"],
                "current_progress": item["current_progress"],
                "status": item["status"],
                "started_at": item["started_at"],
                "completed_at": item["completed_at"],
                **catalog_info  # Esto añade title, description, mission_type, target_value, rewards...
            }
            final_missions.append(flattened)

        return final_missions

    except Exception as e:
        print(f"SISTEMA ERROR MISSIONS: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al sincronizar misiones")

@app.post("/hunter/missions/{instance_id}/claim")
async def claim_mission_reward(instance_id: int, hunter_session: Optional[str] = Cookie(None)):
    if not hunter_session:
        raise HTTPException(status_code=401, detail="Sesión no encontrada")

    try:
        # 1. Validar identidad
        user = supabase_auth.auth.get_user(hunter_session)
        user_id = user.user.id

        # 2. Obtener instancia y catálogo (Con join para recompensas y metas)
        mission_res = (
            supabase_db.table("hunter_missions")
            .select("*, missions(target_value, reward_gold, reward_exp)")
            .eq("id", instance_id)
            .eq("hunter_id", user_id)
            .single()
            .execute()
        )

        instance = mission_res.data
        if not instance:
            raise HTTPException(status_code=404, detail="Misión no encontrada")

        # --- SEGURIDAD ---
        if instance["status"] != "completed":
            raise HTTPException(status_code=400, detail="Misión no completada")
        
        target = instance["missions"]["target_value"]
        if instance["current_progress"] < target:
            raise HTTPException(status_code=400, detail="Progreso insuficiente")

        # 3. Obtener Perfil Actual
        profile_res = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute()
        profile = profile_res.data

        # 4. Calcular Recompensas Inmediatas
        gold_gain = instance["missions"].get("reward_gold", 0)
        exp_gain = instance["missions"].get("reward_exp", 0)

        # 5. Lógica de Subida de Nivel (Bucle para múltiples niveles)
        # Creamos el estado "futuro" sumando la nueva EXP
        new_level = profile["level"]
        new_exp = profile["experience"] + exp_gain
        new_next_level_exp = profile["exp_next_level"]
        new_stat_points = profile["stat_points"]
        new_hp_max = profile["hp_max"]
        new_mp_max = profile["mp_max"]
        
        leveled_up = False

        # Mientras la experiencia alcance para subir, procesamos niveles
        while new_exp >= new_next_level_exp:
            leveled_up = True
            new_exp -= new_next_level_exp
            new_level += 1
            
            # Recompensas de nivel (Personaliza estos valores)
            new_stat_points += 5
            new_hp_max += 20
            new_mp_max += 10
            
            # Recalcular meta para el siguiente nivel (Fórmula 20% escalado)
            new_next_level_exp = math.floor(new_level * 100 * (1.2 ** (new_level - 1)))

        # 6. Preparar el paquete de actualización
        update_data = {
            "gold": profile["gold"] + gold_gain,
            "experience": new_exp,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        if leveled_up:
            update_data.update({
                "level": new_level,
                "exp_next_level": new_next_level_exp,
                "stat_points": new_stat_points,
                "hp_max": new_hp_max,
                "hp_current": new_hp_max, # Full heal al subir nivel
                "mp_max": new_mp_max,
                "mp_current": new_mp_max, # Full mana al subir nivel
                "fatigue": 0              # Reset de fatiga
            })

        # 7. Ejecutar cambios en Base de Datos (Atomic Update)
        supabase_db.table("profiles").update(update_data).eq("id", user_id).execute()
        supabase_db.table("hunter_missions").update({"status": "claimed"}).eq("id", instance_id).execute()

        return {
            "status": "success",
            "leveled_up": leveled_up,
            "gains": {
                "gold": gold_gain,
                "exp": exp_gain,
                "levels_gained": new_level - profile["level"] if leveled_up else 0
            },
            "current_state": {
                "level": new_level,
                "gold": profile["gold"] + gold_gain
            }
        }

    except Exception as e:
        if isinstance(e, HTTPException): raise e
        print(f"ERROR CLAIM: {str(e)}")
        raise HTTPException(status_code=500, detail="Fallo en la conexión con el Sistema")