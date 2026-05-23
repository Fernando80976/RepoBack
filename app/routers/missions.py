from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from app.core.security import validate_hunter_session
from app.utils.game_logic import check_level_up
from app.core.config import supabase_db
from app.utils.logic_dle import sync_daily_dle_mission
from app.utils.flatten_data import flatten_mission_data
from app.utils.inventory_manager import add_item_to_inventory

router = APIRouter(prefix="/hunter", tags=["Quests"])


# --- ENDPOINTS ---

@router.get("/missions")
async def get_hunter_missions(user_id: str = Depends(validate_hunter_session)):
   
    target_today_id = await sync_daily_dle_mission(user_id) # Nos aseguramos de que el DLE esté sincronizado antes de listar misiones

    # 1. CONSULTA FINAL (Sin cambios, pero ahora garantizamos limpieza)
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

    return [flatten_mission_data(item, target_today_id) for item in res.data]

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

    # 2. Validaciones de Seguridad
    if instance["status"] == "claimed":
        print(400, "Esta recompensa ya ha sido reclamada.")
        raise HTTPException(status_code=400, detail="ERR_REWARD_ALREADY_CLAIMED")

    if instance["status"] != "completed":
        print(400, "La misión aún no ha sido completada.")
        raise HTTPException(status_code=400, detail="ERR_MISSION_NOT_COMPLETED")
    
    if instance["current_progress"] < instance["missions"]["target_value"]:
        print(400, "Progreso insuficiente para reclamar.")
        raise HTTPException(status_code=400, detail="ERR_MISSION_INSUFFICIENT_PROGRESS")

    # 3. Obtener Perfil y Calcular Recompensas
    profile = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute().data

    exp_gain = instance["missions"].get("reward_exp", 0)
    gold_gain = instance["missions"].get("reward_gold", 0)
    reward_items = instance["missions"].get("reward_items") or []

    # 3.1 Validar y resolver recompensas de items contra el catalogo
    normalized_rewards = []
    for entry in reward_items:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        quantity = int(entry.get("quantity") or 0)
        if item_id is None or quantity <= 0:
            continue
        normalized_rewards.append({"item_id": int(item_id), "quantity": quantity})

    item_ids = list({r["item_id"] for r in normalized_rewards})
    catalog_rows = []
    if item_ids:
        catalog_res = (
            supabase_db.table("items")
            .select("id, name, type")
            .in_("id", item_ids)
            .execute()
        )
        catalog_rows = catalog_res.data or []

    catalog_map = {int(row["id"]): row for row in catalog_rows}
    missing_ids = [item_id for item_id in item_ids if item_id not in catalog_map]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ERR_MISSION_REWARD_ITEM_NOT_FOUND",
                "missing_item_ids": missing_ids,
            },
        )

    granted_items = []
    for reward in normalized_rewards:
        item_id = reward["item_id"]
        qty = reward["quantity"]
        add_item_to_inventory(user_id, item_id, qty)

        item_data = catalog_map[item_id]
        item_name = item_data.get("name")
        if isinstance(item_name, dict):
            item_name = item_name.get("es") or item_name.get("en") or str(item_name)

        granted_items.append({
            "item_id": item_id,
            "name": item_name,
            "type": item_data.get("type"),
            "quantity": qty,
        })

    profile["experience"] += exp_gain
    profile["gold"] += gold_gain

    # 4. Lógica de Level Up
    level_up_data = check_level_up(profile)

    update_data = {
        "gold": profile["gold"],
        "experience": profile["experience"],
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    if level_up_data:
        update_data.update(level_up_data)


    # 5. Ejecutar cambios en Base de Datos (Atomic Update)
    supabase_db.table("profiles").update(update_data).eq("id", user_id).execute()
    supabase_db.table("hunter_missions").update({"status": "claimed"}).eq("id", instance_id).execute()

    return {
        "status": "success",
        "leveled_up": level_up_data is not None,
        "gains": {
            "gold": gold_gain,
            "exp": exp_gain,
            "items": granted_items,
            "levels_gained": (update_data["level"] - profile["level"]) if level_up_data else 0
        },
        "current_state": {
            "level": update_data.get("level", profile["level"]),
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