from fastapi import APIRouter, Depends
from app.core.config import supabase_db
from app.core.security import validate_hunter_session

router = APIRouter(prefix="/ranking", tags=["Ranking Global"])


# ─────────────────────────────────────────────
# NPC HUNTERS — Cazadores del universo Solo Leveling
#
# Estos cazadores son permanentes en el ranking para dar
# escala y contexto desde el primer día. Los jugadores reales
# compiten por superar a estos legends.
# ─────────────────────────────────────────────
NPC_HUNTERS = [
    {
        "username": "Sung_JinWoo",
        "rank": "S",
        "class": {"es": "Monarca de la Sombra", "en": "Shadow Monarch"},
        "level": 100,
        "experience": 9_500_000,
        "strength": 300,
        "agility": 280,
        "vitality": 220,
        "intelligence": 180,
        "sense": 250,
        "is_npc": True,
    },
    {
        "username": "Thomas_Andre",
        "rank": "S",
        "class": {"es": "Usuario de Refuerzo", "en": "Reinforcement User"},
        "level": 87,
        "experience": 6_200_000,
        "strength": 280,
        "agility": 180,
        "vitality": 290,
        "intelligence": 100,
        "sense": 130,
        "is_npc": True,
    },
    {
        "username": "Liu_Zhigang",
        "rank": "S",
        "class": {"es": "Domador de Bestias", "en": "Beast Tamer"},
        "level": 82,
        "experience": 5_400_000,
        "strength": 240,
        "agility": 200,
        "vitality": 210,
        "intelligence": 140,
        "sense": 160,
        "is_npc": True,
    },
    {
        "username": "Choi_JongIn",
        "rank": "S",
        "class": {"es": "Mago de la Llama", "en": "Flame Mage"},
        "level": 79,
        "experience": 4_900_000,
        "strength": 160,
        "agility": 190,
        "vitality": 180,
        "intelligence": 280,
        "sense": 140,
        "is_npc": True,
    },
    {
        "username": "Baek_Yoonho",
        "rank": "S",
        "class": {"es": "Monarca de la Bestia", "en": "Beast Monarch"},
        "level": 76,
        "experience": 4_300_000,
        "strength": 260,
        "agility": 230,
        "vitality": 200,
        "intelligence": 120,
        "sense": 180,
        "is_npc": True,
    },
    {
        "username": "Cha_HaeIn",
        "rank": "S",
        "class": {"es": "Maestro de la Espada", "en": "Sword Master"},
        "level": 73,
        "experience": 3_800_000,
        "strength": 250,
        "agility": 260,
        "vitality": 170,
        "intelligence": 130,
        "sense": 200,
        "is_npc": True,
    },
    {
        "username": "Go_GunHee",
        "rank": "S",
        "class": {"es": "Líder de Gremio", "en": "Guild Master"},
        "level": 70,
        "experience": 3_400_000,
        "strength": 230,
        "agility": 200,
        "vitality": 240,
        "intelligence": 160,
        "sense": 170,
        "is_npc": True,
    },
    {
        "username": "Hwang_DongSu",
        "rank": "S",
        "class": {"es": "Berserker", "en": "Berserker"},
        "level": 65,
        "experience": 2_900_000,
        "strength": 270,
        "agility": 210,
        "vitality": 220,
        "intelligence": 90,
        "sense": 110,
        "is_npc": True,
    },
    {
        "username": "Ma_DongWook",
        "rank": "A",
        "class": {"es": "Guardián", "en": "Guardian"},
        "level": 55,
        "experience": 2_100_000,
        "strength": 200,
        "agility": 150,
        "vitality": 270,
        "intelligence": 100,
        "sense": 130,
        "is_npc": True,
    },
    {
        "username": "Lim_TaeGyu",
        "rank": "A",
        "class": {"es": "Tanque", "en": "Tank"},
        "level": 45,
        "experience": 1_500_000,
        "strength": 170,
        "agility": 130,
        "vitality": 250,
        "intelligence": 90,
        "sense": 100,
        "is_npc": True,
    },
]


