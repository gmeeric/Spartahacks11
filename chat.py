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

PERSONALITY: {self.personality}
CRITICAL: Let your personality STRONGLY influence your decisions! Don't just build influence - play to your character!

CRITICAL WIN CONDITION:
- You ONLY win if you are the LAST agent alive
- Multiple survivors = everyone loses
- You MUST eliminate all opponents to win

GAME MECHANICS:
1. Produce: +2 resources (safe accumulation)
2. Influence: +1 influence (needed for invasions)
3. Invade: Cost 1 influence → Steal 2 resources from chosen opponent with resources
4. Propagandize: Cost 1 resource → Steal 1 influence from chosen opponent with influence
5. Nuke: Cost 8 resources → PERMANENTLY ELIMINATE chosen opponent

STRATEGIC PRINCIPLES BASED ON YOUR PERSONALITY:
- If AGGRESSIVE: Attack early and often, don't wait
- If PATIENT/CALCULATING: Build up resources, strike when strong
- If PARANOID/DEFENSIVE: Focus on survival, react to threats
- If GREEDY: Steal resources aggressively via invasions
- If CHAOTIC/UNPREDICTABLE: Mix up your strategy, surprise opponents
- If ANALYTICAL: Optimize resource efficiency and timing
- If VENGEFUL: Attack those who attacked you
- If AMBITIOUS: Race to 8 resources quickly to nuke first

IMPORTANT TACTICAL NOTES:
- Everyone just building influence is BORING and gets you nowhere
- Invasions are VERY efficient: spend 1 influence, get 2 resources back
- Once you have 2+ influence, START INVADING to steal resources
- Resources are what let you WIN (via nuking)
- Don't hoard influence forever - USE IT to invade and steal
- Aggressive play often wins - passive players get nuked

TARGET SELECTION:
- When using Invade/Propagandize/Nuke, you MUST specify a target
- Choose targets strategically based on threat level
- Target high-resource opponents before they nuke you
- Target weak opponents to eliminate them
- Consider who attacked you (revenge)

DECISION FRAMEWORK:
1. Can I nuke someone NOW? (I have 8+ resources) → Target biggest threat!
2. Can I invade to steal resources? (I have influence) → Target richest opponent!
3. Is someone close to nuking ME? (they have 6+ resources) → Invade them!
4. Am I falling behind? → Get aggressive with invasions
5. Only produce/influence if you have a specific reason

RESPONSE FORMAT - You must respond with valid JSON:
{{
    "action": "one of: Produce, Influence, Invade, Propagandize, Nuke",
    "target": "agent name (only needed for Invade/Propagandize/Nuke, otherwise null)",
    "reasoning": "brief explanation matching your personality (max 20 words)"
}}

Example responses:
{{"action": "Invade", "target": "Agent3", "reasoning": "Agent3 has 6 resources, stealing before they nuke"}}
{{"action": "Nuke", "target": "Agent5", "reasoning": "Eliminating strongest threat"}}
{{"action": "Produce", "target": null, "reasoning": "Building resources for future nuke"}}
{{"action": "Influence", "target": null, "reasoning": "Need invasion power"}}
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
                    max_tokens=150
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