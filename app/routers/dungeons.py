from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from app.core.config import supabase_db
from app.core.security import validate_hunter_session

router = APIRouter(prefix="/dungeons", tags=["Mazmorras"])


def _auto_assign_dungeon_missions(user_id: str, player_level: int, dungeons: list) -> None:
    """
    Sincroniza misiones de dungeon por nivel:
    - Asigna solo las de dungeons desbloqueadas.
    - Limpia asignaciones antiguas mal creadas (solo activas con progreso 0).
    """
    try:
        unlocked_dungeon_ids = {
            int(d["id"]) for d in dungeons
            if not d.get("min_level_required")  # NULL o 0 = siempre disponible
            or int(d["min_level_required"]) <= player_level
        }

        catalog_res = (
            supabase_db.table("missions")
            .select("id, dungeon_id, target_type")
            .eq("target_type", "complete_dungeon")
            .execute()
        )
        catalog = [m for m in (catalog_res.data or []) if m.get("dungeon_id") is not None]
        if not catalog:
            return

        # 1) Limpieza de misiones de dungeon fuera de nivel (legacy bug)
        all_dungeon_mission_ids = [m["id"] for m in catalog]
        hunter_instances_res = (
            supabase_db.table("hunter_missions")
            .select("id, status, current_progress, missions(dungeon_id, target_type)")
            .eq("hunter_id", user_id)
            .in_("mission_id", all_dungeon_mission_ids)
            .execute()
        )
        for inst in (hunter_instances_res.data or []):
            mission_data = inst.get("missions") or {}
            dungeon_id = mission_data.get("dungeon_id")
            if dungeon_id is None:
                continue

            is_locked_for_level = int(dungeon_id) not in unlocked_dungeon_ids
            is_safe_to_remove = (
                inst.get("status") == "active"
                and int(inst.get("current_progress") or 0) == 0
            )
            if is_locked_for_level and is_safe_to_remove:
                try:
                    supabase_db.table("hunter_missions").delete().eq("id", inst["id"]).execute()
                except Exception:
                    continue

        # 2) Asignar solo las misiones de dungeons desbloqueadas
        mission_list = [m for m in catalog if int(m["dungeon_id"]) in unlocked_dungeon_ids]
        if not mission_list:
            return

        mission_ids = [m["id"] for m in mission_list]
        existing_res = (
            supabase_db.table("hunter_missions")
            .select("mission_id")
            .eq("hunter_id", user_id)
            .in_("mission_id", mission_ids)
            .execute()
        )
        assigned_ids = {row["mission_id"] for row in (existing_res.data or [])}

        now = datetime.now(timezone.utc).isoformat()
        for mission in mission_list:
            if mission["id"] in assigned_ids:
                continue
            try:
                supabase_db.table("hunter_missions").insert({
                    "hunter_id": user_id,
                    "mission_id": mission["id"],
                    "current_progress": 0,
                    "status": "active",
                    "started_at": now,
                }).execute()
            except Exception:
                continue
    except Exception:
        return


@router.get("/")
async def get_all_dungeons(user_id: str = Depends(validate_hunter_session)):
    """Devuelve el catalogo completo de mazmorras."""
    res = supabase_db.table("dungeons").select("*").order("id").execute()
    dungeons = res.data or []

    profile_res = (
        supabase_db.table("profiles")
        .select("level")
        .eq("id", user_id)
        .single()
        .execute()
    )
    player_level = int((profile_res.data or {}).get("level") or 1)

    _auto_assign_dungeon_missions(user_id, player_level, dungeons)

    return dungeons