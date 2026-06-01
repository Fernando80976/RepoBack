from fastapi import APIRouter, HTTPException, Depends
from app.core.config import supabase_db
from app.core.security import validate_hunter_session
from app.models.inventory_schemas import EquipRequest
from app.utils.equipment_stats import get_equipment_stat_bonuses, persist_effective_hp_mp

router = APIRouter(prefix="/inventory", tags=["Inventario"])

@router.post("/use_potion/{inventory_id}")
async def use_potion(inventory_id: int, user_id: str = Depends(validate_hunter_session)):
    """
    Usa una poción del inventario, aplicando el efecto según el tipo y cantidad (incluye fatiga).
    """
    
    from app.utils.battle.combat import _use_potion
    # Obtener datos del jugador (incluye fatiga si existe)
    profile_res = supabase_db.table("profiles").select("id, hp_current, hp_max, mp_current, mp_max, fatigue, fatigue_max").eq("id", user_id).single().execute()
    profile = profile_res.data
    if not profile:
        raise HTTPException(status_code=404, detail="ERR_PROFILE_NOT_FOUND")

    # Estado simulado para la función de poción
    state = {
        "player": {
            "hp": int(profile.get("hp_current") or 0),
            "max_hp": int(profile.get("hp_max") or 0),
            "mp": int(profile.get("mp_current") or 0),
            "max_mp": int(profile.get("mp_max") or 0),
            "fatigue": int(profile.get("fatigue") or 0),
            "max_fatigue": int(profile.get("fatigue_max") or 0),
            "potions": []
        },
        "log": []
    }
    result = _use_potion(state, user_id, inventory_id)
    if not result:
    # Mapear el mensaje del log a un código de error
        error_msg = state["log"][-1] if state["log"] else "ERR_USE_POTION_FAILED"
        error_code = "ERR_NO_NEED_POTION" if "No necesitas" in error_msg else "ERR_USE_POTION_FAILED"
        raise HTTPException(status_code=400, detail=error_code)

    # Actualizar los valores de HP, MP y Fatiga en el perfil si corresponde
    new_hp = state["player"].get("hp", profile.get("hp_current"))
    new_mp = state["player"].get("mp", profile.get("mp_current"))
    new_fatigue = state["player"].get("fatigue", profile.get("fatigue"))
    update_fields = {"hp_current": new_hp, "mp_current": new_mp}
    # Solo actualiza fatiga si el campo existe en el perfil
    if "fatigue" in profile:
        update_fields["fatigue"] = new_fatigue
    supabase_db.table("profiles").update(update_fields).eq("id", user_id).execute()

    return {
        "status": "success",
        "log": state["log"],
        "hp": new_hp,
        "mp": new_mp,
        "fatigue": new_fatigue
    }

@router.get("/")
async def get_hunter_inventory(user_id: str = Depends(validate_hunter_session)):
    """
    Obtiene todos los items del inventario del cazador logueado,
    incluyendo los detalles de cada item (nombre, stats, etc.)
    """
    # Usamos la sintaxis de Supabase para traer datos de la tabla relacionada 'items'
    # Esto es equivalente a un JOIN en SQL.
    res = (
        supabase_db.table("inventory")
        .select("id, quantity, items(*)")
        .eq("hunter_id", user_id)
        .execute()
    )
    return res.data

@router.get("/equipment")
async def get_hunter_equipment(user_id: str = Depends(validate_hunter_session)):
    res = (
        supabase_db.table("hunter_equipment")
        .select("""
            head:inventory!head_id(id, items(*)),
            chest:inventory!chest_id(id, items(*)),
            pants:inventory!pants_id(id, items(*)),
            boots:inventory!boots_id(id, items(*)),
            main_hand:inventory!main_hand_id(id, items(*)),
            off_hand:inventory!off_hand_id(id, items(*)),
            accessory:inventory!accessory_id(id, items(*))
        """)
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )

    if not res.data:
        # Cambiado de "Equipo no encontrado" a código
        raise HTTPException(status_code=404, detail="ERR_EQUIPMENT_NOT_FOUND")

    # --- PROCESAMIENTO PARA MEJORAR EL FRONT ---
    final_equipment = {}
    for slot, data in res.data.items():
        if data and "items" in data:
            # "Aplanamos" la estructura: subimos los datos de 'items' un nivel
            item_info = data["items"]
            final_equipment[slot] = {
                "inventory_id": data["id"],
                "item_id": item_info["id"],
                "name": item_info["name"],
                "type": item_info["type"],
                "slot_type": item_info["slot_type"],
                "rarity": item_info["rarity"],
                "stat_type": item_info["stat_type"],
                "stat_value": item_info["stat_value"],
                "image_key": item_info.get("image_key")
            }
        else:
            # Si el slot está vacío, devolvemos null de forma clara
            final_equipment[slot] = None

    return final_equipment

