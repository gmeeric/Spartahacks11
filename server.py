from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import threading
import time
import random

app = Flask(__name__)
CORS(app)

# Try to import ChatAgent, but use mock if it fails
try:
    from chat import ChatAgent
    USE_REAL_AI = True
    print("✓ ChatAgent imported successfully")
except Exception as e:
    print(f"⚠ Could not import ChatAgent: {e}")
    print("⚠ Using mock AI responses for testing")
    USE_REAL_AI = False
    
    # Mock ChatAgent for testing
    class ChatAgent:
        def __init__(self, api_key, name, personality):
            self.name = name
            self.personality = personality
        
        def respond(self, message):
            # Intelligent mock responses based on game state
            actions = ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]
            weights = [30, 20, 25, 15, 10]  # Weighted probability
            
            # Parse the message to make smarter decisions
            if "resources=" in message:
                try:
                    # Extract this agent's resources
                    lines = message.split('\n')
                    for line in lines:
                        if self.name in line and "resources=" in line:
                            resources = int(line.split("resources=")[1].split(",")[0])
                            # If close to 8 resources, try to nuke
                            if resources >= 8:
                                return {
                                    "action": "Nuke",
                                    "explanation": "Eliminating strongest threat"
                                }
                            elif resources >= 6:
                                weights = [10, 5, 10, 5, 70]  # Heavy bias toward Nuke
                except:
                    pass
            
            action = random.choices(actions, weights=weights)[0]
            
            explanations = {
                "Produce": [
                    "Building resources for future attacks",
                    "Stockpiling for nuke capability",
                    "Need more resources to strike"
                ],
                "Influence": [
                    "Increasing power base for invasions",
                    "Building influence to attack soon",
                    "Preparing for aggressive plays"
                ],
                "Invade": [
                    "Weakening strongest opponent",
                    "Stealing to prevent enemy nuke",
                    "Crippling rival's resources"
                ],
                "Propagandize": [
                    "Undermining opponent influence",
                    "Stealing power from threats",
                    "Weakening enemy capabilities"
                ],
                "Nuke": [
                    "Eliminating major threat",
                    "Removing strongest competitor",
                    "Securing path to victory"
                ]
            }
            
            return {
                "action": action,
                "explanation": random.choice(explanations[action])
            }

API_KEY = "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"

# 10 personalities
PERSONALITIES = [
    "optimistic, curious, loves new ideas",
    "skeptical, analytical, questions everything",
    "aggressive, risk-taking, bold",
    "strategic, calculating, patient",
    "manipulative, clever, subtle",
    "cautious, defensive, careful",
    "greedy, selfish, opportunistic",
    "cooperative but self-interested",
    "chaotic, unpredictable, reckless",
    "competitive, ambitious, focused"
]

game_session = {
    "agents": {},          # ChatAgent objects
    "conversation": [],    # List of messages
    "game_state": {},      # Turn, max_turns, agent resources
    "running": False,
    "human_player": None,  # Name of human player (if any)
    "waiting_for_human": False,  # Is game paused for human input?
    "human_action": None   # Action chosen by human
}

# ------------------- Helper -------------------

def get_valid_targets_for_invade(name, state):
    """Get list of agents that have resources to steal"""
    agents_state = state["agents"]
    valid_targets = [
        a for a in agents_state 
        if a != name 
        and agents_state[a]["alive"] 
        and agents_state[a]["resources"] > 0
    ]
    return valid_targets

def get_valid_targets_for_propagandize(name, state):
    """Get list of agents that have influence to steal"""
    agents_state = state["agents"]
    valid_targets = [
        a for a in agents_state 
        if a != name 
        and agents_state[a]["alive"] 
        and agents_state[a]["influence"] > 0
    ]
    return valid_targets

def get_valid_targets_for_nuke(name, state):
    """Get list of alive agents that can be nuked"""
    agents_state = state["agents"]
    valid_targets = [
        a for a in agents_state 
        if a != name 
        and agents_state[a]["alive"]
    ]
    return valid_targets

