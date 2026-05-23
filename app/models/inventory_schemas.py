from pydantic import BaseModel

class EquipRequest(BaseModel):
    inventory_id: int  # ID de la fila en 'inventory'
    slot: str         # 'head', 'chest', 'pants', 'boots', 'main_hand', 'off_hand', 'accessory'