@router.post("/equip")
async def equip_item(req: EquipRequest, user_id: str = Depends(validate_hunter_session)):
    # 1. Obtener información del ítem
    res = (
        supabase_db.table("inventory")
        .select("id, items(type, slot_type)")
        .eq("id", req.inventory_id)
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="ERR_ITEM_NOT_IN_INVENTORY")

    db_item = res.data["items"]
    requested_slot = req.slot 
    allowed_slot = db_item["slot_type"]

    # 2. Validación de lógica de slots
    # Renombramos 'is_valid_dual' a 'is_valid_either' para no confundirlo con el nuevo tipo 'dual_hand'
    is_valid_either = (allowed_slot == "either_hand" and requested_slot in ["main_hand", "off_hand"])
    is_exact_match = (allowed_slot == requested_slot)
    
    # Si es dual_hand, permitimos que el front mande "main_hand" o "both", nosotros lo forzaremos en ambas
    is_dual_weapon = (allowed_slot == "dual_hand") 

    if not (is_valid_either or is_exact_match or is_dual_weapon):
        raise HTTPException(status_code=400, detail="ERR_INVALID_SLOT_FOR_ITEM")

    # 3. Capturar bonuses ANTES de cambiar el equipo
    old_bonuses = get_equipment_stat_bonuses(user_id)

    # 4. Consultar el equipo actual del cazador (necesario para la lógica de reemplazo)
    current_eq_res = (
        supabase_db.table("hunter_equipment")
        .select("main_hand_id, off_hand_id")
        .eq("hunter_id", user_id)
        .maybe_single()
        .execute()
    )
    current_eq = current_eq_res.data if current_eq_res.data else {}

    # 5. Preparar los datos a actualizar
    update_data = {
        "hunter_id": user_id
    }

    # --- LÓGICA DE ASIGNACIÓN Y DESEQUIPADO ---
    if allowed_slot == "dual_hand":
        # Un arma de dos manos ocupa ambos slots obligatoriamente
        update_data["main_hand_id"] = req.inventory_id
        update_data["off_hand_id"] = req.inventory_id
    else:
        # Es un arma de una mano (o armadura si implementas más slots después)
        update_data[f"{requested_slot}_id"] = req.inventory_id

        # Lógica de conflicto para las manos
        if requested_slot in ["main_hand", "off_hand"]:
            other_hand = "off_hand" if requested_slot == "main_hand" else "main_hand"
            
            if current_eq:
                current_main = current_eq.get("main_hand_id")
                current_off = current_eq.get("off_hand_id")
                
                # Caso A: El ítem (either_hand) ya estaba en la otra mano, lo vaciamos (tu lógica de Swap original)
                was_in_other_hand = (current_eq.get(f"{other_hand}_id") == req.inventory_id)
                
                # Caso B: Había un arma dual equipada (mismo ID en ambas manos) y estamos metiendo una de 1 mano.
                had_dual_equipped = (current_main == current_off and current_main is not None)
                
                if was_in_other_hand or had_dual_equipped:
                    update_data[f"{other_hand}_id"] = None

    try:
        # Upsert insertará la fila si no existe o la actualizará si el hunter_id ya tiene equipo
        supabase_db.table("hunter_equipment").upsert(update_data).execute()
        
        # 6. Actualizar stats y persistir HP/MP
        new_bonuses = get_equipment_stat_bonuses(user_id)
        persist_effective_hp_mp(user_id, old_bonuses, new_bonuses)
        
        return {
            "status": "success",
            "message": "MSG_EQUIP_SUCCESS", 
            "equipped_at": "both_hands" if allowed_slot == "dual_hand" else requested_slot
        }
    except Exception as e:
        print(f"⚠️ [DB ERROR]: {str(e)}")
        raise HTTPException(status_code=500, detail="ERR_INTERNAL_DB_FAILURE")

