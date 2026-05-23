from fastapi import APIRouter, HTTPException, Depends
from app.core.config import supabase_db
from app.core.security import validate_hunter_session
from app.models.inventory_schemas import EquipRequest
from app.utils.equipment_stats import get_equipment_stat_bonuses, persist_effective_hp_mp

router = APIRouter(prefix="/inventory", tags=["Inventario"])

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
                "stat_value": item_info["stat_value"]
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
    is_valid_dual = (allowed_slot == "dual_hand" and requested_slot in ["main_hand", "off_hand"])
    is_exact_match = (allowed_slot == requested_slot)

    if not (is_valid_dual or is_exact_match):
        # Cambiado a código (el front puede manejar la lógica de mostrar qué slot falló)
        raise HTTPException(status_code=400, detail="ERR_INVALID_SLOT_FOR_ITEM")

    # 3. Capturar bonuses ANTES de cambiar el equipo
    old_bonuses = get_equipment_stat_bonuses(user_id)

    # 4. Actualización directa
    column_name = f"{requested_slot}_id"
    update_data = {
        "hunter_id": user_id,
        column_name: req.inventory_id
    }

    # --- LÓGICA DE INTERCAMBIO (SWAP) ---
    # Si el objeto es para las manos, verificamos que no esté ya en la otra mano
    if requested_slot in ["main_hand", "off_hand"]:
        # Determinar cuál es la "otra mano"
        other_hand = "off_hand" if requested_slot == "main_hand" else "main_hand"
        
        # Consultar el equipo actual del cazador
        current_eq = supabase_db.table("hunter_equipment") \
            .select("main_hand_id, off_hand_id") \
            .eq("hunter_id", user_id) \
            .single() \
            .execute()

        if current_eq.data:
            # Si el ID que quiero equipar ya está en la otra mano, la vaciamos
            if current_eq.data.get(f"{other_hand}_id") == req.inventory_id:
                update_data[f"{other_hand}_id"] = None
    
    try:
        supabase_db.table("hunter_equipment").upsert(update_data).execute()
        new_bonuses = get_equipment_stat_bonuses(user_id)
        persist_effective_hp_mp(user_id, old_bonuses, new_bonuses)
        return {
            "status": "success",
            "message": "MSG_EQUIP_SUCCESS", 
            "equipped_at": requested_slot
        }
    except Exception as e:
        print(f"⚠️ [DB ERROR]: {str(e)}")
        raise HTTPException(status_code=500, detail="ERR_INTERNAL_DB_FAILURE")

@router.post("/unequip/{slot}")
async def unequip_item(slot: str, user_id: str = Depends(validate_hunter_session)):
    """
    Quita un objeto de un slot específico del cazador.
    Pone la columna correspondiente en hunter_equipment a NULL.
    """
    # 1. Lista de slots permitidos para evitar que nos inyecten columnas maliciosas
    valid_slots = [
        "head", "chest", "pants", "boots", 
        "main_hand", "off_hand", "accessory"
    ]

    if slot not in valid_slots:
        # Cambiado a código
        raise HTTPException(status_code=400, detail="ERR_INVALID_SLOT_NAME")

    # 2. Capturar bonuses ANTES de desequipar
    old_bonuses = get_equipment_stat_bonuses(user_id)

    # 3. Preparamos el campo a actualizar (ej: {"head_id": None})
    update_field = {f"{slot}_id": None}

    try:
        # 4. Ejecutamos la actualización en la tabla hunter_equipment
        res = (
            supabase_db.table("hunter_equipment")
            .update(update_field)
            .eq("hunter_id", user_id)
            .execute()
        )

        # Opcional: Verificar si el cazador existe
        if not res.data:
            raise HTTPException(status_code=404, detail="ERR_HUNTER_NOT_FOUND")

        new_bonuses = get_equipment_stat_bonuses(user_id)
        persist_effective_hp_mp(user_id, old_bonuses, new_bonuses)

    except Exception as e:
        print(f"Error al desequipar: {e}")
        raise HTTPException(status_code=500, detail="ERR_INTERNAL_DB_FAILURE")

    return {
        "status": "success",
        "message": "MSG_UNEQUIP_SUCCESS",
        "slot_vaciado": slot
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