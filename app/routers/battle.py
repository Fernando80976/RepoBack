from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import json
from app.utils.game_logic import (
    _make_battle_state, 
    _process_action, 
    _save_hp_mp,
    _save_battle_rewards
)
from app.core.security import _validate_ws_session

router = APIRouter(prefix="/battle", tags=["Sistema de Batalla"])


# ─────────────────────────────────────────────
# WEBSOCKET ENDPOINT añadido el xp y gold a la respuesta de victoria
# ─────────────────────────────────────────────

@router.websocket("/ws")
async def battle_ws(ws: WebSocket):
    """
    WebSocket de batalla por turnos.
    Autenticación mediante la cookie 'hunter_session'.
        Selección de mazmorra por query param: /battle/ws?dungeon_id=1

    Mensajes del cliente:
      { "action": "attack" }                  → Ataque normal
      { "action": "skill", "skill_id": 3 }    → Habilidad por ID
            { "action": "potion", "inventory_id": 15 } → Usar poción del inventario
            { "action": "reset", "dungeon_id": 2 }   → Nueva batalla en mazmorra
    """
    hunter_session = ws.cookies.get("hunter_session")
    user_id = _validate_ws_session(hunter_session)

    raw_dungeon_id = ws.query_params.get("dungeon_id")
    dungeon_id = None
    if raw_dungeon_id is not None:
        try:
            dungeon_id = int(raw_dungeon_id)
        except ValueError:
            dungeon_id = None

    await ws.accept()

    if not user_id:
        await ws.send_json({"error": "ERR_AUTH_SESSION_EXPIRED"})
        await ws.close(code=1008)
        return

    try:
        state = _make_battle_state(user_id, dungeon_id=dungeon_id)
    except ValueError as ex:
        await ws.send_json({"error": str(ex)})
        await ws.close(code=1008)
        return

    await ws.send_json(state)

    try:
        while True:
            try:
                raw = await ws.receive_text()
                payload = json.loads(raw)
                action = payload.get("action")

                if action == "reset":
                    new_dungeon_id = payload.get("dungeon_id", state.get("dungeon_id"))
                    try:
                        if new_dungeon_id is not None:
                            new_dungeon_id = int(new_dungeon_id)
                    except (TypeError, ValueError):
                        await ws.send_json({"error": "ERR_INVALID_DUNGEON_ID"})
                        continue

                    try:
                        state = _make_battle_state(user_id, dungeon_id=new_dungeon_id)
                    except ValueError as ex:
                        await ws.send_json({"error": str(ex)})
                        continue

                    await ws.send_json(state)
                    continue

                skill_id = payload.get("skill_id")
                inventory_id = payload.get("inventory_id")
                _process_action(
                    state,
                    action,
                    skill_id,
                    user_id=user_id,
                    inventory_id=inventory_id,
                )

                # Persistir HP/MP y recompensas cuando la batalla termina
                if state["status"] != "active":
                    _save_hp_mp(user_id, state)
                    if state["status"] == "victory" and "rewards" not in state:
                        state["rewards"] = _save_battle_rewards(user_id, state)

                await ws.send_json(state)
            except WebSocketDisconnect:
                # Propagamos la desconexión para que la maneje el bloque externo.
                raise
            except Exception as action_ex:
                # Error de una acción concreta: reportamos y mantenemos el socket activo.
                if ws.application_state == WebSocketState.CONNECTED:
                    await ws.send_json({"error": f"ERR_BATTLE_ACTION: {str(action_ex)}"})
                continue

    except WebSocketDisconnect:
        # Guardar progreso si se desconecta a mitad de batalla
        if state["status"] == "active":
            _save_hp_mp(user_id, state)
    except Exception as ex:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_json({"error": f"ERR_BATTLE_SERVER: {str(ex)}"})
            await ws.close(code=1011)
