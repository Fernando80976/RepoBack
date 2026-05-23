from datetime import datetime, timezone
from app.core.config import supabase_db
from app.utils.battle.constants import _cap_int4
from app.utils.battle.entities import _get_enemy_rewards
from app.utils.level_up import check_level_up


# ─────────────────────────────────────────────
# GUARDADO DE ESTADO EN COMBATE
# ─────────────────────────────────────────────

def _save_hp_mp(user_id: str, state: dict) -> None:
    """Guarda el HP y MP finales en el perfil del cazador, y ajusta fatiga según resultado."""
    p = state["player"]
    profile_limits = (
        supabase_db.table("profiles")
        .select("hp_max, mp_max, fatigue")
        .eq("id", user_id)
        .single()
        .execute()
        .data
    )

    base_hp_max = int(profile_limits.get("hp_max") or 0)
    base_mp_max = int(profile_limits.get("mp_max") or 0)
    hp_to_save = max(0, min(int(p.get("hp") or 0), base_hp_max))
    mp_to_save = max(0, min(int(p.get("mp") or 0), base_mp_max))

    current_fatigue = int(profile_limits.get("fatigue") or 0)
    if state["status"] == "victory":
        new_fatigue = min(100, current_fatigue + 15)
    elif state["status"] == "defeat":
        new_fatigue = min(100, current_fatigue + 10)
    else:
        new_fatigue = current_fatigue

    print("Guardando HP/MP:", hp_to_save, mp_to_save)
    supabase_db.table("profiles").update({
        "hp_current": hp_to_save,
        "mp_current": mp_to_save,
        "fatigue": new_fatigue,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", user_id).execute()


# ─────────────────────────────────────────────
# MISIONES DE MAZMORRA
# ─────────────────────────────────────────────

def _complete_dungeon_mission(user_id: str, dungeon_id: int) -> None:
    """
    Marca como completadas las instancias activas de misiones 'complete_dungeon'
    asociadas a la mazmorra que acaba de ganarse.
    """
    try:
        mission_res = (
            supabase_db.table("missions")
            .select("id, target_value")
            .eq("target_type", "complete_dungeon")
            .eq("dungeon_id", dungeon_id)
            .execute()
        )
        missions = mission_res.data or []
        if not missions:
            return

        mission_ids = [m["id"] for m in missions]
        instance_res = (
            supabase_db.table("hunter_missions")
            .select("id, current_progress, missions(target_value)")
            .eq("hunter_id", user_id)
            .in_("mission_id", mission_ids)
            .eq("status", "active")
            .execute()
        )
        instances = instance_res.data or []
        if not instances:
            return

        now = datetime.now(timezone.utc).isoformat()
        for inst in instances:
            current = int(inst.get("current_progress") or 0)
            target = int((inst.get("missions") or {}).get("target_value") or 1)
            new_progress = min(target, current + 1)
            payload = {"current_progress": new_progress}
            if new_progress >= target:
                payload["status"] = "completed"
                payload["completed_at"] = now
            supabase_db.table("hunter_missions").update(payload).eq("id", inst["id"]).execute()
    except Exception:
        return


# ─────────────────────────────────────────────
# RECOMPENSAS FINALES
# ─────────────────────────────────────────────

def _save_battle_rewards(user_id: str, state: dict) -> dict:
    pending_rewards = state.get("pending_rewards") or {}
    exp_reward = int(pending_rewards.get("exp", 0) or 0)
    gold_reward = int(pending_rewards.get("gold", 0) or 0)

    if exp_reward == 0 and gold_reward == 0:
        exp_reward, gold_reward = _get_enemy_rewards(state["enemy"])

    profile = (
        supabase_db.table("profiles")
        .select("experience, gold, level, exp_next_level, stat_points, skill_points, hp_max, mp_max")
        .eq("id", user_id)
        .single()
        .execute()
        .data
    )

    profile["experience"] = _cap_int4(profile["experience"] + exp_reward)
    profile["gold"] = _cap_int4(profile["gold"] + gold_reward)

    level_up_data = check_level_up(profile)

    update_data = {
        "experience": profile["experience"],
        "gold": profile["gold"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if level_up_data:
        level_up_data["level"] = _cap_int4(level_up_data["level"])
        level_up_data["experience"] = _cap_int4(level_up_data["experience"])
        level_up_data["exp_next_level"] = _cap_int4(level_up_data["exp_next_level"])
        level_up_data["stat_points"] = _cap_int4(level_up_data["stat_points"])
        level_up_data["skill_points"] = _cap_int4(level_up_data["skill_points"])
        level_up_data["hp_max"] = _cap_int4(level_up_data["hp_max"])
        level_up_data["hp_current"] = _cap_int4(level_up_data["hp_current"])
        level_up_data["mp_max"] = _cap_int4(level_up_data["mp_max"])
        level_up_data["mp_current"] = _cap_int4(level_up_data["mp_current"])
        update_data.update(level_up_data)

    supabase_db.table("profiles").update(update_data).eq("id", user_id).execute()

    if state.get("dungeon_id") is not None:
        _complete_dungeon_mission(user_id, int(state["dungeon_id"]))

    return {
        "exp": exp_reward,
        "gold": gold_reward,
        "leveled_up": level_up_data is not None,
        "new_level": update_data.get("level", profile["level"]),
    }
