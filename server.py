from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import threading
import time
import random

app = Flask(__name__)
CORS(app)

# Import ChatAgent - no fallback, real AI only
from chat import ChatAgent

API_KEY = "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"

# 10 distinct personalities for AI agents
PERSONALITIES = [
    "aggressive and decisive, strikes first",
    "calculating and patient, waits for perfect moment",
    "paranoid and defensive, fears being nuked",
    "greedy and opportunistic, steals resources aggressively",
    "diplomatic but ruthless, builds then strikes",
    "chaotic and unpredictable, takes big risks",
    "analytical and methodical, optimizes every move",
    "vengeful and reactive, retaliates against attackers",
    "ambitious and competitive, always pushes for dominance",
    "cunning and deceptive, hides true intentions"
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

# ------------------- Helper Functions -------------------

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

def apply_action(name, action, target, state):
    """Apply an agent's action to the game state with specified target"""
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
        
        # Use AI-specified target if valid, otherwise random
        valid_targets = get_valid_targets_for_invade(name, state)
        if target and target in valid_targets:
            chosen_target = target
        elif valid_targets:
            chosen_target = random.choice(valid_targets)
        else:
            return "tried to invade but no valid targets"
        
        stolen = min(2, agents_state[chosen_target]["resources"])
        agents_state[chosen_target]["resources"] -= stolen
        agents_state[name]["resources"] += stolen
        result_message = f"invaded {chosen_target} and stole {stolen} resources"
            
    elif action == "Propagandize":
        agents_state[name]["resources"] -= 1
        
        # Use AI-specified target if valid, otherwise random
        valid_targets = get_valid_targets_for_propagandize(name, state)
        if target and target in valid_targets:
            chosen_target = target
        elif valid_targets:
            chosen_target = random.choice(valid_targets)
        else:
            return "tried to propagandize but no valid targets"
        
        stolen = min(1, agents_state[chosen_target]["influence"])
        agents_state[chosen_target]["influence"] -= stolen
        agents_state[name]["influence"] += stolen
        result_message = f"propagandized against {chosen_target} and stole {stolen} influence"
            
    elif action == "Nuke":
        agents_state[name]["resources"] -= 8
        
        # Use AI-specified target if valid, otherwise random
        valid_targets = get_valid_targets_for_nuke(name, state)
        if target and target in valid_targets:
            chosen_target = target
        elif valid_targets:
            chosen_target = random.choice(valid_targets)
        else:
            return "tried to nuke but no valid targets"
        
        agents_state[chosen_target]["alive"] = False
        result_message = f"NUKED {chosen_target} - they are eliminated!"
    
    return result_message

def build_strategic_prompt(name, state, conversation, last_seen_index, include_error=None):
    """Build a detailed strategic prompt for the AI agent"""
    agents_state = state["agents"]
    
    prompt = f"=== TURN {state['turn']} STRATEGIC ANALYSIS ===\n\n"
    
    # Your current status
    my_stats = agents_state[name]
    prompt += f"YOUR STATUS ({name}):\n"
    prompt += f"  Resources: {my_stats['resources']} (need 8 to nuke)\n"
    prompt += f"  Influence: {my_stats['influence']} (spend 1 to invade)\n"
    prompt += f"  Status: {'ALIVE' if my_stats['alive'] else 'ELIMINATED'}\n\n"
    
    # Show what I've been doing (last 3 actions)
    my_recent_actions = [
        msg for msg in conversation[max(0, len(conversation)-15):]
        if msg.get('speaker') == name and msg.get('speaker') != 'System'
    ]
    if my_recent_actions:
        prompt += f"YOUR RECENT ACTIONS:\n"
        for msg in my_recent_actions[-3:]:
            action_text = msg['message'].split('—')[0].strip()
            prompt += f"  - {action_text}\n"
        prompt += "\n"
    
    # Threat assessment with what they're doing
    prompt += "OPPONENT ANALYSIS (sorted by danger):\n"
    alive_opponents = [
        (n, s) for n, s in agents_state.items() 
        if n != name and s["alive"]
    ]
    # Sort by resources (most dangerous first)
    alive_opponents.sort(key=lambda x: x[1]["resources"], reverse=True)
    
    for opponent_name, stats in alive_opponents:
        threat_level = ""
        if stats["resources"] >= 8:
            threat_level = "🚨 CAN NUKE YOU NOW!"
        elif stats["resources"] >= 6:
            threat_level = "⚠️ HIGH THREAT - Close to nuke"
        elif stats["resources"] >= 4:
            threat_level = "⚡ MEDIUM THREAT"
        else:
            threat_level = "Low threat"
        
        # Show what this opponent has been doing
        opponent_actions = [
            msg for msg in conversation[max(0, len(conversation)-12):]
            if msg.get('speaker') == opponent_name and msg.get('speaker') != 'System'
        ]
        recent_strategy = "Unknown"
        if opponent_actions:
            last_action = opponent_actions[-1]['message'].split('—')[0].strip()
            recent_strategy = last_action
        
        prompt += f"  {opponent_name}: R={stats['resources']}, I={stats['influence']} | {threat_level}\n"
        prompt += f"    Recent: {recent_strategy}\n"
    
    prompt += f"\nAlive opponents: {len(alive_opponents)}\n\n"
    
    # Action availability
    prompt += "YOUR AVAILABLE ACTIONS:\n"
    for action in ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]:
        can_do, reason = can_perform_action(name, action, state)
        status = "✓ AVAILABLE" if can_do else f"✗ {reason}"
        prompt += f"  {action}: {status}\n"
    
    # Error feedback if retrying
    if include_error:
        prompt += f"\n⚠️ PREVIOUS ACTION INVALID: {include_error}\n"
        prompt += "Choose a different action that you can afford.\n"
    
    # Strategic advice based on game state
    prompt += "\n=== STRATEGIC SITUATION ===\n"
    
    # Check if everyone is just building influence
    all_recent_actions = [
        msg['message'] for msg in conversation[-len(alive_opponents)*2:]
        if msg.get('speaker') not in ['System', name]
    ]
    influence_heavy = sum(1 for msg in all_recent_actions if 'Influence' in msg)
    if influence_heavy > len(alive_opponents):
        prompt += "⚠️ WARNING: Everyone is just building influence! This is inefficient.\n"
        prompt += "Consider INVADING to actually steal resources and get ahead!\n"
    
    if my_stats['influence'] >= 2:
        prompt += f"💡 You have {my_stats['influence']} influence - enough to INVADE multiple times!\n"
        prompt += "Invasions steal resources efficiently. Consider attacking!\n"
    
    prompt += "\n=== YOUR DECISION ===\n"
    prompt += "Make a decision that matches YOUR PERSONALITY.\n"
    prompt += "Don't just copy what others are doing - play to your character!\n"
    prompt += "Remember: You must be the LAST agent alive to win!\n"
    
    return prompt

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
                    chosen_target = None
                    explanation = "Timeout - auto produced"
                    conversation.append({
                        "speaker": "System",
                        "message": f"⏰ {human_name} timed out - auto Produce",
                        "time": time.time()
                    })
                else:
                    chosen_action = game_session["human_action"]
                    explanation = "Human choice"
                    chosen_target = None  # Humans don't specify targets (random for now)
                
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
                    chosen_target = None
                
            else:
                # AI agent
                agent = game_session["agents"][name]
                
                # Try to get a valid action (with retries)
                max_retries = 3
                chosen_action = None
                chosen_target = None
                explanation = None
                error_message = None
                
                for attempt in range(max_retries):
                    try:
                        # Build strategic prompt
                        strategic_prompt = build_strategic_prompt(
                            name, state, conversation, last_seen_index[name], 
                            include_error=error_message if attempt > 0 else None
                        )
                        
                        print(f"\n{'='*60}")
                        print(f"Prompting {name} (attempt {attempt+1}/{max_retries}):")
                        print(f"{'='*60}")
                        if attempt == 0:
                            print(strategic_prompt[:500] + "..." if len(strategic_prompt) > 500 else strategic_prompt)
                        
                        # Get AI response
                        result = agent.respond(strategic_prompt)
                        chosen_action = result["action"]
                        chosen_target = result.get("target", None)
                        explanation = result["explanation"]
                        
                        print(f"AI Response: {chosen_action}" + (f" targeting {chosen_target}" if chosen_target else "") + f" - {explanation}")
                        
                        # Check if action is valid
                        can_perform, error_message = can_perform_action(name, chosen_action, state)
                        
                        if can_perform:
                            # Validate target if action requires one
                            if chosen_action in ["Invade", "Propagandize", "Nuke"]:
                                valid_targets = []
                                if chosen_action == "Invade":
                                    valid_targets = get_valid_targets_for_invade(name, state)
                                elif chosen_action == "Propagandize":
                                    valid_targets = get_valid_targets_for_propagandize(name, state)
                                elif chosen_action == "Nuke":
                                    valid_targets = get_valid_targets_for_nuke(name, state)
                                
                                # If target is invalid or missing, it will be random (handled in apply_action)
                                if chosen_target and chosen_target not in valid_targets:
                                    print(f"⚠️ Invalid target {chosen_target}, will choose randomly from {valid_targets}")
                                    chosen_target = None
                            
                            print(f"✓ Valid action accepted")
                            break
                        else:
                            print(f"✗ Invalid: {error_message}")
                            if attempt == max_retries - 1:
                                # Last retry failed, force Produce
                                print(f"✗ {name} failed all retries, forcing Produce")
                                chosen_action = "Produce"
                                chosen_target = None
                                explanation = "Forced to produce after invalid attempts"
                    
                    except Exception as e:
                        print(f"✗ Error getting response from {name}: {e}")
                        chosen_action = "Produce"
                        chosen_target = None
                        explanation = f"Error: {str(e)[:30]}"
                        break

            # Apply action (we know it's valid now)
            action_result = apply_action(name, chosen_action, chosen_target, state)

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

            # Delay between agents to avoid rate limits
            # - 0.5s between AI agents (reduces simultaneous API calls)
            # - 1.5s after last agent before next turn (UI readability)
            if name != agent_names[-1] or not state["agents"][agent_names[-1]]["alive"]:
                time.sleep(0.5)  # Brief pause between agents
            else:
                time.sleep(1.5)  # Longer pause before next turn

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
            # Add a placeholder to agents dict so Agent1 appears in agent_names
            game_session["agents"][name] = None  # Human player, no ChatAgent needed
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
            
            game_session["agents"][name] = ChatAgent(
                api_key=API_KEY,
                name=name,
                personality=personality
            )
            print(f"✓ Created {name} with personality: {personality}")
            
            game_session["game_state"]["agents"][name] = {
                "resources": 0,
                "influence": 0,
                "alive": True
            }

        game_session["running"] = True
        threading.Thread(target=run_game, args=(num_agents, include_human), daemon=True).start()

        print(f"✓ Game started with {num_agents} agents (human: {include_human}) using Real Groq AI")
        
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
    print("✓ Using Real Groq AI")
    print("="*50 + "\n")
    
    app.run(debug=True, port=5001, threaded=True)