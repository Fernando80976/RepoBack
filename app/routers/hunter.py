from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from app.core.config import supabase_db
from app.models import UpdateStatsSchema, UpdateActiveTitleSchema, SelectClassSchema
from app.core.security import validate_hunter_session
from app.utils.equipment_stats import get_equipment_stat_bonuses, apply_equipment_stats #fer

router = APIRouter(prefix="/hunter", tags=["Gremio de Cazadores"])


def _auto_unlock_titles_by_level(user_id: str, player_level: int) -> None:
    """
    Desbloquea automaticamente los titulos cuyo min_level_required
    sea menor o igual al nivel actual del cazador.
    """
    try:
        eligible_res = (
            supabase_db.table("titles")
            .select("id, min_level_required")
            .lte("min_level_required", player_level)
            .execute()
        )
        eligible_titles = eligible_res.data or []
        if not eligible_titles:
            return

        existing_res = (
            supabase_db.table("hunter_titles")
            .select("title_id")
            .eq("hunter_id", user_id)
            .execute()
        )
        existing_ids = {row["title_id"] for row in (existing_res.data or [])}

        now = datetime.now(timezone.utc).isoformat()
        for title in eligible_titles:
            if title["id"] in existing_ids:
                continue
            try:
                supabase_db.table("hunter_titles").insert({
                    "hunter_id": user_id,
                    "title_id": title["id"],
                    "unlocked_at": now,
                }).execute()
            except Exception:
                # No rompemos el endpoint por una fila conflictiva.
                continue
    except Exception:
        # El autodesbloqueo es complementario; si falla, devolvemos titulos igual.
        return


# @router.get("/profile")
# async def get_my_profile(user_id: str = Depends(validate_hunter_session)):
#     # Si supabase falla, el Handler Global enviará el mensaje de error y el endpoint

#     # # 1. Obtener cliente (reutilizado)
#     # profile = supabase_db.table("profiles").select("*").eq("id", user_id).single().execute()
#     # return profile.data

#     profile = supabase_db.table("profiles").select(
#         "*,"
#         "player_classes(name, target_stat, stats_bonus)" 
#     ).eq("id", user_id).single().execute().data
#     print("Perfil base del cazador:", profile)
#     bonuses = get_equipment_stat_bonuses(user_id)
#     return apply_equipment_stats(profile, bonuses)

@router.get("/profile")
async def get_my_profile(user_id: str = Depends(validate_hunter_session)):
    # 1. Obtenemos el perfil incluyendo la relación con player_classes
    # Traemos el nombre (JSONB), el stat objetivo y el bonus.
    res = supabase_db.table("profiles").select(
        "*, player_classes(name, target_stat, stats_bonus),active_title:titles!profiles_active_title_id_fkey(stats_effect,effect)"
    ).eq("id", user_id).single().execute()
    
    profile_raw = res.data
    profile_raw["titles"] = profile_raw.get("active_title") or {}
    
    # 2. Calculamos los bonus de equipo (Lógica que ya tienes)
    bonuses = get_equipment_stat_bonuses(user_id)
    
    # 3. Aplicamos stats efectivas
    # 'enriched' contiene los cálculos base + bonus
    enriched = apply_equipment_stats(profile_raw, bonuses)
    
    # --- PROCESAMIENTO DE CLASE (Mapping) ---
    # Extraemos el objeto de la clase que viene de la relación
    class_data = profile_raw.get("player_classes") or {}
    
    enriched["class_name"] = class_data.get("name")
    
    # Eliminamos el objeto original de la relación para que el JSON sea más limpio
    if "player_classes" in enriched:
        del enriched["player_classes"]
        
    return enriched

