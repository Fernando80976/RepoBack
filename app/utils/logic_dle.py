from fastapi import HTTPException
from datetime import datetime, timezone, date
from app.core.config import supabase_db
import random

def compare_ranks(guess_key: str, target_key: str):
    # Definimos el orden de poder basado en tus CHECK constraints
    # E < D < C < B < A < S < N (National) < M (Monarch)
    rank_order = ['E', 'D', 'C', 'B', 'A', 'S', 'N', 'M']

    # Si alguno es 'U' (Unknown), no hay comparación de mayor/menor
    if guess_key == 'U' or target_key == 'U':
        return "correct" if guess_key == target_key else "incorrect"

    try:
        g_idx = rank_order.index(guess_key)
        t_idx = rank_order.index(target_key)
        
        if g_idx == t_idx:
            return "correct"
        
        # 'higher' significa que el objetivo es más fuerte que tu elección
        return "higher" if g_idx < t_idx else "lower"
    except ValueError:
        # En caso de que llegue un valor no contemplado
        return "incorrect"

async def get_or_set_daily_target():
    """
    Busca si ya hay un personaje elegido para hoy. 
    Si no, elige uno aleatorio del catálogo de personajes.
    """
    hoy = date.today().isoformat()
    
    # 1. Intentamos ver si algún usuario ya tiene un log hoy para sacar el ID del personaje
    existing = (
        supabase_db.table("daily_dle_logs")
        .select("target_character_id")
        .eq("completion_date", hoy)
        .limit(1)
        .execute()
    )
    
    if existing.data:
        return existing.data[0]["target_character_id"]
    
    # 2. Si es el primer usuario del día, elegimos personaje aleatorio
    all_chars = supabase_db.table("daily_challenge_characters").select("id").execute()
    if not all_chars.data:
        raise HTTPException(status_code=500, detail="Catálogo de personajes DLE vacío")
        
    chosen_id = random.choice([c["id"] for c in all_chars.data])
    return chosen_id


async def sync_daily_dle_mission(user_id: str):
    """
    Encapsula toda la lógica del DLE: 
    1. Obtiene el personaje del día.
    2. Verifica si el usuario tiene la misión al día.
    3. Si no, reinicia el progreso y los logs.
    """

    hoy_dt = datetime.now(timezone.utc)
    hoy_date = hoy_dt.date()

    target_today_id = await get_or_set_daily_target()

    
    # 1. Buscamos si el usuario ya tiene una instancia de DLE (de hoy o de antes)
    # Importante: missions!inner filtra la consulta principal
    check_dle = (
        supabase_db.table("hunter_missions")
        .select("id, started_at, missions!inner(id, target_type)")
        .eq("hunter_id", user_id)
        .eq("missions.target_type", "dle_guess")
        .execute()
    )

    dle_config_id = None
    existing_instance_id = None
    necesita_actualizar = True

    if check_dle.data:
        # Ya tiene una misión DLE registrada alguna vez
        
        instance = check_dle.data[0]
        existing_instance_id = instance["id"]
        dle_config_id = instance["missions"]["id"]
        
        
        fecha_instancia = datetime.fromisoformat(instance["started_at"]).date()
        
        if fecha_instancia == hoy_date:
            necesita_actualizar = False # Ya está al día

    # 2. Si no tiene o es de un día anterior, actualizamos o insertamos
    if necesita_actualizar:
        
        # Si no encontramos el dle_config_id arriba, lo buscamos en el catálogo
        if not dle_config_id:
            dle_cat = supabase_db.table("missions").select("id").eq("target_type", "dle_guess").single().execute()
            if dle_cat.data:
                dle_config_id = dle_cat.data["id"]

        if dle_config_id:
        
            # DATOS DE REINICIO
            mission_data = {
                "hunter_id": user_id,
                "mission_id": dle_config_id,
                "status": "active",
                "current_progress": 0,
                "started_at": hoy_dt.isoformat(),
                "completed_at": None # Limpiamos si estaba completada ayer
            }

            if existing_instance_id:
                # REUTILIZAR: Actualizamos la misión vieja con fecha de hoy
                supabase_db.table("hunter_missions").update(mission_data).eq("id", existing_instance_id).execute()
            else:
                # CREAR: Si es un usuario nuevo que nunca la tuvo
                supabase_db.table("hunter_missions").insert(mission_data).execute()
            
            # B) Sincronizamos el LOG (Minijuego) - El UPSERT aquí es clave
            # Usamos user_id y completion_date como clave lógica para resetear el intento diario
            supabase_db.table("daily_dle_logs").upsert({
                "user_id": user_id,
                "mission_id": dle_config_id,
                "target_character_id": target_today_id,
                "completion_date": hoy_date.isoformat(),
                "is_completed": False,
                "attempts": 0,
                "attempts_history": [] # Limpiamos el historial de ayer
            }).execute() 
    return target_today_id