from fastapi import HTTPException
from datetime import datetime, timezone, date
from app.core.config import supabase_db
import random

def compare_ranks(guess_key: str, target_key: str):
    rank_order = ['E', 'D', 'C', 'B', 'A', 'S', 'N', 'M', 'M_F', 'M_L', 'M_Q', 'M_B', 'M_R', 'M_Y', 'M_ANT', 'M_S', 'M_ASH']

    if guess_key == 'U' or target_key == 'U':
        return "correct" if guess_key == target_key else "incorrect"

    try:
        g_idx = rank_order.index(guess_key)
        t_idx = rank_order.index(target_key)
        
        if g_idx == t_idx:
            return "correct"
        
        return "higher" if g_idx < t_idx else "lower"
    except ValueError:
        return "incorrect"

async def get_or_set_daily_target():
    """
    Busca si ya hay un personaje elegido para hoy. 
    Si no, elige uno aleatorio del catálogo de personajes.
    """
    hoy = datetime.now(timezone.utc).date().isoformat()
    
    # 1. Intentamos ver si algún usuario ya tiene un log hoy para sacar el ID del personaje
    existing = (
        supabase_db.table("daily_dle_logs")
        .select("target_character_id")
        .eq("completion_date", hoy)
        .limit(1)
        .execute()
    )
    
    if existing and existing.data:
        return existing.data[0]["target_character_id"]
    
    # 2. Si es el primer usuario del día, elegimos personaje aleatorio
    all_chars = supabase_db.table("daily_challenge_characters").select("id").execute()
    if not all_chars or not all_chars.data:
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

    # 1. Verifica que existe la misión dle_guess
    dle_cat = supabase_db.table("missions").select("id").eq("target_type", "dle_guess").maybe_single().execute()
    if not dle_cat or not dle_cat.data:
        print("[DLE] ERROR: No existe misión dle_guess en la tabla missions")
        raise HTTPException(status_code=500, detail="No existe misión dle_guess en la tabla de misiones")
    dle_config_id = dle_cat.data["id"]

    # 2. Obtiene el personaje del día (o lanza error si no hay catálogo)
    target_today_id = await get_or_set_daily_target()

    
    # 3. Busca si el usuario ya tiene una instancia de DLE (de hoy o de antes)
    check_dle = (
        supabase_db.table("hunter_missions")
        .select("id, started_at, missions!inner(id, target_type)")
        .eq("hunter_id", user_id)
        .eq("missions.target_type", "dle_guess")
        .execute()
    )

    existing_instance_id = None
    necesita_actualizar = True

    if check_dle and check_dle.data:
        instance = check_dle.data[0]
        existing_instance_id = instance["id"]
        fecha_instancia = datetime.fromisoformat(instance["started_at"]).date()
        if fecha_instancia == hoy_date:
            necesita_actualizar = False

    # 4. Si no tiene o es de un día anterior, actualizamos o insertamos
    if necesita_actualizar:
        mission_data = {
            "hunter_id": user_id,
            "mission_id": dle_config_id,
            "status": "active",
            "current_progress": 0,
            "started_at": hoy_dt.isoformat(),
            "completed_at": None
        }
        if existing_instance_id:
            supabase_db.table("hunter_missions").update(mission_data).eq("id", existing_instance_id).execute()
        else:
            supabase_db.table("hunter_missions").insert(mission_data).execute()


    # 5. Sincroniza el LOG (Minijuego) - SOLO INSERTA SI NO EXISTE, SINO ACTUALIZA
    existing_log = (
        supabase_db.table("daily_dle_logs")
        .select("id")
        .eq("user_id", user_id)
        .eq("mission_id", dle_config_id)
        .eq("completion_date", hoy_date.isoformat())
        .maybe_single()
        .execute()
    )
    log_data = {
        "user_id": user_id,
        "mission_id": dle_config_id,
        "target_character_id": target_today_id,
        "completion_date": hoy_date.isoformat(),
        "is_completed": False,
        "attempts": 0,
        "attempts_history": []
    }
    if existing_log and existing_log.data:
        # Actualiza el registro existente
        supabase_db.table("daily_dle_logs").update(log_data).eq("id", existing_log.data["id"]).execute()
    else:
        # Inserta nuevo registro
        supabase_db.table("daily_dle_logs").insert(log_data).execute()

    # 6. Devuelve el registro actualizado o recién creado
    log_res = (
        supabase_db.table("daily_dle_logs")
        .select("*, daily_challenge_characters!inner(*)")
        .eq("user_id", user_id)
        .eq("completion_date", hoy_date.isoformat())
        .maybe_single()
        .execute()
    )
    if not log_res or not log_res.data:
        print("[DLE] ERROR: No se pudo crear el registro daily_dle_logs para usuario nuevo")
        raise HTTPException(status_code=500, detail="No se pudo crear el registro daily_dle_logs para el usuario")
    return log_res