from pydantic import BaseModel

# Esquema para recibir la ID de la habilidad
class UpgradeSkillSchema(BaseModel):
    skill_id: int

class UnlockSkillSchema(BaseModel):
    skill_id: int