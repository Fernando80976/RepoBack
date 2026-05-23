from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone, date
from app.core.security import validate_hunter_session
from app.utils.game_logic import check_level_up
from app.core.config import supabase_db
from app.utils.logic_dle import compare_ranks

router = APIRouter(prefix="/hunter", tags=["DailyChallengeDle"])

@router.post("/daily-challenge/guess/{characterId}")
async def process_dle_guess(characterId: int, user_id: str = Depends(validate_hunter_session)):
    hoy = date.today().isoformat()
    ahora_timestamp = datetime.now(timezone.utc).isoformat()

    # 1. Obtener el log diario y el personaje objetivo
    log_res = (
        supabase_db.table("daily_dle_logs")
        .select("*, daily_challenge_characters!inner(*)")
        .eq("user_id", user_id)
        .eq("completion_date", hoy)
        .single()
        .execute()
    )

    if not log_res.data:
        raise HTTPException(status_code=404, detail="No hay desafío activo para hoy")

    target_char = log_res.data["daily_challenge_characters"]

    # 2. Obtener los datos del personaje que el usuario ha intentado (guess)
    guess_char_res = (
        supabase_db.table("daily_challenge_characters")
        .select("*")
        .eq("id", characterId)
        .single()
        .execute()
    )
    guess_char = guess_char_res.data

    # 3. Construir la respuesta de comparación usando las nuevas Keys y Data
    # 'value' lleva el JSONB para que el Front elija el idioma
    # 'result' lleva la lógica de acierto/error/flecha
    comparison = {
        "race": {
            "value": guess_char["race_data"],
            "result": "correct" if guess_char["race_key"] == target_char["race_key"] else "incorrect"
        },
        "rank": {
            "value": guess_char["rank_data"],
            "result": compare_ranks(guess_char["rank_key"], target_char["rank_key"])
        },
        "class": {
            "value": guess_char["class_data"],
            "result": "correct" if guess_char["class_key"] == target_char["class_key"] else "incorrect"
        },
        "affiliation": {
            "value": guess_char["affiliation_data"],
            "result": "correct" if guess_char["affiliation_key"] == target_char["affiliation_key"] else "incorrect"
        },
        "image": guess_char["image_key"] # Útil para mostrar la miniatura en el historial
    }

    is_correct = (characterId == target_char["id"])
    new_attempts = log_res.data["attempts"] + 1

    # 4. Actualizar el historial de intentos
    nuevo_intento = {
        "character_id": characterId,
        "character_name": guess_char["name_data"], # Opcional: para facilitar debug
        "comparison": comparison
    }

    historial_actual = log_res.data.get("attempts_history") or []
    # Insertamos al principio para que el Front vea el último intento primero
    historial_actual.insert(0, nuevo_intento)

    # 5. Guardar en la DB (Log del DLE)
    supabase_db.table("daily_dle_logs").update({
        "attempts": new_attempts,
        "is_completed": is_correct,
        "attempts_history": historial_actual
    }).eq("id", log_res.data["id"]).execute()

    # 6. Si acierta, marcar la misión diaria como completada
    if is_correct:
        supabase_db.table("hunter_missions").update({
            "status": "completed",
            "current_progress": 1,
            "completed_at": ahora_timestamp
        }).eq("hunter_id", user_id).eq("mission_id", log_res.data["mission_id"]).execute()

    return {
        "correct": is_correct,
        "attempts": new_attempts,
        "comparison": comparison
    }

@router.get("/daily-challenge/characters")
async def get_all_characters(user_id: str = Depends(validate_hunter_session)):
    """
    Retorna el catálogo de personajes para el buscador del DLE.
    Adaptado a la estructura de name_data (JSONB) y rank_data (JSONB).
    """
    # Seleccionamos las columnas correctas según tu nueva tabla
    res = (
        supabase_db.table("daily_challenge_characters")
        .select("id, name_data, image_key, rank_data")
        .order("id") # Opcional: .order("name_data->>es") para orden alfabético
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="No hay personajes disponibles")
    
    return res.data

@router.get("/daily-challenge/status")
async def get_daily_status(user_id: str = Depends(validate_hunter_session)):
    hoy = date.today().isoformat()
    
    res = (
        supabase_db.table("daily_dle_logs")
        .select("is_completed, attempts_history")
        .eq("user_id", user_id)
        .eq("completion_date", hoy)
        .single()
        .execute()
    )
    
    return res.data or {"is_completed": False, "attempts_history": []}