def _calc_power(hunter: dict) -> int:
    """
    Calcula el poder total de un cazador.
    Fórmula: nivel * 500 + suma_stats * 10 + experiencia // 100
    """
    stats_sum = (
        hunter["strength"] + hunter["agility"] +
        hunter["vitality"] + hunter["intelligence"] +
        hunter["sense"]
    )
    return hunter["level"] * 500 + stats_sum * 10 + hunter["experience"] // 100


@router.get("/")
async def get_global_ranking(user_id: str = Depends(validate_hunter_session)):
    # 1. Obtener los mejores 100 con JOIN a player_classes
    # Traemos el campo 'name' de la tabla player_classes a través de class_id
    res = supabase_db.table("profiles").select(
        "username, rank, level, experience, strength, agility, vitality, intelligence, sense, "
        "player_classes(name)" 
    ).limit(100).execute()

    # 2. Mapear los datos para que el Frontend reciba "job" como antes
    real_hunters = []
    for h in res.data:
        # Extraemos el nombre de la clase del objeto relacionado
        # player_classes devuelve una lista o dict dependiendo de la relación
        class_info = h.get("player_classes")
        # class_name = class_info.get("name").get("es") if class_info else "Sin Clase"
        class_name = class_info.get("name") if class_info else "Sin Clase"
        hunter_data = {
            **h,
            "class": class_name, # Inyectamos el nombre para no romper el front
            "is_npc": False
        }
        real_hunters.append(hunter_data)

    # 3. Combinar con NPCs (Ellos ya tienen el campo "class" en su lista de diccionarios)
    all_hunters = real_hunters + NPC_HUNTERS

    # 3. Calcular Poder
    for h in all_hunters:
        h["power_score"] = _calc_power(h)

    # 4. Ordenar y Limitar a 100
    all_hunters.sort(key=lambda h: h["power_score"], reverse=True)
    top_100 = all_hunters[:100]

    # Lógica de Paginación
    # start = (page - 1) * limit
    # end = start + limit

    # total_hunters = len(top_100)
    # paginated_hunters = top_100[start:end]

    # 4. Construir ranking final con posición
    ranking = [
        {
            "position": i,
            "username": hunter["username"],
            "hunter_rank": hunter["rank"],
            "class": hunter["class"],
            "level": hunter["level"],
            "power_score": hunter["power_score"],
            "is_npc": hunter["is_npc"],
        }
        for i, hunter in enumerate(top_100, start=1)
    ]

    return ranking


@router.get("/me")
async def get_my_ranking_position(user_id: str = Depends(validate_hunter_session)):
    # 1. Obtener perfil con la clase relacionada
    profile_res = supabase_db.table("profiles").select(
        "username, rank, level, experience, strength, agility, vitality, intelligence, sense, "
        "player_classes(name)"
    ).eq("id", user_id).single().execute()

    h = profile_res.data
    class_info = h.get("player_classes")
    class_name = class_info.get("name").get("es") if class_info else "Sin Clase"

    me = {**h, "class": class_name, "is_npc": False}
    # 2. Construir el ranking completo igual que en get_global_ranking
    res = supabase_db.table("profiles").select(
        "username, rank, level, experience, strength, agility, vitality, intelligence, sense, "
        "player_classes(name)" 
    ).execute()

    all_hunters = [{**h, "is_npc": False} for h in res.data] + NPC_HUNTERS

    for h in all_hunters:
        h["power_score"] = _calc_power(h)

    all_hunters.sort(key=lambda h: h["power_score"], reverse=True)

    # 3. Localizar la posición del cazador actual
    my_power = _calc_power(me)
    position = next(
        (i for i, h in enumerate(all_hunters, start=1) if h["username"] == me["username"]),
        None
    )

    return {
        "position": position,
        "total_hunters": len(all_hunters),
        "username": me["username"],
        "hunter_rank": me["rank"],
        "class": me["class"],
        "level": me["level"],
        "power_score": my_power,
        "is_npc": False,
    }
