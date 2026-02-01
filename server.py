from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import threading
import time
import random
import os

app = Flask(__name__)
CORS(app)

# Lock to protect game state modifications
state_lock = threading.Lock()

# Import ChatAgent
from chat import ChatAgent

# Multiple API keys for rotation to avoid rate limiting
API_KEYS_ENV = os.environ.get('GROQ_API_KEYS', '')
if API_KEYS_ENV:
    API_KEYS = [key.strip() for key in API_KEYS_ENV.split(',') if key.strip()]
else:
    # Fallback for local development
    API_KEYS = [
        os.environ.get("groq_key_1"),
        os.environ.get("groq_key_2"),
        os.environ.get("groq_key_3"),
        os.environ.get("groq_key_4")
    ]

API_KEYS = [key for key in API_KEYS if key]

print(f"Loaded {len(API_KEYS)} Groq API key(s)")

current_key_index = 0

def get_next_api_key():
    """Rotate through API keys to distribute load"""
    global current_key_index
    key = API_KEYS[current_key_index]
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    return key

# 10 distinct character personas for AI agents
PERSONALITIES = [
    {"name": "Cowboy", "description": "Wild West cowboy - uses 'partner', 'reckon', 'varmint'"},
    {"name": "Pirate", "description": "Pirate - says 'arr', 'matey', 'scallywag'"},
    {"name": "Knight", "description": "Medieval knight - formal, honorable"},
    {"name": "Scientist", "description": "Mad scientist - analytical"},
    {"name": "Gangster", "description": "1920s mobster - says 'see?', 'wise guy'"},
    {"name": "ValleyGirl", "description": "Valley girl - says 'like', 'totally'"},
    {"name": "Shakespeare", "description": "Shakespearean - flowery dramatic language"},
    {"name": "General", "description": "Military general - tactical commands"},
    {"name": "Robot", "description": "Robot - cold logic, ALL CAPS"},
    {"name": "Surfer", "description": "Surfer - says 'dude', 'gnarly', 'radical'"}
]

game_session = {
    "agents": {},
    "conversation": [],
    "game_state": {},
    "running": False,
    "human_player": None,
    "waiting_for_human": False,
    "human_action": None,
    "human_target": None,
    "waiting_for_contribution": False,
    "human_contribution": None,
    "num_starting_agents": 0,
    "agent_memory": {}
}

# Seats thresholds for the rocket project
SEATS_THRESHOLDS = [
    (0, 0), (10, 1), (20, 2), (30, 3), (40, 4),
    (50, 5), (60, 6), (70, 7), (80, 8)
]

TURN_DELAY = 3  # 3 second delay between each agent's turn

def calculate_available_seats(project_total, num_starting_agents):
    """Calculate how many seats are available based on project total"""
    seats = 0
    for threshold, seat_count in SEATS_THRESHOLDS:
        if project_total >= threshold:
            seats = seat_count
        else:
            break
    
    max_seats = max(0, num_starting_agents - 1)
    return min(seats, max_seats)

# ------------------- Memory System -------------------

def initialize_agent_memory(agent_names):
    """Initialize memory tracking for all agents"""
    memory = {}
    for name in agent_names:
        memory[name] = {
            "times_invaded_by": {},
            "times_nuked_at_by": {},
            "times_propagandized_by": {},
            "invaded_targets": {},
            "contribution_pattern": [],
            "alliance_score": {},
            "biggest_threat": None,
            "was_leader": False
        }
    return memory

