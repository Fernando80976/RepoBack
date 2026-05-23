INT4_MAX = 2_147_483_647

# ─────────────────────────────────────────────
# BALANCE DE ESQUIVA
# ─────────────────────────────────────────────
DODGE_BASE_CHANCE = 5.0               # % base de esquiva para cualquier cazador.
DODGE_AGI_FACTOR = 0.35               # Aporte de cada punto de AGI a la esquiva.
DODGE_SENSE_FACTOR = 0.25             # Aporte de cada punto de SENSE a la esquiva.
DODGE_ENEMY_PERCEPTION_FACTOR = 1.5   # Penalización por percepción del enemigo: enemy_perception * factor.
DODGE_MIN_CHANCE = 2.0                # Límite mínimo de esquiva (%).
DODGE_MAX_CHANCE = 55.0               # Límite máximo de esquiva (%).


def _cap_int4(value: int) -> int:
    """Limita un entero al rango de PostgreSQL int4."""
    return max(0, min(int(value), INT4_MAX))
