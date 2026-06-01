from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from app.core.security import validate_hunter_session
from app.utils.game_logic import check_level_up
from app.core.config import supabase_db
from app.utils.logic_dle import sync_daily_dle_mission
from app.utils.flatten_data import flatten_mission_data
from app.utils.inventory_manager import add_item_to_inventory
from app.routers.dungeons import _auto_assign_dungeon_missions

router = APIRouter(prefix="/hunter", tags=["Quests"])

def resolve_reward_items_with_names(reward_items: list[dict] | None) -> list[dict]:
    """
    Normaliza reward_items y añade el nombre del catálogo a cada item.
    """
    normalized_rewards = []
    for entry in reward_items or []:
        if not isinstance(entry, dict):
            continue

        item_id = entry.get("item_id")
        quantity = int(entry.get("quantity") or 0)
        if item_id is None or quantity <= 0:
            continue

        normalized_rewards.append({
            "item_id": int(item_id),
            "quantity": quantity
        })

    if not normalized_rewards:
        return []

    item_ids = list({r["item_id"] for r in normalized_rewards})
    catalog_res = (
        supabase_db.table("items")
        .select("id, name, type")
        .in_("id", item_ids)
        .execute()
    )

    catalog_map = {int(row["id"]): row for row in catalog_res.data or []}
    missing_ids = [item_id for item_id in item_ids if item_id not in catalog_map]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ERR_MISSION_REWARD_ITEM_NOT_FOUND",
                "missing_item_ids": missing_ids,
            },
        )

    enriched_items = []
    for reward in normalized_rewards:
        item_data = catalog_map[reward["item_id"]]
        item_name = item_data.get("name")
        if isinstance(item_name, dict):
            item_name = item_name.get("es") or item_name.get("en") or str(item_name)

        enriched_items.append({
            "item_id": reward["item_id"],
            "quantity": reward["quantity"],
            "name": item_name,
            "type": item_data.get("type"),
        })

    return enriched_items

# --- ENDPOINTS ---

@router.get("/missions")
async def get_hunter_missions(user_id: str = Depends(validate_hunter_session)):

    target_today_id = await sync_daily_dle_mission(user_id)

    dungeons_res = supabase_db.table("dungeons").select("*").order("id").execute()
    dungeons = dungeons_res.data or []

    profile_res = (
        supabase_db.table("profiles")
        .select("level")
        .eq("id", user_id)
        .single()
        .execute()
    )
    player_level = int((profile_res.data or {}).get("level") or 1)

    _auto_assign_dungeon_missions(user_id, player_level, dungeons)

    res = (
        supabase_db.table("hunter_missions")
        .select("""
            id, current_progress, status, started_at, completed_at,
            missions (
                id, title, description, mission_type, target_type,
                target_value, reward_exp, reward_gold, reward_items
            )
        """)
        .eq("hunter_id", user_id)
        .order("started_at", desc=True)
        .execute()
    )

    missions = res.data or []
    for entry in missions:
        entry["missions"]["reward_items"] = resolve_reward_items_with_names(
            entry.get("missions", {}).get("reward_items")
        )

    return [flatten_mission_data(item, target_today_id) for item in missions]