def update_memory_for_action(memory, agent_name, action, target, state):
    """Update memory based on an action taken"""
    if not target or target not in memory:
        return
    
    if action == "Invade":
        if agent_name not in memory[target]["times_invaded_by"]:
            memory[target]["times_invaded_by"][agent_name] = 0
        memory[target]["times_invaded_by"][agent_name] += 1
        
        if target not in memory[agent_name]["invaded_targets"]:
            memory[agent_name]["invaded_targets"][target] = 0
        memory[agent_name]["invaded_targets"][target] += 1
        
        if agent_name not in memory[target]["alliance_score"]:
            memory[target]["alliance_score"][agent_name] = 0
        memory[target]["alliance_score"][agent_name] -= 2
        
    elif action == "Nuke":
        if state["agents"][target]["alive"]:
            if agent_name not in memory[target]["times_nuked_at_by"]:
                memory[target]["times_nuked_at_by"][agent_name] = 0
            memory[target]["times_nuked_at_by"][agent_name] += 1
        
        if agent_name not in memory[target]["alliance_score"]:
            memory[target]["alliance_score"][agent_name] = 0
        memory[target]["alliance_score"][agent_name] -= 10
        
    elif action == "Propagandize":
        if agent_name not in memory[target]["times_propagandized_by"]:
            memory[target]["times_propagandized_by"][agent_name] = 0
        memory[target]["times_propagandized_by"][agent_name] += 1
        
        if agent_name not in memory[target]["alliance_score"]:
            memory[target]["alliance_score"][agent_name] = 0
        memory[target]["alliance_score"][agent_name] -= 1

def update_memory_for_contribution(memory, contributions, leader_name):
    """Update memory based on contributions"""
    for agent_name, amount in contributions.items():
        if agent_name not in memory:
            continue
        
        memory[agent_name]["contribution_pattern"].append(amount)
        if len(memory[agent_name]["contribution_pattern"]) > 3:
            memory[agent_name]["contribution_pattern"].pop(0)
        
        if agent_name == leader_name:
            memory[agent_name]["was_leader"] = True
        
        if amount > 0:
            for other_agent in memory:
                if other_agent != agent_name:
                    if agent_name not in memory[other_agent]["alliance_score"]:
                        memory[other_agent]["alliance_score"][agent_name] = 0
                    memory[other_agent]["alliance_score"][agent_name] += 0.5

def update_threat_assessment(memory, state):
    """Update who is the biggest threat based on resources"""
    agents_state = state["agents"]
    for agent_name in memory:
        if not agents_state[agent_name]["alive"]:
            continue
        
        max_resources = -1
        biggest_threat = None
        for other_name, stats in agents_state.items():
            if other_name != agent_name and stats["alive"] and stats["resources"] > max_resources:
                max_resources = stats["resources"]
                biggest_threat = other_name
        
        memory[agent_name]["biggest_threat"] = biggest_threat

def build_memory_context(name, memory, state):
    """Build compact memory context for an agent"""
    if name not in memory:
        return ""
    
    agent_mem = memory[name]
    context = []
    
    attackers = []
    for attacker, count in agent_mem["times_invaded_by"].items():
        if state["agents"].get(attacker, {}).get("alive", False):
            attackers.append(f"{attacker}({count}x)")
    if attackers:
        context.append(f"GRUDGES - Invaded by: {', '.join(attackers)}")
    
    nukers = []
    for nuker, count in agent_mem["times_nuked_at_by"].items():
        if state["agents"].get(nuker, {}).get("alive", False):
            nukers.append(f"{nuker}({count}x)")
    if nukers:
        context.append(f"ATTEMPTED NUKES by: {', '.join(nukers)}")
    
    allies = []
    enemies = []
    for other_agent, score in agent_mem["alliance_score"].items():
        if not state["agents"].get(other_agent, {}).get("alive", False):
            continue
        if score >= 2:
            allies.append(f"{other_agent}(+{int(score)})")
        elif score <= -3:
            enemies.append(f"{other_agent}({int(score)})")
    
    if allies:
        context.append(f"ALLIES: {', '.join(allies[:3])}")
    if enemies:
        context.append(f"ENEMIES: {', '.join(enemies[:3])}")
    
    if len(agent_mem["contribution_pattern"]) > 0:
        avg_contrib = sum(agent_mem["contribution_pattern"]) / len(agent_mem["contribution_pattern"])
        if avg_contrib > 2:
            context.append(f"You've been contributing (avg {avg_contrib:.1f}/turn)")
        elif avg_contrib == 0:
            context.append(f"You've never contributed to PROJECT")
    
    if agent_mem["biggest_threat"]:
        threat = agent_mem["biggest_threat"]
        threat_resources = state["agents"][threat]["resources"]
        if threat_resources >= 6:
            context.append(f"⚠️ THREAT: {threat} has {threat_resources}R (nuke range!)")
    
    if agent_mem["invaded_targets"]:
        top_target = max(agent_mem["invaded_targets"].items(), key=lambda x: x[1])
        if top_target[1] >= 2:
            context.append(f"You've invaded {top_target[0]} {top_target[1]} times")
    
    if context:
        return "MEMORY:\n" + "\n".join(context[:5]) + "\n\n"
    return ""

