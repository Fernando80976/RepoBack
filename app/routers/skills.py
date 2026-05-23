from fastapi import APIRouter, Depends, HTTPException, Response
from app.core.config import supabase_db
from app.core.security import validate_hunter_session
from app.models.skills_schemas import UpgradeSkillSchema, UnlockSkillSchema

router = APIRouter(prefix="/hunter", tags=["Gremio de Cazadores"])


def _auto_unlock_skills_by_level(user_id: str, player_level: int) -> None:
    """
    Desbloquea automaticamente las skills cuyo min_level_required
    sea menor o igual al nivel actual del cazador.
    """
    try:
        eligible_res = (
            supabase_db.table("skills")
            .select("id, mana_cost, min_level_required")
            .lte("min_level_required", player_level)
            .execute()
        )
        eligible_skills = eligible_res.data or []
        if not eligible_skills:
            return

        existing_res = (
            supabase_db.table("hunter_skills")
            .select("skill_id")
            .eq("hunter_id", user_id)
            .execute()
        )
        existing_ids = {row["skill_id"] for row in (existing_res.data or [])}

        for skill in eligible_skills:
            if skill["id"] in existing_ids:
                continue
            try:
                supabase_db.table("hunter_skills").insert({
                    "hunter_id": user_id,
                    "skill_id": skill["id"],
                    "current_level": 1,
                    "current_mana_cost": int(skill.get("mana_cost") or 0),
                }).execute()
            except Exception:
                # No rompemos el endpoint de skills por una fila conflictiva.
                continue
    except Exception:
        # El autodesbloqueo es complementario; si falla, devolvemos skills igual.
        return

@router.get("/skills")
async def get_all_game_skills(
    response: Response,
    user_id: str = Depends(validate_hunter_session)
):
    # Evita que navegador/proxy reutilicen una respuesta vieja de skills.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    # 1. Obtener nivel actual del cazador
    profile_res = (
        supabase_db.table("profiles")
        .select("level")
        .eq("id", user_id)
        .single()
        .execute()
    )
    player_level = int((profile_res.data or {}).get("level") or 1)

    # Auto-desbloqueo al consultar skills (evita que nivel 1 aparezca sin habilidades).
    _auto_unlock_skills_by_level(user_id, player_level)

    # 2. Obtener TODAS las skills del catálogo general
    all_skills_res = supabase_db.table("skills").select("*").execute()
    all_skills = all_skills_res.data or []

    # 3. Obtener las skills desbloqueadas por el cazador
    unlocked_res = (
        supabase_db.table("hunter_skills")
        .select("skill_id, current_level, current_mana_cost")
        .eq("hunter_id", user_id)
        .execute()
    )
    unlocked_map = {
        item["skill_id"]: {
            "level": item["current_level"],
            "mana": item["current_mana_cost"]
        } for item in (unlocked_res.data or [])
    }

    # 4. Combinar la información
    for skill in all_skills:
        skill_id = skill["id"]
        is_unlocked = skill_id in unlocked_map

        skill["is_unlocked"] = is_unlocked

        if is_unlocked:
            skill["current_level"] = unlocked_map[skill_id]["level"]
            skill["current_mana_cost"] = unlocked_map[skill_id]["mana"]
            skill["next_upgrade_cost"] = skill["base_upgrade_sp_cost"] + skill["current_level"]
        else:
            skill["current_level"] = 0
            skill["current_mana_cost"] = skill["mana_cost"]
            skill["next_upgrade_cost"] = skill["base_upgrade_sp_cost"]

    return all_skills

@router.post("/unlock-skill")
async def unlock_skill(
    datos: UnlockSkillSchema,
    user_id: str = Depends(validate_hunter_session)
):
    """
    Desbloquea una habilidad si el cazador cumple el nivel mínimo requerido.
    Inserta una fila en hunter_skills con nivel 1 y el coste de mana base.
    """
    # 1. Comprobar que la skill existe y obtener su min_level_required
    skill_res = (
        supabase_db.table("skills")
        .select("id, min_level_required, mana_cost")
        .eq("id", datos.skill_id)
        .single()
        .execute()
    )
    if not skill_res.data:
        raise HTTPException(status_code=404, detail="ERR_SKILL_NOT_FOUND")

    skill = skill_res.data
    min_level = int(skill.get("min_level_required") or 1)

    # 2. Obtener nivel del cazador
    profile_res = (
        supabase_db.table("profiles")
        .select("level")
        .eq("id", user_id)
        .single()
        .execute()
    )
    player_level = int((profile_res.data or {}).get("level") or 1)

    if player_level < min_level:
        raise HTTPException(
            status_code=403,
            detail=f"ERR_LEVEL_TOO_LOW: necesitas nivel {min_level} (tienes {player_level})"
        )

    # 3. Comprobar que no esté ya desbloqueada
    already_res = (
        supabase_db.table("hunter_skills")
        .select("skill_id")
        .eq("hunter_id", user_id)
        .eq("skill_id", datos.skill_id)
        .execute()
    )
    if already_res.data:
        raise HTTPException(status_code=409, detail="ERR_SKILL_ALREADY_UNLOCKED")

    # 4. Insertar con nivel 1 y mana base
    supabase_db.table("hunter_skills").insert({
        "hunter_id": user_id,
        "skill_id": datos.skill_id,
        "current_level": 1,
        "current_mana_cost": int(skill.get("mana_cost") or 0),
    }).execute()

    return {
        "status": "success",
        "message": "Habilidad desbloqueada correctamente",
        "skill_id": datos.skill_id,
        "current_level": 1,
    }


@router.post("/upgrade-skill")
async def upgrade_skill(
    datos: UpgradeSkillSchema,
    user_id: str = Depends(validate_hunter_session)
):
    """
    Endpoint para subir de nivel una habilidad específica.
    Llama a la función atómica en Supabase.
    """
    # Llamamos a la función RPC que acabamos de crear
    rpc_res = supabase_db.rpc('upgrade_hunter_skill_atomic', {
        'p_hunter_id': user_id,
        'p_skill_id': datos.skill_id
    }).execute()

    if hasattr(rpc_res, 'error') and rpc_res.error:
        raise Exception(rpc_res.error['message'])

    # Si la base de datos lanza un RAISE EXCEPTION, 
    # postgrest (y por ende la librería de python) devolverá un error que tu 
    # handler unificado debería capturar.
    
    return {
        "status": "success",
        "message": "Habilidad mejorada correctamente",
        "skill_data": rpc_res.data[0]
    }
