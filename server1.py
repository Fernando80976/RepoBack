from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import create_client, Client
import copy
import json
import os
import random

load_dotenv()

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Faltan variables SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

DEFAULT_BATTLE_STATE = {
    "player": {
        "name": "Hunter",
        "hp": 120,
        "max_hp": 120,
        "skills": [
            {
                "name": "Quick Slash",
                "dmg": 15,
                "cd": 0,
                "max_cd": 0,
                "description": "Ataque rapido sin enfriamiento",
                "type": "Physical",
                "power": 15,
            },
            {
                "name": "Shadow Burst",
                "dmg": 25,
                "cd": 2,
                "max_cd": 2,
                "description": "Explosion de energia sombría",
                "type": "Dark",
                "power": 25,
            },
            {
                "name": "Critical Stab",
                "dmg": 35,
                "cd": 3,
                "max_cd": 3,
                "description": "Estocada de alto riesgo",
                "type": "Critical",
                "power": 35,
            },
        ],
    },
    "enemy": {
        "name": "Knight-Level Boss",
        "hp": 150,
        "max_hp": 150,
    },
    "turn": "player",
    "round": 1,
    "log": ["A Knight-Level Boss emerges from the shadows..."],
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ALLOWED_ORIGINS == ["*"] else ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy", "supabase": "connected"}


def make_default_battle_state(username: str) -> dict:
    state = copy.deepcopy(DEFAULT_BATTLE_STATE)
    state["player"]["name"] = username
    return state


def clamp_hp(state: dict) -> None:
    state["player"]["hp"] = max(0, min(state["player"]["hp"], state["player"]["max_hp"]))
    state["enemy"]["hp"] = max(0, min(state["enemy"]["hp"], state["enemy"]["max_hp"]))


def trim_log(state: dict, max_items: int = 60) -> None:
    if len(state["log"]) > max_items:
        state["log"] = state["log"][-max_items:]


def validate_session(username: str, session_token: str) -> bool:
    result = (
        supabase.table("player_profiles")
        .select("username")
        .eq("username", username.lower())
        .eq("session_token", session_token)
        .limit(1)
        .execute()
    )
    return bool(result.data and len(result.data) > 0)


def load_battle_state(username: str) -> dict:
    result = (
        supabase.table("player_battles")
        .select("battle_state")
        .eq("username", username.lower())
        .limit(1)
        .execute()
    )

    if result.data and len(result.data) > 0:
        saved = result.data[0].get("battle_state")
        if isinstance(saved, dict):
            return saved

    state = make_default_battle_state(username)
    save_battle_state(username, state)
    return state


def save_battle_state(username: str, battle_state: dict) -> None:
    supabase.table("player_battles").upsert(
        {
            "username": username.lower(),
            "battle_state": battle_state,
        }
    ).execute()


def enemy_attack(state: dict) -> None:
    dmg = random.randint(10, 22)
    state["player"]["hp"] -= dmg
    state["log"].append(f"Boss attacks! Deals {dmg} damage.")


def reduce_cooldowns(state: dict) -> None:
    for skill in state["player"]["skills"]:
        if skill["cd"] > 0:
            skill["cd"] -= 1


def process_turn(state: dict, skill_index: int) -> None:
    if state["player"]["hp"] <= 0 or state["enemy"]["hp"] <= 0:
        return

    if state["turn"] != "player":
        state["log"].append("Wait for your turn.")
        return

    skills = state["player"]["skills"]
    if skill_index < 0 or skill_index >= len(skills):
        state["log"].append("Invalid skill.")
        return

    skill = skills[skill_index]

    if skill["cd"] > 0:
        state["log"].append(f"{skill['name']} is on cooldown.")
        return

    state["enemy"]["hp"] -= skill["dmg"]
    state["log"].append(f"You used {skill['name']} and dealt {skill['dmg']} damage.")
    skill["cd"] = skill["max_cd"]

    clamp_hp(state)

    if state["enemy"]["hp"] <= 0:
        state["log"].append("YOU WIN!")
        state["turn"] = "finished"
        trim_log(state)
        return

    state["turn"] = "enemy"

    enemy_attack(state)
    reduce_cooldowns(state)
    clamp_hp(state)

    if state["player"]["hp"] <= 0:
        state["log"].append("YOU DIED...")
        state["turn"] = "finished"
    else:
        state["turn"] = "player"
        state["round"] = int(state.get("round", 1)) + 1

    trim_log(state)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    username = ws.query_params.get("username", "").strip().lower()
    session_token = ws.query_params.get("session_token", "").strip()

    await ws.accept()

    if not username or not session_token:
        await ws.send_json({"error": "Missing username or session_token"})
        await ws.close(code=1008)
        return

    if not validate_session(username, session_token):
        await ws.send_json({"error": "Invalid session"})
        await ws.close(code=1008)
        return

    battle_state = load_battle_state(username)
    await ws.send_json(battle_state)

    try:
        while True:
            raw = await ws.receive_text()
            payload = json.loads(raw)

            action = payload.get("action")

            if action == "reset":
                battle_state = make_default_battle_state(username)
                save_battle_state(username, battle_state)
                await ws.send_json(battle_state)
                continue

            skill_i = payload.get("skill")
            if not isinstance(skill_i, int):
                battle_state["log"].append("Invalid action payload.")
                trim_log(battle_state)
                await ws.send_json(battle_state)
                continue

            process_turn(battle_state, skill_i)
            save_battle_state(username, battle_state)
            await ws.send_json(battle_state)

    except WebSocketDisconnect:
        return
    except Exception as ex:
        await ws.send_json({"error": f"Server error: {str(ex)}"})
        await ws.close(code=1011)