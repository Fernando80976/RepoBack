from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

# CORS (para React)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Estado del combate
battle_state = {
    "player": {
        "hp": 120,
        "max_hp": 120,
        "skills": [
            {"name": "Quick Slash", "dmg": 15, "cd": 0, "max_cd": 0},
            {"name": "Shadow Burst", "dmg": 25, "cd": 2, "max_cd": 2},
            {"name": "Critical Stab", "dmg": 35, "cd": 3, "max_cd": 3}
        ]
    },
    "enemy": {
        "name": "Knight-Level Boss",
        "hp": 150,
        "max_hp": 150,
    },
    "turn": "player",
    "log": ["A Knight-Level Boss emerges from the shadows..."]
}

def enemy_attack():
    import random
    dmg = random.randint(10, 22)
    battle_state["player"]["hp"] -= dmg
    battle_state["log"].append(f"Boss attacks! Deals {dmg} damage.")

def reduce_cooldowns():
    for skill in battle_state["player"]["skills"]:
        if skill["cd"] > 0:
            skill["cd"] -= 1

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await ws.send_json(battle_state)

    while True:
        data = await ws.receive_text()
        data = json.loads(data)

        if battle_state["turn"] == "player":
            skill_i = data.get("skill")
            skill = battle_state["player"]["skills"][skill_i]

            if skill["cd"] > 0:
                battle_state["log"].append("Skill on cooldown!")
            else:
                battle_state["enemy"]["hp"] -= skill["dmg"]
                battle_state["log"].append(f"You used {skill['name']}!")

                skill["cd"] = skill["max_cd"]
                battle_state["turn"] = "enemy"

        if battle_state["enemy"]["hp"] <= 0:
            battle_state["log"].append("YOU WIN!")
            await ws.send_json(battle_state)
            continue

        # ENEMY TURN
        if battle_state["turn"] == "enemy":
            enemy_attack()
            battle_state["turn"] = "player"
            reduce_cooldowns()

        if battle_state["player"]["hp"] <= 0:
            battle_state["log"].append("YOU DIED...")

        await ws.send_json(battle_state)