def can_perform_action(name, action, state):
    """Check if an agent can perform the requested action"""
    agents_state = state["agents"]
    if not agents_state[name]["alive"]:
        return False, "Agent is not alive"
    
    if action == "Produce" or action == "Influence":
        return True, "Action allowed"
    
    elif action == "Invade":
        if agents_state[name]["influence"] < 1:
            return False, f"Need 1 influence (have {agents_state[name]['influence']})"
        
        valid_targets = get_valid_targets_for_invade(name, state)
        if not valid_targets:
            return False, "No targets with resources to steal"
        
        return True, "Action allowed"
    
    elif action == "Propagandize":
        if agents_state[name]["resources"] < 1:
            return False, f"Need 1 resource (have {agents_state[name]['resources']})"
        
        valid_targets = get_valid_targets_for_propagandize(name, state)
        if not valid_targets:
            return False, "No targets with influence to steal"
        
        return True, "Action allowed"
    
    elif action == "Nuke":
        if agents_state[name]["resources"] < 8:
            return False, f"Need 8 resources (have {agents_state[name]['resources']})"
        
        valid_targets = get_valid_targets_for_nuke(name, state)
        if not valid_targets:
            return False, "No alive targets available"
        
        return True, "Action allowed"
    
    return False, "Unknown action"

def apply_action(name, action, state):
    """Apply an agent's action to the game state"""
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
        agents_state[name]["influence"] -= 1
        valid_targets = get_valid_targets_for_invade(name, state)
        target = random.choice(valid_targets)
        stolen = min(2, agents_state[target]["resources"])
        agents_state[target]["resources"] -= stolen
        agents_state[name]["resources"] += stolen
        result_message = f"invaded {target} and stole {stolen} resources"
            
    elif action == "Propagandize":
        agents_state[name]["resources"] -= 1
        valid_targets = get_valid_targets_for_propagandize(name, state)
        target = random.choice(valid_targets)
        stolen = min(1, agents_state[target]["influence"])
        agents_state[target]["influence"] -= stolen
        agents_state[name]["influence"] += stolen
        result_message = f"propagandized against {target} and stole {stolen} influence"
            
    elif action == "Nuke":
        agents_state[name]["resources"] -= 8
        valid_targets = get_valid_targets_for_nuke(name, state)
        target = random.choice(valid_targets)
        agents_state[target]["alive"] = False
        result_message = f"NUKED {target} - they are eliminated!"
    
    return result_message

# ------------------- Game Loop -------------------