# ------------------- Helper Functions -------------------

def get_valid_targets_for_invade(name, state):
    """Get list of agents that have resources to steal"""
    agents_state = state["agents"]
    return [a for a in agents_state if a != name and agents_state[a]["alive"] and agents_state[a]["resources"] > 0]

def get_valid_targets_for_propagandize(name, state):
    """Get list of agents that have influence to steal"""
    agents_state = state["agents"]
    return [a for a in agents_state if a != name and agents_state[a]["alive"] and agents_state[a]["influence"] > 0]

def get_valid_targets_for_nuke(name, state):
    """Get list of alive agents that can be nuked"""
    agents_state = state["agents"]
    return [a for a in agents_state if a != name and agents_state[a]["alive"]]

def can_perform_action(name, action, state):
    """Check if an agent can perform the requested action"""
    agents_state = state["agents"]
    if not agents_state[name]["alive"]:
        return False, "Agent is not alive"
    
    if action in ["Produce", "Influence"]:
        return True, "Action allowed"
    elif action == "Invade":
        if agents_state[name]["influence"] < 1:
            return False, f"Need 1 influence"
        if not get_valid_targets_for_invade(name, state):
            return False, "No targets with resources"
        return True, "Action allowed"
    elif action == "Propagandize":
        if agents_state[name]["resources"] < 1:
            return False, f"Need 1 resource"
        if not get_valid_targets_for_propagandize(name, state):
            return False, "No targets with influence"
        return True, "Action allowed"
    elif action == "Nuke":
        if agents_state[name]["resources"] < 8:
            return False, f"Need 8 resources"
        if not get_valid_targets_for_nuke(name, state):
            return False, "No alive targets"
        return True, "Action allowed"
    
    return False, "Unknown action"

def apply_action(name, action, target, state):
    """Apply an agent's action to the game state"""
    with state_lock:
        agents_state = state["agents"]
        if not agents_state[name]["alive"]:
            return None

        result_message = None
        
        if action == "Produce":
            agents_state[name]["resources"] += 2
            result_message = f"gained 2 resources"
            
        elif action == "Influence":
            agents_state[name]["influence"] += 1
            result_message = f"gained 1 influence"
            
        elif action == "Invade":
            if agents_state[name]["influence"] < 1:
                return "tried to invade but has no influence"
            
            agents_state[name]["influence"] -= 1
            valid_targets = get_valid_targets_for_invade(name, state)
            
            if target and target in valid_targets:
                chosen_target = target
            elif valid_targets:
                chosen_target = random.choice(valid_targets)
            else:
                agents_state[name]["influence"] += 1
                return "tried to invade but no valid targets"
            
            stolen = min(2, agents_state[chosen_target]["resources"])
            agents_state[chosen_target]["resources"] -= stolen
            agents_state[name]["resources"] += stolen
            result_message = f"invaded {chosen_target} and stole {stolen} resources"
                
        elif action == "Propagandize":
            if agents_state[name]["resources"] < 1:
                return "tried to propagandize but has no resources"
            
            agents_state[name]["resources"] -= 1
            valid_targets = get_valid_targets_for_propagandize(name, state)
            
            if target and target in valid_targets:
                chosen_target = target
            elif valid_targets:
                chosen_target = random.choice(valid_targets)
            else:
                agents_state[name]["resources"] += 1
                return "tried to propagandize but no valid targets"
            
            stolen = min(1, agents_state[chosen_target]["influence"])
            agents_state[chosen_target]["influence"] -= stolen
            agents_state[name]["influence"] += stolen
            result_message = f"propagandized against {chosen_target} and stole {stolen} influence"
                
        elif action == "Nuke":
            if agents_state[name]["resources"] < 8:
                return "tried to nuke but has insufficient resources"
            
            agents_state[name]["resources"] -= 8
            valid_targets = get_valid_targets_for_nuke(name, state)
            
            if target and target in valid_targets:
                chosen_target = target
            elif valid_targets:
                chosen_target = random.choice(valid_targets)
            else:
                agents_state[name]["resources"] += 8
                return "tried to nuke but target was eliminated"
            
            agents_state[chosen_target]["alive"] = False
            result_message = f"NUKED {chosen_target} - they are eliminated!"
        
        return result_message