@router.post("/unequip/{slot}")
async def unequip_item(slot: str, user_id: str = Depends(validate_hunter_session)):
    """
    Quita un objeto de un slot específico del cazador.
    Pone la columna correspondiente en hunter_equipment a NULL.
    Si el arma es de dos manos (dual_hand), limpia ambas manos.
    """
    # 1. Lista de slots permitidos para evitar que nos inyecten columnas maliciosas
    valid_slots = [
        "head", "chest", "pants", "boots", 
        "main_hand", "off_hand", "accessory"
    ]

    if slot not in valid_slots:
        raise HTTPException(status_code=400, detail="ERR_INVALID_SLOT_NAME")

    # 2. Capturar bonuses ANTES de desequipar
    old_bonuses = get_equipment_stat_bonuses(user_id)

    # 3. Preparamos el campo a actualizar por defecto (ej: {"head_id": None})
    update_field = {f"{slot}_id": None}

    try:
        # --- LÓGICA PARA ARMAS DUALES ---
        # Solo comprobamos si el slot que queremos vaciar es una de las manos
        if slot in ["main_hand", "off_hand"]:
            # Consultamos qué tiene equipado el cazador actualmente en las manos
            eq_res = (
                supabase_db.table("hunter_equipment")
                .select("main_hand_id, off_hand_id")
                .eq("hunter_id", user_id)
                .maybe_single()
                .execute()
            )
            
            if eq_res.data:
                main_id = eq_res.data.get("main_hand_id")
                off_id = eq_res.data.get("off_hand_id")
                
                # Si el ID de la mano principal coincide con el de la mano secundaria (y no están vacíos)
                # sabemos que es un arma "dual_hand", por lo que vaciamos ambas.
                if main_id and off_id and (main_id == off_id):
                    update_field["main_hand_id"] = None
                    update_field["off_hand_id"] = None

        # 4. Ejecutamos la actualización en la tabla hunter_equipment
        res = (
            supabase_db.table("hunter_equipment")
            .update(update_field)
            .eq("hunter_id", user_id)
            .execute()
        )

        # Verificar si el cazador existe o si la actualización afectó alguna fila
        if not res.data:
            raise HTTPException(status_code=404, detail="ERR_HUNTER_NOT_FOUND")

        # 5. Actualizar stats y persistir HP/MP
        new_bonuses = get_equipment_stat_bonuses(user_id)
        persist_effective_hp_mp(user_id, old_bonuses, new_bonuses)

    except HTTPException:
        # Importante: re-lanzamos la HTTPException (como el 404) para que no caiga en el bloque Exception genérico
        raise
    except Exception as e:
        print(f"⚠️ [DB ERROR] Error al desequipar: {e}")
        raise HTTPException(status_code=500, detail="ERR_INTERNAL_DB_FAILURE")

    return {
        "status": "success",
        "message": "MSG_UNEQUIP_SUCCESS",
        # Si update_field tiene 2 claves, significa que se vaciaron ambas manos
        "slot_vaciado": "both_hands" if len(update_field) > 1 else slot
    }

@router.post("/sell/{inventory_id}")
async def sell_item(inventory_id: int, user_id: str = Depends(validate_hunter_session)):
    # (Mantenemos la lógica de vender que ya tenías con códigos, 
    #  solo unificamos el estilo de respuesta de error)
    
    is_equipped = supabase_db.table("hunter_equipment") \
        .select("*") \
        .eq("hunter_id", user_id) \
        .or_(f"main_hand_id.eq.{inventory_id},off_hand_id.eq.{inventory_id},head_id.eq.{inventory_id},chest_id.eq.{inventory_id},pants_id.eq.{inventory_id},boots_id.eq.{inventory_id},accessory_id.eq.{inventory_id}") \
        .execute()

    if is_equipped.data:
        raise HTTPException(status_code=400, detail="ERR_ITEM_IS_EQUIPPED")

    res = (
        supabase_db.table("inventory")
        .select("id, quantity, items(price)")
        .eq("id", inventory_id)
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="ERR_ITEM_NOT_FOUND")

    slot = res.data
    item_price = slot["items"]["price"]
    
    # 2. Calcular el oro a recibir (ejemplo: 50% del precio original por cada unidad)
    sell_value = int((item_price * 0.5) * slot["quantity"])

    # 3. Obtener el oro actual del perfil para sumar
    profile_res = supabase_db.table("profiles").select("gold").eq("id", user_id).single().execute()
    current_gold = profile_res.data["gold"]
    new_balance = current_gold + sell_value

    try:
        supabase_db.table("profiles").update({"gold": new_balance}).eq("id", user_id).execute()
        supabase_db.table("inventory").delete().eq("id", inventory_id).execute()

        return {
            "status": "success", 
            "gold_earned": sell_value,
            "new_balance": new_balance,
            "message": "MSG_ITEM_SOLD_SUCCESS"
        }
    except Exception:
        raise HTTPException(status_code=500, detail="ERR_INTERNAL_DB_FAILURE")