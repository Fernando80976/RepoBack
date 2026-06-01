# Fachada de compatibilidad - re-exporta todo para no romper imports existentes.
from app.utils.battle.constants import INT4_MAX, _cap_int4
from app.utils.battle.entities import (
    _load_player,
    _make_enemy,
    _get_pool_with_types,
    _get_wave_allowed_types,
    _pick_enemy_for_dungeon,
    _get_enemy_rewards,
)
from app.utils.battle.combat import (
    _clamp,
    _trim_log,
    _reduce_cooldowns,
    _determine_first_turn,
    _calc_dodge_chance,
    _enemy_turn,
    _normal_attack,
    _skill_attack,
    _use_potion,
)
from app.utils.battle.state import _make_battle_state, _process_action
from app.utils.battle.persistence import (
    _save_hp_mp,
    _save_battle_rewards,
    _complete_dungeon_mission,
)
from app.utils.level_up import check_level_up

__all__ = [
    "INT4_MAX", "_cap_int4",
    "_load_player", "_make_enemy", "_get_pool_with_types",
    "_get_wave_allowed_types", "_pick_enemy_for_dungeon", "_get_enemy_rewards",
    "_clamp", "_trim_log", "_reduce_cooldowns", "_determine_first_turn",
    "_calc_dodge_chance", "_enemy_turn", "_normal_attack", "_skill_attack", "_use_potion",
    "_make_battle_state", "_process_action",
    "_save_hp_mp", "_save_battle_rewards", "_complete_dungeon_mission",
    "check_level_up",
]
