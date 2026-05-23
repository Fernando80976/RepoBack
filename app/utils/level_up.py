import math
from datetime import datetime, timezone
from app.utils.battle.constants import _cap_int4


def check_level_up(profile: dict):
    new_data = {
        "level": profile["level"],
        "experience": profile["experience"],
        "exp_next_level": profile["exp_next_level"],
        "stat_points": profile["stat_points"],
        "skill_points": int(profile.get("skill_points") or 0),
        "hp_max": profile["hp_max"],
        "mp_max": profile["mp_max"],
    }

    leveled_up = False

    while new_data["experience"] >= new_data["exp_next_level"]:
        leveled_up = True
        new_data["experience"] -= new_data["exp_next_level"]
        new_data["level"] += 1
        new_data["stat_points"] += 5
        new_data["skill_points"] += 5
        new_data["hp_max"] += 20
        new_data["mp_max"] += 10

        # Fórmula Solo Leveling: 20% más difícil cada nivel
        new_data["exp_next_level"] = math.floor(
            new_data["level"] * 100 * (1.2 ** (new_data["level"] - 1))
        )
        new_data["exp_next_level"] = _cap_int4(new_data["exp_next_level"])

    if leveled_up:
        return {
            "level": new_data["level"],
            "experience": new_data["experience"],
            "exp_next_level": new_data["exp_next_level"],
            "stat_points": new_data["stat_points"],
            "skill_points": new_data["skill_points"],
            "hp_max": new_data["hp_max"],
            "hp_current": new_data["hp_max"],
            "mp_max": new_data["mp_max"],
            "mp_current": new_data["mp_max"],
            "fatigue": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return None