def build_minimal_prompt(name, state, conversation, memory):
    """Build minimal strategic prompt with memory context"""
    agents_state = state["agents"]
    alive_count = len([n for n, s in agents_state.items() if s["alive"]])
    available_seats = state.get("available_seats", 0)
    
    prompt = f"Turn {state['turn']}: {alive_count} alive, {available_seats} seats, {state['project_total']} PROJECT\n\n"
    
    memory_context = build_memory_context(name, memory, state)
    if memory_context:
        prompt += memory_context
    
    my_stats = agents_state[name]
    prompt += f"YOU: R={my_stats['resources']}, I={my_stats['influence']}\n\n"
    
    prompt += "OPPONENTS:\n"
    alive_opponents = [(n, s) for n, s in agents_state.items() if n != name and s["alive"]]
    alive_opponents.sort(key=lambda x: x[1]["resources"], reverse=True)
    
    for opponent_name, stats in alive_opponents:
        last_action = "..."
        for msg in reversed(conversation[-20:]):
            if msg.get('speaker') == opponent_name:
                last_action = msg['message'].split('—')[0].strip()
                break
        
        prompt += f"{opponent_name}: R={stats['resources']}, I={stats['influence']} | Last: {last_action}\n"
    
    prompt += f"\nDecide action + contribution (0-{my_stats['resources']}):"
    
    return prompt

# ------------------- Game Loop -------------------