@router.post("/rest")
async def hunter_rest(user_id: str = Depends(validate_hunter_session)):
    """
    Descansa al cazador: restaura HP y MP al máximo y reinicia la fatiga a 0.
    """
    profile_res = supabase_db.table("profiles").select("hp_max, mp_max").eq("id", user_id).single().execute()
    profile = profile_res.data

    supabase_db.table("profiles").update({
        "hp_current": profile["hp_max"],
        "mp_current": profile["mp_max"],
        "fatigue": 0,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", user_id).execute()

    return {
        "status": "success",
        "message": "MSG_REST_COMPLETE",
        "hp_current": profile["hp_max"],
        "mp_current": profile["mp_max"],
        "fatigue": 0
    }

@router.post("/update-stats")
async def update_hunter_stats(datos: UpdateStatsSchema, user_id: str = Depends(validate_hunter_session)):
    # La lógica de validación y atomicidad está en la BBDD
    # Si la BBDD lanza un error, FastAPI lo mandará directamente al sistema_unified_handler
    rpc_res = supabase_db.rpc('update_hunter_stats_atomic', {
        'p_user_id': user_id,
        'p_str': datos.strength,
        'p_agi': datos.agility,
        'p_vit': datos.vitality,
        'p_int': datos.intelligence,
        'p_sen': datos.sense
    }).execute()

    # Si llega a esta línea, es que no hubo excepción
    return {
        "status": "success", 
        "new_stats": rpc_res.data
    }

@router.get("/titles")
async def get_all_game_titles(user_id: str = Depends(validate_hunter_session)):
    # 1. Obtener nivel actual del cazador
    profile_res = (
        supabase_db.table("profiles")
        .select("level")
        .eq("id", user_id)
        .single()
        .execute()
    )
    player_level = int((profile_res.data or {}).get("level") or 1)

    # Auto-desbloqueo por nivel al consultar titulos.
    _auto_unlock_titles_by_level(user_id, player_level)

    # 2. Obtener TODOS los titulos del catalogo
    all_titles_res = supabase_db.table("titles").select("*").execute()
    all_titles = all_titles_res.data or []

    # 3. Obtener los IDs de los titulos que el cazador ya desbloqueo
    unlocked_res = (
        supabase_db.table("hunter_titles")
        .select("title_id")
        .eq("hunter_id", user_id)
        .execute()
    )
    # Creamos un set de IDs para búsqueda rápida: {1, 2, 5}
    unlocked_ids = {item["title_id"] for item in (unlocked_res.data or [])}

    # 4. Combinar la informacion
    # Añadimos la propiedad 'is_unlocked' a cada objeto
    for title in all_titles:
        title["is_unlocked"] = title["id"] in unlocked_ids

    return all_titles

@router.patch("/active-title")
async def update_active_title(datos: UpdateActiveTitleSchema, user_id: str = Depends(validate_hunter_session)):
    """
    Cambia el título activo del cazador. 
    Verifica primero que el cazador posea el título en la tabla intermedia.
    """
    
    # 1. VERIFICACIÓN DE SEGURIDAD: ¿El cazador tiene este título desbloqueado?
    # Consultamos la tabla intermedia hunter_titles
    check_ownership = (
        supabase_db.table("hunter_titles")
        .select("*")
        .eq("hunter_id", user_id)
        .eq("title_id", datos.title_id)
        .execute()
    )

    if not check_ownership.data:
        print(403, "No has desbloqueado este título todavía.")
        raise HTTPException(status_code=403, detail="ERR_TITLE_LOCKED")

    # 2. ACTUALIZAR el active_title_id en el perfil del cazador
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
        "message": "MSG_TITLE_EQUIPPED",
        "active_title_id": datos.title_id
    }

@router.get("/classes")
async def get_available_classes():
    """
    Devuelve todas las clases disponibles en el catálogo para que el usuario elija.
    """
    classes_res = supabase_db.table("player_classes").select("*").execute()
    return classes_res.data

@router.post("/select-class")
async def select_hunter_class(datos: SelectClassSchema, user_id: str = Depends(validate_hunter_session)):
    """
    Asigna una clase al cazador y aplica el bonus inicial de estadísticas.
    """
    # 1. Verificar si el usuario ya tiene una clase (Evitar que elijan dos veces)
    current_profile = supabase_db.table("profiles").select("class_id").eq("id", user_id).single().execute()
    
    if current_profile.data.get("class_id") is not None:
        raise HTTPException(status_code=400, detail="ERR_CLASS_ALREADY_SELECTED")

    # 2. Obtener los beneficios de la clase elegida
    class_info = supabase_db.table("player_classes").select("*").eq("id", datos.class_id).single().execute()
    
    if not class_info.data:
        raise HTTPException(status_code=404, detail="ERR_CLASS_NOT_FOUND")

    target_stat = class_info.data["target_stat"] # Ej: 'strength'
    bonus_value = class_info.data["stats_bonus"] # Ej: 5

    # 3. Actualizar el perfil del usuario: 
    # Seteamos el class_id y sumamos el bonus a la estadística correspondiente
    # Nota: Usamos una consulta para obtener el valor actual y sumarlo
    # profile_data = supabase_db.table("profiles").select(target_stat).eq("id", user_id).single().execute()
    # new_stat_value = profile_data.data[target_stat] + bonus_value

    update_res = supabase_db.table("profiles").update({
        "class_id": datos.class_id,
        # target_stat: new_stat_value,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", user_id).execute()

    return {
        "status": "success",
        "message": "MSG_CLASS_AWAKENED",
        "class_name": class_info.data["name"],
        "bonus_applied": f"+{bonus_value} {target_stat}"
    }

@router.get("/check-class")
async def check_player_class(user_id: str = Depends(validate_hunter_session)):
    """
    Verifica de forma rápida si el cazador ya ha despertado (elegido una clase).
    Retorna True si tiene clase, False si no.
    """
    # Consultamos solo la columna class_id para minimizar el tráfico de datos
    result = supabase_db.table("profiles").select("class_id").eq("id", user_id).single().execute()
    
    # Comprobamos si class_id tiene un valor asignado
    # .get() evita errores si por algún motivo la columna no viniera en el json
    has_class = result.data.get("class_id") is not None
    return {
        "has_class": has_class
    }