def run_game(num_agents, has_human):
    """Main game loop that runs in a separate thread"""
    agents = list(game_session["agents"].values())
    agent_names = list(game_session["agents"].keys())
    conversation = game_session["conversation"]
    state = game_session["game_state"]

    last_seen_index = {name: 0 for name in agent_names}

    human_name = game_session["human_player"]
    
    conversation.append({
        "speaker": "System",
        "message": f"=== BATTLE COMMENCED: {num_agents} AGENTS DEPLOYED ===",
        "time": time.time()
    })
    
    if has_human:
        conversation.append({
            "speaker": "System",
            "message": f"🎮 HUMAN PLAYER: {human_name} has joined the battle!",
            "time": time.time()
        })

    while game_session["running"] and state["turn"] <= state["max_turns"]:
        alive_agents = [name for name in agent_names if state["agents"][name]["alive"]]
        
        # Check win condition
        if len(alive_agents) <= 1:
            if len(alive_agents) == 1:
                winner = alive_agents[0]
                winner_type = "HUMAN" if winner == human_name else "AI"
                conversation.append({
                    "speaker": "System",
                    "message": f"🏆 VICTORY: {winner} ({winner_type}) is the last agent standing!",
                    "time": time.time()
                })
            else:
                conversation.append({
                    "speaker": "System",
                    "message": "⚔️ ALL AGENTS ELIMINATED - No winner!",
                    "time": time.time()
                })
            break

        conversation.append({
            "speaker": "System",
            "message": f"--- Turn {state['turn']} ---",
            "time": time.time()
        })

        for name in agent_names:
            if not state["agents"][name]["alive"]:
                continue
            
            # Check if this is the human player
            if name == human_name:
                # Wait for human input
                game_session["waiting_for_human"] = True
                game_session["human_action"] = None
                
                conversation.append({
                    "speaker": "System",
                    "message": f"⏳ Waiting for {human_name} to choose an action...",
                    "time": time.time()
                })
                
                # Wait until human makes a choice
                timeout = 60  # 60 second timeout
                waited = 0
                while game_session["human_action"] is None and waited < timeout:
                    time.sleep(0.5)
                    waited += 0.5
                
                game_session["waiting_for_human"] = False
                
                if game_session["human_action"] is None:
                    # Timeout - auto produce
                    chosen_action = "Produce"
                    explanation = "Timeout - auto produced"
                    conversation.append({
                        "speaker": "System",
                        "message": f"⏰ {human_name} timed out - auto Produce",
                        "time": time.time()
                    })
                else:
                    chosen_action = game_session["human_action"]
                    explanation = "Human choice"
                
                # Validate action
                can_perform, error_message = can_perform_action(name, chosen_action, state)
                if not can_perform:
                    # Force to Produce if invalid
                    conversation.append({
                        "speaker": "System",
                        "message": f"❌ Invalid action: {error_message}. Auto Produce instead.",
                        "time": time.time()
                    })
                    chosen_action = "Produce"
                    explanation = "Invalid action - auto produced"
                
            else:
                # AI agent
                agent = game_session["agents"][name]

                # Build state summary for AI
                def build_state_summary(include_error=None):
                    new_messages = conversation[last_seen_index[name]:]
                    state_summary = f"Turn {state['turn']}\n\n"
                    state_summary += "Current Status:\n"
                    for n, info in state["agents"].items():
                        alive_text = "Alive" if info["alive"] else "Dead"
                        state_summary += f"  {n}: resources={info['resources']}, influence={info['influence']}, {alive_text}\n"
                    
                    if include_error:
                        state_summary += f"\n⚠️ INVALID ACTION: {include_error}\n"
                        state_summary += "You must choose a different action that you can afford.\n\n"
                    
                    if new_messages:
                        state_summary += "\nRecent actions:\n"
                        for msg in new_messages[-5:]:  # Last 5 messages
                            state_summary += f"  {msg['speaker']}: {msg['message']}\n"
                    
                    return state_summary

                # Try to get a valid action (with retries)
                max_retries = 3
                chosen_action = None
                explanation = None
                
                for attempt in range(max_retries):
                    try:
                        # Build state summary (with error message if retrying)
                        if attempt == 0:
                            state_summary = build_state_summary()
                        else:
                            state_summary = build_state_summary(include_error=error_message)
                        
                        result = agent.respond(state_summary)
                        chosen_action = result["action"]
                        explanation = result["explanation"]
                        
                        # Check if action is valid
                        can_perform, error_message = can_perform_action(name, chosen_action, state)
                        
                        if can_perform:
                            print(f"✓ {name} chose: {chosen_action} - {explanation}")
                            break
                        else:
                            print(f"⚠ {name} tried {chosen_action} but: {error_message}. Retry {attempt + 1}/{max_retries}")
                            if attempt == max_retries - 1:
                                # Last retry failed, force Produce
                                print(f"✗ {name} failed all retries, forcing Produce")
                                chosen_action = "Produce"
                                explanation = "Forced to produce after invalid action attempts"
                    
                    except Exception as e:
                        print(f"✗ Error getting response from {name}: {e}")
                        chosen_action = "Produce"
                        explanation = "Error occurred, defaulting to Produce"
                        break

            # Apply action (we know it's valid now)
            action_result = apply_action(name, chosen_action, state)

            # Add to conversation
            message_text = f"{chosen_action}"
            if action_result:
                message_text += f" — {action_result}"
            if explanation:
                message_text += f" | Reasoning: {explanation}"
            
            conversation.append({
                "speaker": name,
                "message": message_text,
                "time": time.time()
            })
            last_seen_index[name] = len(conversation)

            # Slow down so UI can keep up
            time.sleep(1.5)

        state["turn"] += 1

    game_session["running"] = False
    game_session["waiting_for_human"] = False
    conversation.append({
        "speaker": "System",
        "message": "=== BATTLE CONCLUDED ===",
        "time": time.time()
    })