def run_game(num_agents, has_human):
    """Main game loop - SEQUENTIAL turns"""
    agent_names = list(game_session["agents"].keys())
    conversation = game_session["conversation"]
    state = game_session["game_state"]
    
    memory = initialize_agent_memory(agent_names)
    game_session["agent_memory"] = memory

    human_name = game_session["human_player"]
    
    # Sort so human goes first
    if human_name:
        agent_names = [human_name] + [name for name in agent_names if name != human_name]
    
    conversation.append({
        "speaker": "System",
        "message": f"=== BATTLE COMMENCED: {num_agents} AGENTS ===",
        "time": time.time()
    })
    
    if has_human:
        conversation.append({
            "speaker": "System",
            "message": f"🎮 HUMAN: {human_name}",
            "time": time.time()
        })

    while game_session["running"] and state["turn"] <= state["max_turns"]:
        alive_agents = [name for name in agent_names if state["agents"][name]["alive"]]
        
        available_seats = calculate_available_seats(state["project_total"], state["num_starting_agents"])
        state["available_seats"] = available_seats
        
        conversation.append({
            "speaker": "System",
            "message": f"--- Turn {state['turn']} ---",
            "time": time.time()
        })

        # Check win condition
        if len(alive_agents) <= available_seats:
            if len(alive_agents) > 0:
                winners = alive_agents
                conversation.append({
                    "speaker": "System",
                    "message": f"🚀 ROCKET LAUNCH! {len(winners)} agent(s) escape!",
                    "time": time.time()
                })
                conversation.append({
                    "speaker": "System",
                    "message": f"🏆 WINNERS: {', '.join(winners)}",
                    "time": time.time()
                })
            else:
                conversation.append({
                    "speaker": "System",
                    "message": "⚔️ ALL AGENTS ELIMINATED",
                    "time": time.time()
                })
            break

        round_contributions = {}
        
        # ==================== PHASE 1: SEQUENTIAL ACTIONS ====================
        contribution_explanations = {}

        for name in agent_names:
            if not state["agents"][name]["alive"]:
                continue
            
            is_human = (name == human_name)
            
            if is_human:
                # Handle human action
                game_session["waiting_for_human"] = True
                game_session["human_action"] = None
                game_session["human_target"] = None
                
                conversation.append({
                    "speaker": "System",
                    "message": f"⏳ Waiting for {human_name} action...",
                    "time": time.time()
                })
                
                timeout = 30
                waited = 0
                while game_session["human_action"] is None and waited < timeout:
                    time.sleep(0.5)
                    waited += 0.5
                
                game_session["waiting_for_human"] = False
                
                if game_session["human_action"] is None:
                    chosen_action = "Produce"
                    chosen_target = None
                    explanation = "Timeout"
                else:
                    chosen_action = game_session["human_action"]
                    chosen_target = game_session["human_target"]
                    explanation = "Human choice"
                
                can_perform, error_message = can_perform_action(human_name, chosen_action, state)
                if not can_perform:
                    chosen_action = "Produce"
                    explanation = "Invalid - auto produced"
                    chosen_target = None
                    
            else:
                # Handle AI action
                print(f"🎯 {name}'s turn")
                
                agent = game_session["agents"][name]
                minimal_prompt = build_minimal_prompt(name, state, conversation, memory)
                
                try:
                    result = agent.respond(minimal_prompt)
                    chosen_action = result["action"]
                    chosen_target = result.get("target", None)
                    contribution = result.get("contribution", 0)
                    explanation = result["explanation"]

                    contribution_explanation = result.get("contribution_explanation", "Strategic decision")
                    
                    can_perform, error_message = can_perform_action(name, chosen_action, state)
                    if not can_perform:
                        print(f"✗ {name} invalid action, forcing Produce")
                        chosen_action = "Produce"
                        chosen_target = None
                    
                    max_contrib = state["agents"][name]["resources"]
                    contribution = max(0, min(contribution, max_contrib))
                    round_contributions[name] = contribution
                    
                    print(f"✓ {name}: {chosen_action}" + (f" -> {chosen_target}" if chosen_target else "") + f" + will contribute {contribution}")
                    
                except Exception as e:
                    print(f"✗ Error from {name}: {e}")
                    chosen_action = "Produce"
                    chosen_target = None
                    explanation = "Error"
                    round_contributions[name] = 0
            
            # Apply action
            action_result = apply_action(name, chosen_action, chosen_target, state)
            
            if chosen_target:
                update_memory_for_action(memory, name, chosen_action, chosen_target, state)
            
            message_text = f"{chosen_action}"
            if action_result:
                message_text += f" — {action_result}"
            if explanation:
                message_text += f" | {explanation}"
            
            conversation.append({
                "speaker": name,
                "message": message_text,
                "time": time.time()
            })
            
            # 3 second delay after each agent's action
            time.sleep(TURN_DELAY)
        
        # In the run_game function, find the contribution phase section and update it:

    # ==================== PHASE 2: SEQUENTIAL CONTRIBUTIONS ====================
    conversation.append({
        "speaker": "System",
        "message": "💰 Contribution Phase:",
        "time": time.time()
    })

    # Store contribution explanations from earlier
    contribution_explanations = {}

    for name in agent_names:
        if not state["agents"][name]["alive"]:
            continue
        
        is_human = (name == human_name)
        
        if is_human:
            # Handle human contribution
            game_session["waiting_for_contribution"] = True
            game_session["human_contribution"] = None
            
            conversation.append({
                "speaker": "System",
                "message": f"⏳ Waiting for {human_name} contribution...",
                "time": time.time()
            })
            
            timeout = 30
            waited = 0
            while game_session["human_contribution"] is None and waited < timeout:
                time.sleep(0.5)
                waited += 0.5
            
            game_session["waiting_for_contribution"] = False
            
            contribution = game_session["human_contribution"] if game_session["human_contribution"] is not None else 0
            max_contrib = state["agents"][human_name]["resources"]
            contribution = max(0, min(contribution, max_contrib))
            round_contributions[human_name] = contribution
            contrib_message = "Human choice"
        else:
            # AI contribution was already decided during action phase
            contribution = round_contributions.get(name, 0)
            contrib_message = contribution_explanations.get(name, "Strategic decision")
        
        # Apply contribution
        if contribution > 0:
            state["agents"][name]["resources"] -= contribution
            state["project_total"] += contribution
        
        conversation.append({
            "speaker": name,
            "message": f"Contributed {contribution} resources | {contrib_message}",  # CHANGE THIS LINE
            "time": time.time()
        })
        
        # 3 second delay after each contribution
        time.sleep(TURN_DELAY)
        
        # Determine round leader
        if round_contributions:
            max_contribution = max(round_contributions.values())
            if max_contribution > 0:
                leaders = [name for name, contrib in round_contributions.items() if contrib == max_contribution]
                
                if len(leaders) == 1:
                    leader = leaders[0]
                    state["project_leader"] = leader
                    state["agents"][leader]["influence"] += 1
                    
                    update_memory_for_contribution(memory, round_contributions, leader)
                    
                    conversation.append({
                        "speaker": "System",
                        "message": f"🏆 {leader} is PROJECT LEADER! (+1 influence)",
                        "time": time.time()
                    })
                else:
                    update_memory_for_contribution(memory, round_contributions, None)
                    
                    conversation.append({
                        "speaker": "System",
                        "message": f"🤝 TIE - no leader",
                        "time": time.time()
                    })
        
        update_threat_assessment(memory, state)
        
        alive_count = len([name for name in agent_names if state["agents"][name]["alive"]])
        state["available_seats"] = calculate_available_seats(state["project_total"], state["num_starting_agents"])
        
        conversation.append({
            "speaker": "System",
            "message": f"📊 PROJECT: {state['project_total']} | SEATS: {state['available_seats']}/{alive_count}",
            "time": time.time()
        })

        state["turn"] += 1

    game_session["running"] = False
    game_session["waiting_for_human"] = False
    game_session["waiting_for_contribution"] = False
    conversation.append({
        "speaker": "System",
        "message": "=== BATTLE CONCLUDED ===",
        "time": time.time()
    })

