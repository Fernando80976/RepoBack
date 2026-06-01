import random
from app.core.config import supabase_db
from app.utils.battle.constants import (
    DODGE_BASE_CHANCE, DODGE_AGI_FACTOR, DODGE_SENSE_FACTOR,
    DODGE_ENEMY_PERCEPTION_FACTOR, DODGE_MIN_CHANCE, DODGE_MAX_CHANCE,
)


# ─────────────────────────────────────────────
# UTILIDADES DE ESTADO
# ─────────────────────────────────────────────

def _clamp(state: dict) -> None:
    p = state["player"]
    p["hp"] = max(0, min(p["hp"], p["max_hp"]))
    p["mp"] = max(0, min(p["mp"], p["max_mp"]))
    e = state["enemy"]
    e["hp"] = max(0, min(e["hp"], e["max_hp"]))


def _trim_log(state: dict, max_items: int = 60) -> None:
    if len(state["log"]) > max_items:
        state["log"] = state["log"][-max_items:]


def _reduce_cooldowns(state: dict) -> None:
    for skill in state["player"]["skills"]:
        if skill["cd"] > 0:
            skill["cd"] -= 1


# ─────────────────────────────────────────────
# ORDEN DE TURNO Y ESQUIVA
# ─────────────────────────────────────────────

def _determine_first_turn(player: dict, enemy: dict) -> str:
    """
    Compara la agilidad del jugador y el enemigo para decidir quién ataca primero.
    En caso de empate, se decide aleatoriamente.
    """
    player_agi = int(player.get("agility") or 0)
    enemy_agi = int(enemy.get("agility") or 0)
    if player_agi > enemy_agi:
        return "player"
    elif enemy_agi > player_agi:
        return "enemy"
    else:
        return random.choice(["player", "enemy"])


def _calc_dodge_chance(player: dict, enemy: dict) -> float:
    """
    Probabilidad de esquiva en porcentaje.
    Escala con AGI+SENSE y se penaliza según la percepción del enemigo.
    """
    agi = int(player.get("agility") or 0)
    sense = int(player.get("sense") or 0)
    enemy_perception = int(enemy.get("perception") or 0)

    base = DODGE_BASE_CHANCE
    stat_factor = agi * DODGE_AGI_FACTOR + sense * DODGE_SENSE_FACTOR
    enemy_penalty = enemy_perception * DODGE_ENEMY_PERCEPTION_FACTOR
    chance = base + stat_factor - enemy_penalty

    return max(DODGE_MIN_CHANCE, min(DODGE_MAX_CHANCE, chance))


def _enemy_turn(state: dict) -> None:
    p = state["player"]
    e = state["enemy"]

    dodge_chance = _calc_dodge_chance(p, e)
    roll = random.uniform(0, 100)
    if roll < dodge_chance:
        state["log"].append(
            f"{p['name']} esquiva el ataque de {e['name']} ({dodge_chance:.1f}% de prob.)."
        )
        return

    min_dmg = int(e.get("min_dmg") or 1)
    max_dmg = int(e.get("max_dmg") or min_dmg)
    if max_dmg < min_dmg:
        max_dmg = min_dmg
    dmg = random.randint(min_dmg, max_dmg)
    p["hp"] -= dmg
    state["log"].append(f"{e['name']} ataca y causa {dmg} de daño.")


# ─────────────────────────────────────────────
# ACCIONES DEL JUGADOR
# ─────────────────────────────────────────────

