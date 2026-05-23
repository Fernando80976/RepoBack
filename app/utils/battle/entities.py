import random
from app.core.config import supabase_db
from app.utils.equipment_stats import get_equipment_stat_bonuses, apply_equipment_stats


# ─────────────────────────────────────────────
# CARGA DE DATOS REALES DEL CAZADOR
# ─────────────────────────────────────────────

def _load_player(user_id: str) -> dict:
    base_profile = (
        supabase_db.table("profiles")
        .select("username, hp_current, hp_max, mp_current, mp_max, strength, agility, vitality, intelligence, sense, level")
        .eq("id", user_id)
        .single()
        .execute()
        .data
    )
    bonuses = get_equipment_stat_bonuses(user_id)
    profile = apply_equipment_stats(base_profile, bonuses)

    skills_res = (
        supabase_db.table("hunter_skills")
        .select("current_level, current_mana_cost, skills(id, name, damage_multiplier, cooldown)")
        .eq("hunter_id", user_id)
        .execute()
    )

    skills = []
    for entry in skills_res.data:
        s = entry["skills"]
        skills.append({
            "id": s["id"],
            "name": s["name"],
            "mana_cost": entry["current_mana_cost"],
            "damage_multiplier": float(s["damage_multiplier"]),
            "current_level": entry["current_level"],
            "cd": 0,
            "max_cd": s["cooldown"],
        })

    potions_res = (
        supabase_db.table("inventory")
        .select("id, quantity, items(name, type, stat_type, stat_value)")
        .eq("hunter_id", user_id)
        .execute()
    )
    potions = []
    for row in (potions_res.data or []):
        item = row.get("items") or {}
        if item.get("type") == "potion":
            potions.append({
                "inventory_id": row["id"],
                "name": item.get("name"),
                "quantity": int(row.get("quantity") or 0),
                "stat_type": str(item.get("stat_type") or "").strip().lower(),
                "stat_value": int(item.get("stat_value") or 0),
            })

    return {
        "name": profile["username"],
        "hp": profile["hp_current"],
        "max_hp": profile["hp_max"],
        "mp": profile["mp_current"],
        "max_mp": profile["mp_max"],
        "strength": profile["strength"],
        "agility": profile["agility"],
        "vitality": profile["vitality"],
        "intelligence": profile["intelligence"],
        "sense": profile["sense"],
        "level": profile["level"],
        "skills": skills,
        "potions": potions,
    }


# ─────────────────────────────────────────────
# GENERACIÓN DEL ENEMIGO (ESCALADO AL NIVEL)
# ─────────────────────────────────────────────

def _make_enemy(player_level: int) -> dict:
    hp = 80 + player_level * 25
    return {
        "name": f"Shadow Beast (Lv. {player_level})",
        "level": player_level,
        "source": "legacy",
        "hp": hp,
        "max_hp": hp,
        "min_dmg": 6 + player_level * 2,
        "max_dmg": 12 + player_level * 3,
        "perception": 0,
        "agility": 0,
    }


# ─────────────────────────────────────────────
# POOL DE ENEMIGOS DE MAZMORRAS
# ─────────────────────────────────────────────

def _get_pool_with_types(dungeon_id: int) -> list[dict]:
    pool_res = (
        supabase_db.table("dungeon_enemies")
        .select("enemy_id, spawn_chance")
        .eq("dungeon_id", dungeon_id)
        .execute()
    )
    pool = pool_res.data or []
    if not pool:
        return []

    enemy_ids = [item["enemy_id"] for item in pool]
    types_res = (
        supabase_db.table("enemies")
        .select("id, enemy_type")
        .in_("id", enemy_ids)
        .execute()
    )
    type_map = {
        row["id"]: (row.get("enemy_type") or "normal")
        for row in (types_res.data or [])
    }
    for item in pool:
        item["enemy_type"] = type_map.get(item["enemy_id"], "normal")
    return pool


def _get_wave_allowed_types(state: dict, wave_number: int) -> list[str]:
    n = int(state.get("normal_wave_count") or 0)
    m = int(state.get("elite_wave_count") or 0)
    if wave_number <= n:
        return ["normal"]
    elif wave_number <= n + m:
        return ["elite"]
    else:
        return ["boss"]


def _pick_enemy_for_dungeon(
    dungeon_id: int,
    excluded_enemy_ids: set[int] | None = None,
    allowed_types: list[str] | None = None,
) -> dict:
    pool = _get_pool_with_types(dungeon_id)
    if not pool:
        raise ValueError("ERR_DUNGEON_WITHOUT_ENEMIES")

    if excluded_enemy_ids:
        pool = [item for item in pool if item["enemy_id"] not in excluded_enemy_ids]
        if not pool:
            raise ValueError("ERR_DUNGEON_NO_UNIQUE_ENEMIES_LEFT")

    if allowed_types is not None:
        pool = [item for item in pool if item.get("enemy_type") in allowed_types]
        if not pool:
            raise ValueError("ERR_DUNGEON_NO_ENEMIES_OF_TYPE")

    enemy_ids = [item["enemy_id"] for item in pool]
    weights = [float(item.get("spawn_chance", 1) or 1) for item in pool]
    selected_enemy_id = random.choices(enemy_ids, weights=weights, k=1)[0]

    enemy_res = (
        supabase_db.table("enemies")
        .select("id, name, rank, enemy_type, base_hp, base_damage_min, base_damage_max, reward_exp, reward_gold, perception, agility")
        .eq("id", selected_enemy_id)
        .single()
        .execute()
    )
    enemy = enemy_res.data
    if not enemy:
        raise ValueError("ERR_DUNGEON_ENEMY_NOT_FOUND")

    enemy_name = enemy["name"]
    if isinstance(enemy_name, dict):
        enemy_name = enemy_name.get("es") or enemy_name.get("en") or str(enemy_name)

    hp = int(enemy.get("base_hp") or 1)
    min_dmg = int(enemy.get("base_damage_min") or 1)
    max_dmg = int(enemy.get("base_damage_max") or min_dmg)
    if max_dmg < min_dmg:
        max_dmg = min_dmg
    reward_exp = int(enemy.get("reward_exp") or 0)
    reward_gold = int(enemy.get("reward_gold") or 0)

    return {
        "id": enemy["id"],
        "name": enemy_name,
        "rank": enemy.get("rank"),
        "enemy_type": enemy.get("enemy_type") or "normal",
        "level": 1,
        "source": "dungeon",
        "hp": hp,
        "max_hp": hp,
        "min_dmg": min_dmg,
        "max_dmg": max_dmg,
        "reward_exp": reward_exp,
        "reward_gold": reward_gold,
        "perception": int(enemy.get("perception") or 0),
        "agility": int(enemy.get("agility") or 0),
    }


def _get_enemy_rewards(enemy: dict) -> tuple[int, int]:
    if enemy.get("source") == "dungeon":
        return int(enemy.get("reward_exp", 0) or 0), int(enemy.get("reward_gold", 0) or 0)
    enemy_level = int(enemy.get("level", 1) or 1)
    return 30 + enemy_level * 20, 10 + enemy_level * 10
