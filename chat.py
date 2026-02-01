from groq import Groq
import re
import json
import time

ACTIONS = ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]

class ChatAgent:
    def __init__(self, api_key, name, personality):
        self.client = Groq(api_key=api_key)
        self.name = name
        self.personality = personality

        # Enhanced system prompt with strategic guidance
        self.SYSTEM_PROMPT = f"""You are {self.name}, a highly strategic AI agent in a competitive survival game.

PERSONA & CHARACTER: {self.personality}
CRITICAL: You must speak and reason ENTIRELY in character! Use vocabulary, phrases, and tone that match your persona.

CRITICAL WIN CONDITION - THE ROCKET ESCAPE:
- There is a ROCKET that can only fit a LIMITED number of seats
- The number of seats depends on how much the PROJECT has accumulated (shared pool of resources)
- You WIN if you are ALIVE when the number of alive agents <= available seats
- This means you DON'T need to be the last one alive - multiple agents can win!
- BUT seats are limited (max = starting agents - 1), so you still need to eliminate some opponents
- Strategy: Balance contributing to increase seats vs eliminating opponents to reduce competition

GAME MECHANICS:
1. Produce: +2 resources (safe accumulation)
2. Influence: +1 influence (needed for invasions)
3. Invade: Cost 1 influence → Steal 2 resources from chosen opponent with resources
4. Propagandize: Cost 1 resource → Steal 1 influence from chosen opponent with influence
5. Nuke: Cost 8 resources → PERMANENTLY ELIMINATE chosen opponent

THE PROJECT (Shared Resource Pool):
- All agents can contribute resources to THE PROJECT each turn
- Total project resources determine how many ROCKET SEATS are available
- More resources = more seats = easier for everyone to win
- The agent who contributes MOST each round becomes LEADER (+1 influence as a bonus)
- This creates a dilemma: help everyone by contributing, or save resources for attacks?

SEAT THRESHOLDS (How contributions unlock seats):
- 0-9 project resources: 0 seats (everyone dies)
- 10-19 resources: 1 seat
- 20-29 resources: 2 seats
- 30-39 resources: 3 seats
- 40-49 resources: 4 seats
- 50-59 resources: 5 seats
- 60-69 resources: 6 seats
- 70-79 resources: 7 seats
- 80+ resources: 8 seats (capped at starting agents - 1)

CONTRIBUTION STRATEGY:
- If alive agents > current seats: Either contribute to add seats OR eliminate opponents
- If alive agents <= seats: STOP contributing! You can already win, just survive!
- Contributing helps EVERYONE (including enemies), so only do it when it helps you more
- Example: 5 alive, 3 seats → Need 2 more seats OR 2 eliminations. Which is easier?

ROLEPLAYING GUIDELINES - EXTREMELY IMPORTANT:
Your "reasoning" field MUST be written completely in character!

Examples of persona-appropriate reasoning:
- Cowboy: "Reckon it's high noon for Agent3, partner"
- Pirate: "Aye, time to plunder Agent2's treasure chest!"
- Knight: "Honor demands I vanquish the greatest foe!"
- Scientist: "Hypothesis: eliminating Agent5 maximizes survival probability"
- Gangster: "Gonna whack Agent3, see? He's gettin' too big for his britches"
- Valley Girl: "Like, Agent2 is totally being extra with those resources"
- Shakespeare: "To nuke or not to nuke? Agent4 must perish!"
- Robot: "CALCULATING... TARGET: AGENT3. INITIATING ELIMINATION PROTOCOL"

STAY IN CHARACTER - Your reasoning should sound NOTHING like a generic AI!

STRATEGIC PRINCIPLES (adapt to your persona):
- Attack when it matches your character
- Build resources in a way your persona would
- Target opponents your character would dislike
- Express strategy in your unique voice
- Consider the SEATS - do you need to eliminate more, or can you cooperate?

TARGET SELECTION:
- When using Invade/Propagandize/Nuke, you MUST specify a target
- Choose targets strategically based on threat level
- Target high-resource opponents before they nuke you
- Consider who attacked you (revenge)
- Think about the seat count - eliminate threats, not random opponents

DECISION FRAMEWORK:
1. Check the seats situation: alive agents vs available seats
2. If alive > seats: Need to eliminate opponents OR increase project total
3. If alive <= seats: Focus on survival, avoid being nuked
4. Can I nuke someone NOW? (I have 8+ resources) → Target biggest threat!
5. Can I invade to steal resources? (I have influence) → Target richest opponent!
6. Is someone close to nuking ME? (they have 6+ resources) → Invade them!

RESPONSE FORMAT - You must respond with valid JSON:
{{
    "action": "one of: Produce, Influence, Invade, Propagandize, Nuke",
    "target": "agent name (only needed for Invade/Propagandize/Nuke, otherwise null)",
    "reasoning": "MUST be in character! Use your persona's voice, vocabulary, and style (max 25 words)"
}}

Example responses showing CHARACTER:
{{"action": "Invade", "target": "Agent3", "reasoning": "This here varmint's got too many resources, time to rustle 'em!"}}
{{"action": "Nuke", "target": "Agent5", "reasoning": "Arr! Send that scallywag to Davy Jones' locker!"}}
{{"action": "Produce", "target": null, "reasoning": "A knight must prepare his armory before the great battle!"}}
"""

        # Project contribution prompt
        self.CONTRIBUTION_PROMPT = f"""You are {self.name}, deciding how much to contribute to THE PROJECT.

PERSONA & CHARACTER: {self.personality}
CRITICAL: Stay in character when making your decision!

THE PROJECT & ROCKET SEATS:
- A shared pool where all agents can contribute resources
- Total contributions determine how many ROCKET SEATS are available
- More seats = more agents can escape and win together
- The agent who contributes MOST this round becomes the LEADER (+1 influence bonus)
- This is a strategic decision - balance investing vs keeping resources for nukes/actions

WIN CONDITION:
- You win if you're ALIVE when alive agents <= available seats
- So contributing helps EVERYONE (including you), but costs your attack resources
- Consider: Are there too many opponents for current seats? Should you save resources to nuke someone?
- Or are seats close to enough? Should you contribute to help everyone escape?

SEAT THRESHOLDS:
Every 10 project resources typically unlocks 1 more seat:
- 10 resources = 1 seat
- 20 resources = 2 seats
- 30 resources = 3 seats
... up to 80+ resources = 8 seats (capped)

CONTRIBUTION DECISION:
- You can contribute 0 or more resources (up to what you have)
- Contributing more = better chance to be leader (+1 influence is valuable!)
- But you need 8 resources to nuke opponents
- Think about seat math: Do we need more seats or fewer opponents?

IMPORTANT STRATEGIC GUIDANCE:
- If you're ALREADY in winning position (alive <= seats): DON'T contribute! Save resources!
- If you need more seats AND it's cheaper than nuking: Contribute!
- If becoming leader helps you survive: Small contribution (1-3) might be worth it
- If you're close to 8 resources for a nuke: DON'T contribute, get that nuke!

RESPONSE FORMAT - You must respond with valid JSON:
{{
    "contribution": number (0 to your current resources),
    "reasoning": "MUST be in character! Explain your contribution decision (max 25 words)"
}}

Example responses:
{{"contribution": 5, "reasoning": "This cowboy's gonna invest in the future, partner!"}}
{{"contribution": 0, "reasoning": "Arr! I be keepin' me treasure for more important plunder!"}}
{{"contribution": 3, "reasoning": "A knight invests wisely in the realm's prosperity!"}}
"""

    def respond(self, message):
        """
        Get AI's strategic action based on game state.
        Returns {"action": str, "explanation": str}
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]

        # Retry logic for rate limits
        max_retries = 5
        base_delay = 1  # Start with 1 second
        
        for retry_attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=1.2,  # Higher temperature for more varied strategies
                    max_tokens=500
                )

                reply = response.choices[0].message.content.strip()
                
                # Try to parse as JSON first
                try:
                    # Clean up potential markdown code blocks
                    if "```json" in reply:
                        reply = reply.split("```json")[1].split("```")[0].strip()
                    elif "```" in reply:
                        reply = reply.split("```")[1].split("```")[0].strip()
                    
                    parsed = json.loads(reply)
                    action = parsed.get("action", "Produce")
                    target = parsed.get("target", None)
                    explanation = parsed.get("reasoning", "Strategic decision")
                    
                    # Validate action
                    if action not in ACTIONS:
                        # Try to find closest match
                        action_lower = action.lower()
                        for valid_action in ACTIONS:
                            if valid_action.lower() in action_lower or action_lower in valid_action.lower():
                                action = valid_action
                                break
                        else:
                            action = "Produce"
                    
                    return {
                        "action": action,
                        "target": target,
                        "explanation": explanation
                    }
                
                except json.JSONDecodeError:
                    # Fallback to regex parsing
                    pass
                
                # Fallback parsing with regex
                chosen_action = "Produce"
                chosen_target = None
                explanation = "Strategic decision"
                
                # Look for action in quotes or after "action:"
                action_patterns = [
                    r'"action"\s*:\s*"(\w+)"',
                    r'Action\s*:\s*(\w+)',
                    r'\*\*(\w+)\*\*',
                ]
                
                for pattern in action_patterns:
                    action_match = re.search(pattern, reply, re.IGNORECASE)
                    if action_match:
                        potential_action = action_match.group(1).strip()
                        for act in ACTIONS:
                            if act.lower() == potential_action.lower():
                                chosen_action = act
                                break
                        if chosen_action != "Produce":
                            break
                
                # If still no match, search for action words in the text
                if chosen_action == "Produce":
                    reply_lower = reply.lower()
                    # Prioritize more aggressive actions
                    for act in ["Nuke", "Invade", "Propagandize", "Influence", "Produce"]:
                        if act.lower() in reply_lower:
                            chosen_action = act
                            break
                
                # Look for target
                target_patterns = [
                    r'"target"\s*:\s*"(Agent\d+)"',
                    r'target[:\s]+(Agent\d+)',
                    r'against\s+(Agent\d+)',
                    r'(Agent\d+)',  # Any mention of an agent
                ]
                
                for pattern in target_patterns:
                    target_match = re.search(pattern, reply, re.IGNORECASE)
                    if target_match:
                        chosen_target = target_match.group(1)
                        break
                
                # Extract reasoning
                reasoning_patterns = [
                    r'"reasoning"\s*:\s*"([^"]+)"',
                    r'Reasoning\s*:\s*(.+?)(?:\n|$)',
                    r'Explanation\s*:\s*(.+?)(?:\n|$)',
                ]
                
                for pattern in reasoning_patterns:
                    reasoning_match = re.search(pattern, reply, re.IGNORECASE)
                    if reasoning_match:
                        explanation = reasoning_match.group(1).strip()[:100]
                        break
                
                return {
                    "action": chosen_action,
                    "target": chosen_target,
                    "explanation": explanation
                }
            
            except Exception as e:
                error_str = str(e)
                
                # Check if it's a rate limit error (429)
                if "429" in error_str or "rate limit" in error_str.lower():
                    if retry_attempt < max_retries - 1:
                        # Calculate exponential backoff delay
                        delay = base_delay * (2 ** retry_attempt)
                        print(f"⚠️ Rate limit hit for {self.name}, waiting {delay}s before retry {retry_attempt + 1}/{max_retries}")
                        time.sleep(delay)
                        continue
                    else:
                        print(f"✗ Rate limit exceeded for {self.name} after {max_retries} retries")
                        return {
                            "action": "Produce",
                            "target": None,
                            "explanation": "Rate limited - defaulting to safe action"
                        }
                else:
                    # Non-rate-limit error
                    print(f"✗ Error in ChatAgent.respond for {self.name}: {e}")
                    return {
                        "action": "Produce",
                        "target": None,
                        "explanation": f"Error: {str(e)[:50]}"
                    }
        
        # Should never reach here, but just in case
        return {
            "action": "Produce",
            "target": None,
            "explanation": "Max retries exceeded"
        }

    def decide_contribution(self, message):
        """
        Get AI's decision on how much to contribute to the project.
        Returns {"contribution": int, "reasoning": str}
        """
        messages = [
            {"role": "system", "content": self.CONTRIBUTION_PROMPT},
            {"role": "user", "content": message}
        ]

        max_retries = 3
        base_delay = 1
        
        for retry_attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=1.0,
                    max_tokens=100
                )

                reply = response.choices[0].message.content.strip()
                
                # Try to parse as JSON
                try:
                    if "```json" in reply:
                        reply = reply.split("```json")[1].split("```")[0].strip()
                    elif "```" in reply:
                        reply = reply.split("```")[1].split("```")[0].strip()
                    
                    parsed = json.loads(reply)
                    contribution = int(parsed.get("contribution", 0))
                    reasoning = parsed.get("reasoning", "Strategic contribution")
                    
                    return {
                        "contribution": max(0, contribution),  # Ensure non-negative
                        "reasoning": reasoning
                    }
                
                except (json.JSONDecodeError, ValueError):
                    # Fallback parsing
                    pass
                
                # Fallback: look for numbers
                contribution = 0
                reasoning = "Strategic contribution"
                
                number_patterns = [
                    r'"contribution"\s*:\s*(\d+)',
                    r'contribute\s+(\d+)',
                    r'(\d+)\s+resources?'
                ]
                
                for pattern in number_patterns:
                    match = re.search(pattern, reply, re.IGNORECASE)
                    if match:
                        contribution = int(match.group(1))
                        break
                
                # Extract reasoning
                reasoning_patterns = [
                    r'"reasoning"\s*:\s*"([^"]+)"',
                    r'because\s+(.+?)(?:\n|$)',
                ]
                
                for pattern in reasoning_patterns:
                    match = re.search(pattern, reply, re.IGNORECASE)
                    if match:
                        reasoning = match.group(1).strip()[:100]
                        break
                
                return {
                    "contribution": max(0, contribution),
                    "reasoning": reasoning
                }
            
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate limit" in error_str.lower():
                    if retry_attempt < max_retries - 1:
                        delay = base_delay * (2 ** retry_attempt)
                        print(f"⚠️ Rate limit hit for {self.name} contribution, waiting {delay}s")
                        time.sleep(delay)
                        continue
                
                print(f"✗ Error in contribution decision for {self.name}: {e}")
                return {
                    "contribution": 0,
                    "reasoning": "Error in decision-making"
                }
        
        return {
            "contribution": 0,
            "reasoning": "Failed to decide"
        }