def _normal_attack(state: dict) -> None:
    p = state["player"]
    dmg = p["strength"] * 2 + random.randint(0, max(1, p["agility"] // 2))
    state["enemy"]["hp"] -= dmg
    state["log"].append(f"Atacas con fuerza bruta y causas {dmg} de daño.")


def _skill_attack(state: dict, skill_id: int) -> bool:
    p = state["player"]
    skill = next((s for s in p["skills"] if s["id"] == skill_id), None)

    if not skill:
        state["log"].append("Habilidad desconocida.")
        return False

    if skill["cd"] > 0:
        state["log"].append(f"{skill['name']} está en recarga ({skill['cd']} turnos).")
        return False

    if p["mp"] < skill["mana_cost"]:
        state["log"].append(f"No tienes suficiente MP para usar {skill['name']}.")
        return False

    dmg = int(p["strength"] * skill["damage_multiplier"] * skill["current_level"])
    p["mp"] -= skill["mana_cost"]
    skill["cd"] = skill["max_cd"]
    state["enemy"]["hp"] -= dmg
    state["log"].append(
        f"Usas {skill['name']} y causas {dmg} de daño. (-{skill['mana_cost']} MP)"
    )
    return True


def _use_potion(state: dict, user_id: str, inventory_id: int) -> bool:
    inv_res = (
        supabase_db.table("inventory")
        .select("id, quantity, items(id, name, type, stat_type, stat_value)")
        .eq("id", inventory_id)
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )
    slot = inv_res.data
    if not slot:
        state["log"].append("No tienes esa pocion en tu inventario.")
        return False

    item = slot.get("items") or {}
    if item.get("type") != "potion":
        state["log"].append("Ese objeto no es una pocion.")
        return False

    amount = int(item.get("stat_value") or 0)
    if amount <= 0:
        state["log"].append("La pocion no tiene un efecto valido.")
        return False

    stat_type = str(item.get("stat_type") or "").strip().lower()
    potion_name = item.get("name")
    if isinstance(potion_name, dict):
        potion_name = potion_name.get("es") or potion_name.get("en") or "Pocion"
    elif not isinstance(potion_name, str) or not potion_name.strip():
        potion_name = "Pocion"

    p = state["player"]
    before_hp = int(p.get("hp") or 0)
    before_mp = int(p.get("mp") or 0)

    heal_hp = 0
    heal_mp = 0
    heal_fatigue = 0

    # Soporta pociones de vitalidad/inteligencia/fatiga (acepta variantes y typos)
    if stat_type in ("hp", "health", "heal", "hp_current", "vitality"):
        heal = amount * 15 if stat_type == "vitality" else amount
        p["hp"] = min(int(p.get("max_hp") or 0), before_hp + heal)
        heal_hp = p["hp"] - before_hp
    elif stat_type in ("mp", "mana", "mp_current", "intelligence"):
        heal = amount * 5 if stat_type == "intelligence" else amount
        p["mp"] = min(int(p.get("max_mp") or 0), before_mp + heal)
        heal_mp = p["mp"] - before_mp
    elif stat_type in ("both", "hp_mp", "all"):
        amount_hp = int(item.get("stat_value_hp") or amount)
        amount_mp = int(item.get("stat_value_mp") or amount)
        p["hp"] = min(int(p.get("max_hp") or 0), before_hp + amount_hp)
        p["mp"] = min(int(p.get("max_mp") or 0), before_mp + amount_mp)
        heal_hp = p["hp"] - before_hp
        heal_mp = p["mp"] - before_mp
    elif stat_type == "vit_int":
        heal_hp = amount * 15
        heal_mp = amount * 5
        p["hp"] = min(int(p.get("max_hp") or 0), before_hp + heal_hp)
        p["mp"] = min(int(p.get("max_mp") or 0), before_mp + heal_mp)
        heal_hp = p["hp"] - before_hp
        heal_mp = p["mp"] - before_mp
    elif stat_type in ("fatigue", "fatiga", "fatige", "fatiga_max", "fatigue_max"):
        before_fatigue = int(p.get("fatigue") or 0)
        min_fatigue = 0
        heal_fatigue = min(amount, before_fatigue)
        p["fatigue"] = max(min_fatigue, before_fatigue - amount)
    else:
        state["log"].append("Esta pocion tiene un efecto no soportado.")
        return False

    if heal_hp <= 0 and heal_mp <= 0 and heal_fatigue <= 0:
        state["log"].append("No necesitas usar esa pocion ahora.")
        return False

    current_qty = int(slot.get("quantity") or 0)
    if current_qty <= 1:
        supabase_db.table("inventory").delete().eq("id", inventory_id).execute()
    else:
        supabase_db.table("inventory").update({"quantity": current_qty - 1}).eq("id", inventory_id).execute()


    if heal_hp > 0 and heal_mp > 0:
        state["log"].append(f"Usas {potion_name}: +{heal_hp} HP y +{heal_mp} MP.")
    elif heal_hp > 0:
        state["log"].append(f"Usas {potion_name}: +{heal_hp} HP.")
    elif heal_mp > 0:
        state["log"].append(f"Usas {potion_name}: +{heal_mp} MP.")
    elif heal_fatigue > 0:
        state["log"].append(f"Usas {potion_name}: -{heal_fatigue} Fatiga.")

    potions = state["player"].get("potions") or []
    for i, pot in enumerate(potions):
        if pot.get("inventory_id") == inventory_id:
            if current_qty <= 1:
                potions.pop(i)
            else:
                pot["quantity"] = current_qty - 1
            break
    state["player"]["potions"] = potions

    return True