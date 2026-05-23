from fastapi import APIRouter, HTTPException, Depends
from app.core.config import supabase_db
from app.core.security import validate_hunter_session

router = APIRouter(prefix="/shop", tags=["Tienda"])


@router.get("/items")
async def get_shop_items(user_id: str = Depends(validate_hunter_session)):
    """
    Devuelve todos los items disponibles en la tienda.
    """
    items_res = supabase_db.table("items").select("*").execute()
    return items_res.data

@router.post("/buy/{item_id}")
async def buy_item(item_id: int, user_id: str = Depends(validate_hunter_session)):
    # 1. Obtenemos datos del item (precio y tipo)
    item_res = supabase_db.table("items").select("price, type").eq("id", item_id).single().execute()
    
    if not item_res.data:
        raise HTTPException(status_code=404, detail="ERR_SHOP_ITEM_NOT_FOUND")

    # Ejecutamos el RPC sin preocuparnos de si es stackable o no
    rpc_res = supabase_db.rpc('comprar_item', {
        'p_user_id': user_id,
        'p_item_id': item_id,
    }).execute()
        
    # rpc_res.data devuelve una lista con el resultado de la función
    resultado = rpc_res.data[0]

    return {
        "status": "success",
        "message": "MSG_SHOP_PURCHASE_SUCCESS",
        
        "item_id": item_id,
        "gold_spent": resultado["precio_pagado"],
        "gold_remaining": resultado["nuevo_gold"]

    }