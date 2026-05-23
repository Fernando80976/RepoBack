from app.core.config import supabase_db
from app.utils.battle.entities import (
    _load_player, _make_enemy, _get_pool_with_types, _get_wave_allowed_types,
    _pick_enemy_for_dungeon, _get_enemy_rewards,
)
from app.utils.battle.combat import (
    _clamp, _trim_log, _reduce_cooldowns, _determine_first_turn,
    _enemy_turn, _normal_attack, _skill_attack, _use_potion,
)


# ─────────────────────────────────────────────
# CONSTRUCCIÓN DEL ESTADO INICIAL DE BATALLA
# ─────────────────────────────────────────────

def _make_battle_state(user_id: str, dungeon_id: int | None = None) -> dict:
    player = _load_player(user_id)

    # Comprobar fatiga antes de iniciar la batalla
    fatigue_res = (
        supabase_db.table("profiles")
        .select("fatigue")
        .eq("id", user_id)
        .single()
        .execute()
    )
    fatigue = int((fatigue_res.data or {}).get("fatigue") or 0)
    if fatigue >= 100:
        raise ValueError("ERR_MAX_FATIGUE")

    if dungeon_id is not None:
        dungeon_res = (
            supabase_db.table("dungeons")
            .select("id, name, max_enemies")
            .eq("id", dungeon_id)
            .single()
            .execute()
        )
        dungeon = dungeon_res.data
        if not dungeon:
            raise ValueError("ERR_DUNGEON_NOT_FOUND")
        pool = _get_pool_with_types(dungeon_id)
        if not pool:
            raise ValueError("ERR_DUNGEON_WITHOUT_ENEMIES")

        normals = [e for e in pool if e.get("enemy_type") == "normal"]
        elites  = [e for e in pool if e.get("enemy_type") == "elite"]
        bosses  = [e for e in pool if e.get("enemy_type") == "boss"]

        requested_waves = max(1, int(dungeon.get("max_enemies") or 1))

        boss_wave_count   = min(len(bosses),  requested_waves)
        remaining         = min(requested_waves, len(pool)) - boss_wave_count
        elite_wave_count  = min(len(elites),  remaining)
        normal_wave_count = min(len(normals), remaining - elite_wave_count)
        wave_total = normal_wave_count + elite_wave_count + boss_wave_count

        if wave_total == 0:
            raise ValueError("ERR_DUNGEON_WITHOUT_ENEMIES")

        first_wave_types = (
            ["normal"] if normal_wave_count > 0
            else ["elite"] if elite_wave_count > 0
            else ["boss"]
        )
        enemy = _pick_enemy_for_dungeon(dungeon_id, allowed_types=first_wave_types)
    else:
        dungeon = None
        enemy = _make_enemy(player["level"])
        wave_total = 1
        normal_wave_count = 0
        elite_wave_count  = 0
        boss_wave_count   = 0

    dungeon_name = None
    if dungeon:
        dungeon_name_raw = dungeon.get("name")
        if isinstance(dungeon_name_raw, dict):
            dungeon_name = dungeon_name_raw.get("es") or dungeon_name_raw.get("en")
        elif isinstance(dungeon_name_raw, str):
            dungeon_name = dungeon_name_raw

    first_turn = _determine_first_turn(player, enemy)
    emerge_msg = f"Un {enemy['name']} emerge de las sombras..."
    if first_turn == "enemy":
        turn_msg = f"{enemy['name']} actúa primero (AGI {enemy.get('agility', 0)} > {player.get('agility', 0)})."
    else:
        turn_msg = f"Atacas primero (AGI {player.get('agility', 0)} >= {enemy.get('agility', 0)})."

    state = {
        "player": player,
        "enemy": enemy,
        "dungeon_id": dungeon_id,
        "dungeon_name": dungeon_name,
        "wave_current": 1,
        "wave_total": wave_total,
        "normal_wave_count": normal_wave_count,
        "elite_wave_count": elite_wave_count,
        "boss_wave_count": boss_wave_count,
        "used_enemy_ids": [enemy["id"]] if dungeon_id is not None and enemy.get("id") else [],
        "pending_rewards": {"exp": 0, "gold": 0},
        "turn": "player",
        "round": 1,
        "status": "active",
        "log": [emerge_msg, turn_msg],
    }

    if first_turn == "enemy":
        _enemy_turn(state)
        _clamp(state)
        if state["player"]["hp"] <= 0:
            state["log"].append("💀 HAS MUERTO antes de poder actuar.")
            state["status"] = "defeat"
            state["turn"] = "finished"

    return state


