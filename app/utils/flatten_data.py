
def flatten_mission_data(item: dict, target_today_id: int = None) -> dict:
    """
    Transforma un registro anidado de hunter_missions + missions en un JSON plano.
    """
    # Extraemos el objeto anidado 'missions' (el catálogo)
    catalog_info = item.get("missions", {})
    
    # Construimos el JSON TOTAL (aplanado)
    return {
        # Datos de la instancia (progreso del jugador)
        "instance_id": item.get("id"),
        "status": item.get("status"),
        "current_progress": item.get("current_progress"),
        "started_at": item.get("started_at"),
        "completed_at": item.get("completed_at"),
        
        # Datos del catálogo (definición de la misión)
        "mission_id": catalog_info.get("id"),
        "title": catalog_info.get("title"),
        "description": catalog_info.get("description"),
        "mission_type": catalog_info.get("mission_type"),
        "target_type": catalog_info.get("target_type"),
        "target_value": catalog_info.get("target_value"),
        "reward_exp": catalog_info.get("reward_exp"),
        "reward_gold": catalog_info.get("reward_gold"),
        "reward_items": catalog_info.get("reward_items"),
        
        # Dato extra para la lógica de Solo Leveling (DLE)
        "daily_target_id": target_today_id if catalog_info.get("mission_type") == "daily" else None
    }