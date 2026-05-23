from app.core.config import supabase_db

def add_item_to_inventory(user_id: str, item_id: int, quantity: int = 1):
    """
    Lógica centralizada para añadir items.
    Si el item es de tipo 'potion' o 'material', hace UPSERT.
    Si es 'weapon' o 'armor', hace INSERT de una nueva instancia.
    """
    # 1. Consultamos el tipo de item en el catálogo
    item_res = supabase_db.table("items").select("type").eq("id", item_id).single().execute()
    item_type = item_res.data["type"]

    # 2. Definimos qué tipos son apilables
    stackable_types = ["potion", "material"]

    if item_type in stackable_types:
        # Lógica de APILAR (UPSERT)
        # Buscamos si ya tiene ese item_id
        existing = (
            supabase_db.table("inventory")
            .select("id, quantity")
            .eq("hunter_id", user_id)
            .eq("item_id", item_id)
            .execute()
        )

        if existing.data:
            # Si existe, sumamos a la fila actual
            current_inv_id = existing.data[0]["id"]
            new_qty = existing.data[0]["quantity"] + quantity
            supabase_db.table("inventory").update({"quantity": new_qty}).eq("id", current_inv_id).execute()
        else:
            # Si no existe, creamos la primera fila
            supabase_db.table("inventory").insert({
                "hunter_id": user_id,
                "item_id": item_id,
                "quantity": quantity
            }).execute()
    else:
        # Lógica de EQUIPO (INSTANCIAS ÚNICAS)
        # Creamos una fila nueva por cada unidad (normalmente cantidad será 1)
        for _ in range(quantity):
            supabase_db.table("inventory").insert({
                "hunter_id": user_id,
                "item_id": item_id,
                "quantity": 1
            }).execute()