# ─────────────────────────────────────────────
# PROCESADO DEL TURNO COMPLETO
# ─────────────────────────────────────────────

def _process_action(
    state: dict,
    action: str,
    skill_id: int | None,
    user_id: str | None = None,
    inventory_id: int | None = None,
) -> None:
    if state["status"] != "active":
        state["log"].append("La batalla ya ha terminado.")
        return

    if state["turn"] != "player":
        state["log"].append("No es tu turno.")
        return

    # — Acción del jugador —
    if action == "attack":
        _normal_attack(state)
    elif action == "skill" and skill_id is not None:
        if not _skill_attack(state, skill_id):
            return
    elif action == "potion" and inventory_id is not None and user_id is not None:
        if not _use_potion(state, user_id, inventory_id):
            return
    else:
        state["log"].append("Acción inválida.")
        return

    _clamp(state)

    # ¿Enemigo derrotado?
    if state["enemy"]["hp"] <= 0:
        exp_gain, gold_gain = _get_enemy_rewards(state["enemy"])
        pending_rewards = state.setdefault("pending_rewards", {"exp": 0, "gold": 0})
        pending_rewards["exp"] += exp_gain
        pending_rewards["gold"] += gold_gain
        state["log"].append(f"Recompensa acumulada: +{exp_gain} EXP, +{gold_gain} Gold.")

        is_dungeon = state.get("dungeon_id") is not None
        current_wave = int(state.get("wave_current", 1) or 1)
        total_waves = int(state.get("wave_total", 1) or 1)

        if is_dungeon and current_wave < total_waves:
            state["wave_current"] = current_wave + 1
            used_enemy_ids = set(state.get("used_enemy_ids", []))
            try:
                allowed_types = _get_wave_allowed_types(state, state["wave_current"])
                state["enemy"] = _pick_enemy_for_dungeon(
                    int(state["dungeon_id"]),
                    excluded_enemy_ids=used_enemy_ids,
                    allowed_types=allowed_types,
                )
            except ValueError:
                state["log"].append("No quedan enemigos únicos para más oleadas.")
                state["status"] = "victory"
                state["turn"] = "finished"
                _trim_log(state)
                return

            state.setdefault("used_enemy_ids", []).append(state["enemy"].get("id"))
            state["round"] += 1
            new_enemy = state["enemy"]
            first_turn = _determine_first_turn(state["player"], new_enemy)
            if first_turn == "enemy":
                turn_msg = f"{new_enemy['name']} actúa primero (AGI {new_enemy.get('agility', 0)} > {state['player'].get('agility', 0)})."
            else:
                turn_msg = f"Atacas primero (AGI {state['player'].get('agility', 0)} >= {new_enemy.get('agility', 0)})."
            state["log"].append(
                f"Oleada {state['wave_current']}/{state['wave_total']}: {new_enemy['name']} aparece."
            )
            state["log"].append(turn_msg)
            if first_turn == "enemy":
                state["turn"] = "player"
                _enemy_turn(state)
                _reduce_cooldowns(state)
                _clamp(state)
                if state["player"]["hp"] <= 0:
                    state["log"].append("💀 HAS MUERTO... Las sombras te consumen.")
                    state["status"] = "defeat"
                    state["turn"] = "finished"
                    _trim_log(state)
                    return
            state["turn"] = "player"
            _trim_log(state)
            return

        state["log"].append("⚔️ ¡VICTORIA! El enemigo ha sido derrotado.")
        state["status"] = "victory"
        state["turn"] = "finished"
        _trim_log(state)
        return

    # — Turno del enemigo —
    state["turn"] = "enemy"
    _enemy_turn(state)
    _reduce_cooldowns(state)
    _clamp(state)

    if state["player"]["hp"] <= 0:
        state["log"].append("💀 HAS MUERTO... Las sombras te consumen.")
        state["status"] = "defeat"
        state["turn"] = "finished"
    else:
        state["turn"] = "player"
        state["round"] += 1

    _trim_log(state)