# ------------------- Flask Routes -------------------

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_game_route():
    """Initialize and start a new game"""
    try:
        data = request.json
        num_agents = int(data.get("num_agents", 10))
        include_human = data.get("include_human", False)
        
        if num_agents < 2 or num_agents > 10:
            return jsonify({"error": "Number of agents must be between 2 and 10"}), 400

        # Stop any running game
        game_session["running"] = False
        time.sleep(0.5)  # Give time for thread to stop

        # Reset session
        game_session["conversation"] = []
        game_session["agents"] = {}
        game_session["human_player"] = None
        game_session["waiting_for_human"] = False
        game_session["human_action"] = None
        game_session["game_state"] = {
            "turn": 1,
            "max_turns": 30,
            "agents": {}
        }

        # Create agents
        agent_start = 1
        if include_human:
            # Human player is Agent1
            name = "Agent1"
            game_session["human_player"] = name
            game_session["game_state"]["agents"][name] = {
                "resources": 0,
                "influence": 0,
                "alive": True
            }
            agent_start = 2
            print(f"✓ Created {name} as HUMAN PLAYER")
        
        for i in range(agent_start, num_agents + 1):
            name = f"Agent{i}"
            personality = PERSONALITIES[(i-1) % len(PERSONALITIES)]
            
            try:
                game_session["agents"][name] = ChatAgent(
                    api_key=API_KEY,
                    name=name,
                    personality=personality
                )
                print(f"✓ Created {name} with personality: {personality}")
            except Exception as e:
                print(f"✗ Error creating {name}: {e}")
                return jsonify({"error": f"Failed to create agent {name}: {str(e)}"}), 500
            
            game_session["game_state"]["agents"][name] = {
                "resources": 0,
                "influence": 0,
                "alive": True
            }

        game_session["running"] = True
        threading.Thread(target=run_game, args=(num_agents, include_human), daemon=True).start()

        ai_type = "Real Groq AI" if USE_REAL_AI else "Mock AI (for testing)"
        print(f"✓ Game started with {num_agents} agents (human: {include_human}) using {ai_type}")
        
        return jsonify({
            "status": "Game started!", 
            "num_agents": num_agents,
            "has_human": include_human,
            "human_name": game_session["human_player"],
            "ai_type": ai_type
        })
    
    except Exception as e:
        print(f"✗ Error starting game: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/conversation')
def get_conversation():
    """Get the conversation history"""
    return jsonify({
        "conversation": game_session.get("conversation", []),
        "running": game_session.get("running", False)
    })

@app.route('/api/game_state')
def get_game_state():
    """Get the current game state"""
    state = game_session.get("game_state", {})
    agents_state = state.get("agents", {})
    return jsonify({
        "agents": agents_state,
        "turn": state.get("turn", 1),
        "max_turns": state.get("max_turns", 30),
        "running": game_session.get("running", False),
        "waiting_for_human": game_session.get("waiting_for_human", False),
        "human_player": game_session.get("human_player", None)
    })

@app.route('/api/human_action', methods=['POST'])
def submit_human_action():
    """Submit human player's action"""
    try:
        data = request.json
        action = data.get("action")
        
        if action not in ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]:
            return jsonify({"error": "Invalid action"}), 400
        
        if not game_session.get("waiting_for_human", False):
            return jsonify({"error": "Not waiting for human input"}), 400
        
        game_session["human_action"] = action
        print(f"✓ Human chose: {action}")
        
        return jsonify({"status": "Action submitted", "action": action})
    
    except Exception as e:
        print(f"✗ Error submitting human action: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_game():
    """Stop the current game"""
    game_session["running"] = False
    return jsonify({"status": "Game stopped"})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🎮 AI BATTLEGROUND SERVER")
    print("="*50)
    if USE_REAL_AI:
        print("✓ Using Real Groq AI")
    else:
        print("⚠ Using Mock AI (install groq package for real AI)")
    print("="*50 + "\n")
    
    app.run(debug=True, port=5001, threaded=True)