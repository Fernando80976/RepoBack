from app.core.config import supabase_db


TRACKED_STATS = {"strength", "agility", "vitality", "intelligence", "sense"}


def get_equipment_stat_bonuses(user_id: str) -> dict[str, int]:
    """Obtiene bonus de stats desde hunter_equipment -> inventory -> items."""
    bonuses = {stat: 0 for stat in TRACKED_STATS}

    equipment_res = (
        supabase_db.table("hunter_equipment")
        .select(
            """
            head:inventory!head_id(id, items(stat_type, stat_value)),
            chest:inventory!chest_id(id, items(stat_type, stat_value)),
            pants:inventory!pants_id(id, items(stat_type, stat_value)),
            boots:inventory!boots_id(id, items(stat_type, stat_value)),
            main_hand:inventory!main_hand_id(id, items(stat_type, stat_value)),
            off_hand:inventory!off_hand_id(id, items(stat_type, stat_value)),
            accessory:inventory!accessory_id(id, items(stat_type, stat_value))
        """
        )
        .eq("hunter_id", user_id)
        .single()
        .execute()
    )
    equipment = equipment_res.data or {}

    # 1. Creamos un Set para llevar el control de los IDs ya sumados
    processed_inventory_ids = set()

    for slot_data in equipment.values():
        if not slot_data:
            continue

        # 2. Capturamos el ID único del objeto en el inventario
        inv_id = slot_data.get("id")

        # 3. Si el ID ya está en el Set, significa que es la otra mitad del arma dual. Lo saltamos.
        if inv_id in processed_inventory_ids:
            continue
        
        # 4. Añadimos el ID al Set para marcarlo como procesado
        if inv_id:
            processed_inventory_ids.add(inv_id)

        item = slot_data.get("items")
        if not item:
            continue

        raw_stat_type = str(item.get("stat_type") or "").strip().lower()
        if raw_stat_type in TRACKED_STATS:
            bonuses[raw_stat_type] += int(item.get("stat_value") or 0)

    return bonuses


def apply_equipment_stats(profile: dict, bonuses: dict[str, int]) -> dict:
    """Devuelve una copia del profile con stats efectivas (base + equipo)."""
    enriched = dict(profile)
    enriched["equipment_bonuses"] = dict(bonuses)

    title_info = profile.get("titles") or {}
    title_bonuses = {stat: 0 for stat in TRACKED_STATS}
    title_stat = str(title_info.get("stats_effect") or "").strip().lower()
    if title_stat in TRACKED_STATS:
        title_bonuses[title_stat] = int(title_info.get("effect") or 0)
    enriched["title_bonuses"] = dict(title_bonuses)

    class_info = profile.get("player_classes", {})
    target_stat = class_info.get("target_stat")  # Ej: "strength"
    class_bonus_val = int(class_info.get("stats_bonus") or 0)

    base_hp_max = int(enriched.get("hp_max") or 0)
    base_mp_max = int(enriched.get("mp_max") or 0)
    base_hp_current = int(enriched.get("hp_current") or 0)
    base_mp_current = int(enriched.get("mp_current") or 0)

    for stat in TRACKED_STATS:
        base_value = int(enriched.get(stat) or 0)
        bonus_value = int(bonuses.get(stat) or 0)
        title_bonus_value = int(title_bonuses.get(stat) or 0)

        # Comprobamos si esta stat es la beneficiada por la clase
        current_class_bonus = class_bonus_val if stat == target_stat else 0

        enriched[f"base_{stat}"] = base_value
        enriched[f"bonus_{stat}"] = bonus_value
        enriched[f"title_bonus_{stat}"] = title_bonus_value
        enriched[f"class_bonus_{stat}"] = current_class_bonus

        enriched[stat] = base_value + bonus_value + title_bonus_value + current_class_bonus

    # HP/MP ya se persisten con valores efectivos en la BD al equipar/desequipar
    # (ver persist_effective_hp_mp). Aquí solo se calculan para visualización.
    total_vit_bonus = max(0, int(bonuses.get("vitality") or 0) + int(title_bonuses.get("vitality") or 0))
    total_int_bonus = max(0, int(bonuses.get("intelligence") or 0) + int(title_bonuses.get("intelligence") or 0))

    bonus_hp_max = total_vit_bonus * 15
    bonus_mp_max = total_int_bonus * 5

    enriched["base_hp_max"] = base_hp_max
    enriched["bonus_hp_max"] = bonus_hp_max
    enriched["base_mp_max"] = base_mp_max
    enriched["bonus_mp_max"] = bonus_mp_max

    # La BD ya contiene el hp_max/mp_max efectivo; no se suma el bonus aquí.
    enriched["hp_max"] = base_hp_max
    enriched["mp_max"] = base_mp_max
    enriched["hp_current"] = base_hp_current
    enriched["mp_current"] = base_mp_current

    return enriched


def persist_effective_hp_mp(
    user_id: str,
    old_bonuses: dict[str, int],
    new_bonuses: dict[str, int],
) -> None:
    """
    Actualiza hp_max, hp_current, mp_max y mp_current en la BD cuando cambia
    el equipo. Aplica el delta de VIT/INT para mantener siempre valores efectivos.
    """
    delta_vit = int(new_bonuses.get("vitality") or 0) - int(old_bonuses.get("vitality") or 0)
    delta_int = int(new_bonuses.get("intelligence") or 0) - int(old_bonuses.get("intelligence") or 0)

    if delta_vit == 0 and delta_int == 0:
        return

    profile_res = (
        supabase_db.table("profiles")
        .select("hp_max, hp_current, mp_max, mp_current")
        .eq("id", user_id)
        .single()
        .execute()
    )
    p = profile_res.data

    current_hp_max = int(p.get("hp_max") or 0)
    current_mp_max = int(p.get("mp_max") or 0)
    current_hp = int(p.get("hp_current") or 0)
    current_mp = int(p.get("mp_current") or 0)

    delta_hp = delta_vit * 15
    delta_mp = delta_int * 5

    new_hp_max = max(1, current_hp_max + delta_hp)
    new_mp_max = max(0, current_mp_max + delta_mp)

    # Si estaba al máximo, sube junto al nuevo máximo
    if delta_hp > 0 and current_hp >= current_hp_max:
        new_hp = new_hp_max
    else:
        new_hp = min(current_hp, new_hp_max)

    if delta_mp > 0 and current_mp >= current_mp_max:
        new_mp = new_mp_max
    else:
        new_mp = min(current_mp, new_mp_max)

    supabase_db.table("profiles").update({
        "hp_max": new_hp_max,
        "hp_current": new_hp,
        "mp_max": new_mp_max,
        "mp_current": new_mp,
    }).eq("id", user_id).execute()