# ------------------- Flask Routes -------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_game_route():
    try:
        data = request.json
        num_agents = int(data.get("num_agents", 10))
        include_human = data.get("include_human", False)
        
        if num_agents < 2 or num_agents > 10:
            return jsonify({"error": "Number of agents must be between 2 and 10"}), 400

        game_session["running"] = False
        time.sleep(0.5)

        game_session["conversation"] = []
        game_session["agents"] = {}
        game_session["agent_memory"] = {}
        game_session["human_player"] = None
        game_session["waiting_for_human"] = False
        game_session["human_action"] = None
        game_session["human_target"] = None
        game_session["waiting_for_contribution"] = False
        game_session["human_contribution"] = None
        game_session["num_starting_agents"] = num_agents
        game_session["game_state"] = {
            "turn": 1,
            "max_turns": 30,
            "agents": {},
            "project_total": 0,
            "project_leader": None,
            "available_seats": 0,
            "num_starting_agents": num_agents
        }

        available_personalities = PERSONALITIES.copy()
        random.shuffle(available_personalities)
        
        if include_human:
            name = "Human"
            game_session["human_player"] = name
            game_session["agents"][name] = None
            game_session["game_state"]["agents"][name] = {
                "resources": 0,
                "influence": 0,
                "alive": True
            }
            print(f"✓ Created {name} as HUMAN PLAYER")
        
        num_ai_agents = num_agents - (1 if include_human else 0)
        for i in range(num_ai_agents):
            personality_data = available_personalities[i % len(available_personalities)]
            name = personality_data["name"]
            personality_desc = personality_data["description"]
            
            api_key = get_next_api_key()
            
            game_session["agents"][name] = ChatAgent(
                api_key=api_key,
                name=name,
                personality=personality_desc
            )
            print(f"✓ Created {name}")
            
            game_session["game_state"]["agents"][name] = {
                "resources": 0,
                "influence": 0,
                "alive": True
            }

        game_session["running"] = True
        threading.Thread(target=run_game, args=(num_agents, include_human), daemon=True).start()

        print(f"✓ Game started - SEQUENTIAL VERSION")
        
        return jsonify({
            "status": "Game started!", 
            "num_agents": num_agents,
            "has_human": include_human,
            "human_name": game_session["human_player"]
        })
    
    except Exception as e:
        print(f"✗ Error starting game: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/conversation')
def get_conversation():
    return jsonify({
        "conversation": game_session.get("conversation", []),
        "running": game_session.get("running", False)
    })

@app.route('/api/game_state')
def get_game_state():
    state = game_session.get("game_state", {})
    agents_state = state.get("agents", {})
    return jsonify({
        "agents": agents_state,
        "turn": state.get("turn", 1),
        "max_turns": state.get("max_turns", 30),
        "running": game_session.get("running", False),
        "waiting_for_human": game_session.get("waiting_for_human", False),
        "waiting_for_contribution": game_session.get("waiting_for_contribution", False),
        "human_player": game_session.get("human_player", None),
        "project_total": state.get("project_total", 0),
        "project_leader": state.get("project_leader", None),
        "available_seats": state.get("available_seats", 0),
        "num_starting_agents": state.get("num_starting_agents", 0)
    })

@app.route('/api/human_action', methods=['POST'])
def submit_human_action():
    try:
        data = request.json
        action = data.get("action")
        target = data.get("target", None)
        
        if action not in ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]:
            return jsonify({"error": "Invalid action"}), 400
        
        if not game_session.get("waiting_for_human", False):
            return jsonify({"error": "Not waiting for human input"}), 400
        
        game_session["human_action"] = action
        game_session["human_target"] = target
        print(f"✓ Human: {action}" + (f" -> {target}" if target else ""))
        
        return jsonify({"status": "Action submitted", "action": action, "target": target})
    
    except Exception as e:
        print(f"✗ Error submitting human action: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/human_contribution', methods=['POST'])
def submit_human_contribution():
    try:
        data = request.json
        contribution = int(data.get("contribution", 0))
        
        if contribution < 0:
            return jsonify({"error": "Contribution must be non-negative"}), 400
        
        if not game_session.get("waiting_for_contribution", False):
            return jsonify({"error": "Not waiting for contribution input"}), 400
        
        game_session["human_contribution"] = contribution
        print(f"✓ Human contributed: {contribution}")
        
        return jsonify({"status": "Contribution submitted", "contribution": contribution})
    
    except Exception as e:
        print(f"✗ Error submitting human contribution: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_game():
    game_session["running"] = False
    return jsonify({"status": "Game stopped"})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🎮 AI BATTLEGROUND - SEQUENTIAL EDITION")
    print("="*50)
    print("✓ 3 second delay between each agent")
    print("✓ One AI call at a time")
    print("✓ Actions → Contributions (sequential)")
    print("="*50 + "\n")
    
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, threaded=True)