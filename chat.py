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

        # Drastically shortened system prompt - all essentials in ~150 tokens
        self.SYSTEM_PROMPT = f"""You are {self.name}. Persona: {self.personality}

WIN: Be alive when alive_agents ≤ rocket_seats. Seats unlock every 10 PROJECT resources (10=1 seat, 20=2, etc, max 8).

ACTIONS (pick one + contribute 0+ resources to PROJECT):
- Produce: +2 resources
- Influence: +1 influence
- Invade (cost 1 influence): steal 2 resources from target
- Propagandize (cost 1 resource): steal 1 influence from target
- Nuke (cost 8 resources): eliminate target permanently

PROJECT: Each turn, all agents contribute resources. Most contributor becomes LEADER (+1 influence). More PROJECT total = more seats.

Respond in character (max 20 words reasoning):
{{"action":"...","target":"... or null","contribution":0-your_resources,"reasoning":"..."}}"""

    def respond(self, message):
        """
        Get AI's strategic action AND contribution in one call.
        Returns {"action": str, "target": str, "contribution": int, "explanation": str}
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]

        # Single attempt - assume AI works correctly
        try:
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                temperature=1.2,
                max_tokens=150  # Reduced from 500 - JSON response is short
            )

            reply = response.choices[0].message.content.strip()
            
            # Try to parse as JSON
            try:
                # Clean up potential markdown code blocks
                if "```json" in reply:
                    reply = reply.split("```json")[1].split("```")[0].strip()
                elif "```" in reply:
                    reply = reply.split("```")[1].split("```")[0].strip()
                
                parsed = json.loads(reply)
                action = parsed.get("action", "Produce")
                target = parsed.get("target", None)
                contribution = int(parsed.get("contribution", 0))
                explanation = parsed.get("reasoning", "Strategic decision")
                
                # Validate action
                if action not in ACTIONS:
                    action = "Produce"
                
                # Ensure non-negative contribution
                contribution = max(0, contribution)
                
                return {
                    "action": action,
                    "target": target,
                    "contribution": contribution,
                    "explanation": explanation
                }
            
            except (json.JSONDecodeError, ValueError):
                # Fallback parsing - extract what we can
                pass
            
            # Simple fallback
            chosen_action = "Produce"
            chosen_target = None
            contribution = 0
            explanation = "Strategic decision"
            
            # Look for action
            for act in ["Nuke", "Invade", "Propagandize", "Influence", "Produce"]:
                if act.lower() in reply.lower():
                    chosen_action = act
                    break
            
            # Look for target
            target_match = re.search(r'(Agent\w+|Cowboy|Pirate|Knight|Scientist|Gangster|ValleyGirl|Shakespeare|General|Robot|Surfer|Human)', reply, re.IGNORECASE)
            if target_match:
                chosen_target = target_match.group(1)
            
            # Look for contribution number
            contrib_match = re.search(r'"contribution"\s*:\s*(\d+)|contribute\s+(\d+)', reply, re.IGNORECASE)
            if contrib_match:
                contribution = int(contrib_match.group(1) or contrib_match.group(2))
            
            return {
                "action": chosen_action,
                "target": chosen_target,
                "contribution": max(0, contribution),
                "explanation": explanation
            }
        
        except Exception as e:
            print(f"✗ Error in ChatAgent.respond for {self.name}: {e}")
            return {
                "action": "Produce",
                "target": None,
                "contribution": 0,
                "explanation": f"Error: {str(e)[:30]}"
            }