from .auth_schemas import LoginSchema, SignupSchema
from .hunter_schemas import UpdateStatsSchema, UpdateActiveTitleSchema, SelectClassSchema
from .inventory_schemas import EquipRequest
from .skills_schemas import UpgradeSkillSchema

# Esto es opcional, pero ayuda a Python a saber qué exportar exactamente
__all__ = [
    "LoginSchema",
    "SignupSchema",
    "UpdateStatsSchema",
    "UpdateActiveTitleSchema",
    "SelectClassSchema",
    "EquipRequest",
    "UpgradeSkillSchema"
    
]