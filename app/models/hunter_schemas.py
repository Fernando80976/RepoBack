from pydantic import BaseModel

class UpdateStatsSchema(BaseModel):
    strength: int = 0
    agility: int = 0
    vitality: int = 0
    intelligence: int = 0
    sense: int = 0

class UpdateActiveTitleSchema(BaseModel):
    title_id: int

class SelectClassSchema(BaseModel):
    class_id: int