@router.post("/missions/{instance_id}/claim")
async def claim_mission_reward(instance_id: int, user_id: str = Depends(validate_hunter_session)):

    # 1. Obtener instancia
    mission_res = (
        supabase_db.table("hunter_missions")
        .select("*, missions(target_value, reward_gold, reward_exp, reward_items)")
        .eq("id", instance_id)
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )

    instance = mission_res.data
    if not instance:
        print(404, "Misión no encontrada.")
        raise HTTPException(status_code=404, detail="ERR_MISSION_NOT_FOUND")

    # 2. Validaciones de seguridad
    if instance["status"] == "claimed":
        print(400, "Esta recompensa ya ha sido reclamada.")
        raise HTTPException(status_code=400, detail="ERR_REWARD_ALREADY_CLAIMED")

    if instance["status"] != "completed":
        print(400, "La misión aún no ha sido completada.")
        raise HTTPException(status_code=400, detail="ERR_MISSION_NOT_COMPLETED")
    
    if instance["current_progress"] < instance["missions"]["target_value"]:
        print(400, "Progreso insuficiente para reclamar.")
        raise HTTPException(status_code=400, detail="ERR_MISSION_INSUFFICIENT_PROGRESS")

    # 3. Obtener perfil y ganancias básicas
    profile_res = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute()
    profile = profile_res.data or {}
    exp_gain = instance["missions"].get("reward_exp", 0)
    gold_gain = instance["missions"].get("reward_gold", 0)

    # 4. Resolver y enriquecer reward_items (usa la función helper)
    reward_items = resolve_reward_items_with_names(instance["missions"].get("reward_items"))

    # 5. Conceder items y preparar lista de granted_items
    granted_items = []
    for reward in reward_items:
        add_item_to_inventory(user_id, reward["item_id"], reward["quantity"])
        granted_items.append({
            "item_id": reward["item_id"],
            "name": reward.get("name"),
            "type": reward.get("type"),
            "quantity": reward["quantity"],
        })

    # 6. Aplicar ganancias al perfil
    profile["experience"] = int(profile.get("experience", 0)) + int(exp_gain)
    profile["gold"] = int(profile.get("gold", 0)) + int(gold_gain)

    # 7. Lógica de level up
    level_up_data = check_level_up(profile)

    update_data = {
        "gold": profile["gold"],
        "experience": profile["experience"],
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    if level_up_data:
        update_data.update(level_up_data)

    # 8. Persistir cambios (perfil y marcar misión reclamada)
    supabase_db.table("profiles").update(update_data).eq("id", user_id).execute()
    supabase_db.table("hunter_missions").update({"status": "claimed"}).eq("id", instance_id).execute()

    # 9. Calcular niveles ganados de forma segura
    prev_level = int(profile.get("level", 0))
    new_level = int(update_data.get("level", prev_level))
    levels_gained = (new_level - prev_level) if level_up_data else 0

    # 10. Respuesta
    return {
        "status": "success",
        "leveled_up": level_up_data is not None,
        "gains": {
            "gold": gold_gain,
            "exp": exp_gain,
            "items": granted_items,
            "levels_gained": levels_gained
        },
        "current_state": {
            "level": new_level,
            "gold": update_data["gold"]
        }
    }

@router.patch("/missions/{instance_id}/progress")
async def update_mission_progress(
    instance_id: int, 
    increment: int = 1, 
    complete_max: bool = False, # Nuevo parámetro opcional
    user_id: str = Depends(validate_hunter_session)
):
    """
    Sube el progreso. Si complete_max es True, iguala el progreso al target_value.
    """
    
    # 1. Obtener la misión y su objetivo
    res = (
        supabase_db.table("hunter_missions")
        .select("current_progress, status, missions(target_value)")
        .eq("id", instance_id)
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )
    
    if not res.data:
        raise HTTPException(status_code=404, detail="Misión no encontrada")
    
    mission_data = res.data
    target = mission_data["missions"]["target_value"]
    
    # 2. Validar si ya está activa
    if mission_data["status"] != "active":
        raise HTTPException(status_code=400, detail=f"La misión no está activa")

    # 3. Lógica de incremento o completado máximo
    if complete_max:
        new_progress = target
    else:
        new_progress = mission_data["current_progress"] + increment
    
    # 4. Determinar si se ha completado
    new_status = "active"
    completed_at = None
    
    if new_progress >= target:
        new_progress = target 
        new_status = "completed"
        completed_at = datetime.now(timezone.utc).isoformat()

    # 5. Actualizar en Supabase
    supabase_db.table("hunter_missions").update({
        "current_progress": int(new_progress), # Aseguramos entero
        "status": new_status,
        "completed_at": completed_at
    }).eq("id", instance_id).execute()

    return {
        "status": "success",
        "new_progress": new_progress,
        "is_completed": new_status == "completed"
    }