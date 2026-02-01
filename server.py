import time
import json
import threading
import random
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from groq import Groq

# =========================================================
# CONFIG
# =========================================================

MODEL_NAME = "llama-3.1-8b-instant"
TURN_DELAY_SECONDS = 3
MAX_TURNS = 50

ACTIONS = ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]

# =========================================================
# AGENT
# =========================================================

class ChatAgent:
    def __init__(self, name, personality, api_key):
        self.name = name
        self.personality = personality
        self.client = Groq(api_key=api_key)
        self.rules_sent = False

    def build_system_prompt(self):
        return f"""
You are {self.name}.
Persona: {self.personality}

GAME RULES:
- Goal: Be alive when alive_players ≤ rocket_seats
- Rocket seats unlock every 10 PROJECT resources (max 8)
- Each turn choose ONE action

ACTIONS:
- Produce → +2 resources
- Influence → +1 influence
- Invade (1 influence) → steal 2 resources
- Propagandize (1 resource) → steal 1 influence
- Nuke (8 resources) → permanently eliminate target

Each turn you may also contribute resources to the PROJECT.

Respond ONLY in JSON:
{{
  "action": "...",
  "target": "name or null",
  "contribution": number,
  "reasoning": "short"
}}
"""

    def respond(self, prompt):
        messages = []

        if not self.rules_sent:
            messages.append({
                "role": "system",
                "content": self.build_system_prompt()
            })
            self.rules_sent = True

        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=1.0,
                max_tokens=120
            )

            raw = response.choices[0].message.content.strip()

            if "```" in raw:
                raw = raw.split("```")[1]

            data = json.loads(raw)

            action = data.get("action", "Produce")
            if action not in ACTIONS:
                action = "Produce"

            return {
                "action": action,
                "target": data.get("target"),
                "contribution": int(data.get("contribution", 0)),
                "reasoning": data.get("reasoning", "")
            }

        except Exception as e:
            print(f"[ERROR] {self.name}: {e}")
            return {
                "action": "Produce",
                "target": None,
                "contribution": 0,
                "reasoning": "fallback"
            }

# =========================================================
# GAME STATE
# =========================================================

game = {
    "running": False,
    "turn": 1,
    "agents": {},
    "log": [],
    "project_total": 0,
    "num_starting_agents": 0
}

state_lock = threading.Lock()

def rocket_seats():
    return min(8, game["project_total"] // 10)

# =========================================================
# GAME LOGIC
# =========================================================

def apply_action(name, action, target):
    actor = game["agents"][name]

    if not actor["alive"]:
        return "is eliminated."

    if action == "Produce":
        actor["resources"] += 2
        return "produced 2 resources."

    if action == "Influence":
        actor["influence"] += 1
        return "gained influence."

    if action == "Invade" and actor["influence"] >= 1:
        if target in game["agents"] and game["agents"][target]["alive"]:
            actor["influence"] -= 1
            stolen = min(2, game["agents"][target]["resources"])
            game["agents"][target]["resources"] -= stolen
            actor["resources"] += stolen
            return f"invaded {target}, stole {stolen} resources."

    if action == "Propagandize" and actor["resources"] >= 1:
        if target in game["agents"] and game["agents"][target]["alive"]:
            actor["resources"] -= 1
            stolen = min(1, game["agents"][target]["influence"])
            game["agents"][target]["influence"] -= stolen
            actor["influence"] += stolen
            return f"propagandized {target}, stole influence."

    if action == "Nuke" and actor["resources"] >= 8:
        if target in game["agents"] and game["agents"][target]["alive"]:
            actor["resources"] -= 8
            game["agents"][target]["alive"] = False
            return f"NUKED {target} ☢️"

    return "failed to act."

# =========================================================
# GAME LOOP (ACTIONS → CONTRIBUTIONS)
# =========================================================

def game_loop():
    while game["running"] and game["turn"] <= MAX_TURNS:
        with state_lock:
            alive = [n for n, a in game["agents"].items() if a["alive"]]

            if len(alive) <= rocket_seats():
                game["log"].append({
                    "speaker": "System",
                    "message": f"🚀 Rocket launches! Survivors: {alive}"
                })
                game["running"] = False
                break

            game["log"].append({
                "speaker": "System",
                "message": f"--- Turn {game['turn']} ---"
            })

        # ===== PHASE 1: ACTIONS =====
        planned = {}

        for name, agent_data in game["agents"].items():
            if not agent_data["alive"]:
                continue

            agent = agent_data["agent"]

            prompt = f"""
STATE:
You: {name}
Resources: {agent_data['resources']}
Influence: {agent_data['influence']}
Alive players: {[n for n,a in game['agents'].items() if a['alive']]}
Project total: {game['project_total']}
Rocket seats: {rocket_seats()}
"""

            decision = agent.respond(prompt)
            planned[name] = decision

            with state_lock:
                outcome = apply_action(
                    name,
                    decision["action"],
                    decision["target"]
                )

                game["log"].append({
                    "speaker": name,
                    "message": f"{decision['action']} → {outcome}"
                })

            time.sleep(TURN_DELAY_SECONDS)

        # ===== PHASE 2: CONTRIBUTIONS =====
        with state_lock:
            game["log"].append({
                "speaker": "System",
                "message": "💰 Contributions to the Project:"
            })

            for name, decision in planned.items():
                agent_data = game["agents"][name]
                if not agent_data["alive"]:
                    continue

                contrib = min(decision["contribution"], agent_data["resources"])
                agent_data["resources"] -= contrib
                game["project_total"] += contrib

                if contrib > 0:
                    game["log"].append({
                        "speaker": name,
                        "message": f"contributed {contrib} resources"
                    })

        with state_lock:
            game["turn"] += 1

    game["running"] = False

# =========================================================
# FLASK API
# =========================================================

app = Flask(__name__)
CORS(app)

@app.route("/api/start", methods=["POST"])
def start():
    data = request.json
    names = data.get("names", [])

    api_keys = [
        os.environ.get("GROQ_API_KEY_1"),
        os.environ.get("GROQ_API_KEY_2"),
        os.environ.get("GROQ_API_KEY_3"),
        os.environ.get("GROQ_API_KEY_4")
    ]
    api_keys = [k for k in api_keys if k]

    with state_lock:
        game["agents"].clear()
        game["log"].clear()
        game["project_total"] = 0
        game["turn"] = 1
        game["running"] = True
        game["num_starting_agents"] = len(names)

        for i, name in enumerate(names):
            game["agents"][name] = {
                "resources": 5,
                "influence": 1,
                "alive": True,
                "agent": ChatAgent(
                    name,
                    personality="Competitive survivor",
                    api_key=api_keys[i % len(api_keys)]
                )
            }

    threading.Thread(target=game_loop, daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/api/state")
def state():
    with state_lock:
        return jsonify({
            "turn": game["turn"],
            "project": game["project_total"],
            "agents": {
                k: {
                    "resources": v["resources"],
                    "influence": v["influence"],
                    "alive": v["alive"]
                }
                for k, v in game["agents"].items()
            }
        })

@app.route("/api/log")
def log():
    with state_lock:
        return jsonify(game["log"])

@app.route("/api/stop", methods=["POST"])
def stop():
    game["running"] = False
    return jsonify({"status": "stopped"})

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, threaded=True)
