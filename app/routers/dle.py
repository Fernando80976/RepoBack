from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone, date
from app.core.security import validate_hunter_session
from app.utils.game_logic import check_level_up
from app.core.config import supabase_db
from app.utils.logic_dle import compare_ranks

router = APIRouter(prefix="/hunter", tags=["DailyChallengeDle"])

@router.post("/daily-challenge/guess/{characterId}")
async def process_dle_guess(characterId: int, user_id: str = Depends(validate_hunter_session)):
    hoy = datetime.now(timezone.utc).date().isoformat()
    ahora_timestamp = datetime.now(timezone.utc).isoformat()


    # 1. Obtener el log diario y el personaje objetivo (crearlo si no existe)
    log_res = (
        supabase_db.table("daily_dle_logs")
        .select("*, daily_challenge_characters!inner(*)")
        .eq("user_id", user_id)
        .eq("completion_date", hoy)
        .maybe_single()
        .execute()
    )
    if not log_res or not log_res.data:
        # Intentar crear el registro y volver a consultar
        from app.utils.logic_dle import sync_daily_dle_mission
        log_res = await sync_daily_dle_mission(user_id)
        if not log_res or not log_res.data:
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

    # 6. Si acierta, marcar la misión diaria como completada y dar recompensa
    rewards = None
    if is_correct:
        # Obtener la instancia de la misión dle_guess del usuario
        mission_res = (
            supabase_db.table("hunter_missions")
            .select("* , missions(reward_exp, reward_gold, reward_items, target_value)")
            .eq("hunter_id", user_id)
            .eq("mission_id", log_res.data["mission_id"])
            .maybe_single()
            .execute()
        )
        mission_instance = mission_res.data if mission_res else None
        if mission_instance:
            # Sumar progreso y marcar como completada
            supabase_db.table("hunter_missions").update({
                "status": "completed",
                "current_progress": mission_instance["missions"]["target_value"] if mission_instance["missions"].get("target_value") else 1,
                "completed_at": ahora_timestamp
            }).eq("id", mission_instance["id"]).execute()

            # Dar experiencia y oro
            profile_res = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute()
            profile = profile_res.data or {}
            exp_gain = mission_instance["missions"].get("reward_exp", 0)
            gold_gain = mission_instance["missions"].get("reward_gold", 0)

            # Dar items
            from app.routers.missions import resolve_reward_items_with_names
            reward_items = resolve_reward_items_with_names(mission_instance["missions"].get("reward_items"))
            granted_items = []
            from app.utils.inventory_manager import add_item_to_inventory
            for reward in reward_items:
                add_item_to_inventory(user_id, reward["item_id"], reward["quantity"])
                granted_items.append({
                    "item_id": reward["item_id"],
                    "name": reward.get("name"),
                    "type": reward.get("type"),
                    "quantity": reward["quantity"],
                })

            # Actualizar perfil
            profile["experience"] = int(profile.get("experience", 0)) + int(exp_gain)
            profile["gold"] = int(profile.get("gold", 0)) + int(gold_gain)
            from app.utils.game_logic import check_level_up
            level_up_data = check_level_up(profile)
            update_data = {
                "gold": profile["gold"],
                "experience": profile["experience"],
                "updated_at": ahora_timestamp
            }
            if level_up_data:
                update_data.update(level_up_data)
            supabase_db.table("profiles").update(update_data).eq("id", user_id).execute()

            rewards = {
                "exp": exp_gain,
                "gold": gold_gain,
                "items": granted_items
            }

    return {
        "correct": is_correct,
        "attempts": new_attempts,
        "comparison": comparison,
        "rewards": rewards if is_correct else None
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
    hoy = datetime.now(timezone.utc).date().isoformat()
    
    res = (
        supabase_db.table("daily_dle_logs")
        .select("is_completed, attempts_history")
        .eq("user_id", user_id)
        .eq("completion_date", hoy)
        .maybe_single()
        .execute()
    )
    if res and res.data:
        return res.data
    # Si no existe, sincroniza misión y log correctamente
    from app.utils.logic_dle import sync_daily_dle_mission
    import asyncio
    # Ejecuta la función asíncrona para crear misión y log
    await sync_daily_dle_mission(user_id)
    # Vuelve a consultar el estado
    res2 = (
        supabase_db.table("daily_dle_logs")
        .select("is_completed, attempts_history")
        .eq("user_id", user_id)
        .eq("completion_date", hoy)
        .maybe_single()
        .execute()
    )
    if res2 and res2.data:
        return res2.data
    return {"is_completed": False, "attempts_history": []}