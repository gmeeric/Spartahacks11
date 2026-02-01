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

        # Compact system prompt - two separate in-character statements
        self.SYSTEM_PROMPT = f"""You are {self.name}. {self.personality}

WIN: Be alive when alive_agents ≤ rocket_seats. Seats unlock every 10 PROJECT (max 8).

ACTIONS:
- Produce: +2 resources
- Influence: +1 influence
- Invade (1 influence): steal 2 resources
- Propagandize (1 resource): steal 1 influence
- Nuke (8 resources): eliminate target

Each turn: action + contribute 0+ to PROJECT. Top contributor = LEADER (+1 influence).

IMPORTANT: Give TWO separate in-character statements (15-25 words each):
1. "action_reasoning" - why you chose this action
2. "contribution_reasoning" - why you're contributing this amount

Examples:
Cowboy action: "Well partner, I reckon I need resources first!"
Cowboy contribution: "Ain't sharin' nothin' yet - a cowboy looks out for himself!"

Pirate action: "Arr, time to plunder some treasure, matey!"
Pirate contribution: "Not givin' up me doubloons - pirates keep their gold!"

Robot action: "EXECUTING RESOURCE PRODUCTION PROTOCOL."
Robot contribution: "ZERO CONTRIBUTION. SELF-PRESERVATION PRIORITY OVERRIDE."

JSON only:
{{"action":"...","target":"null or name","contribution":0-X,"action_reasoning":"...","contribution_reasoning":"..."}}"""

    def respond(self, message):
        """
        Get AI's strategic action AND contribution in one call.
        Returns {"action": str, "target": str, "contribution": int, "explanation": str, "contribution_explanation": str}
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]

        try:
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                temperature=1.2,
                max_tokens=150  # Slightly increased for two statements
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
                action_reasoning = parsed.get("action_reasoning", "Strategic decision")
                contribution_reasoning = parsed.get("contribution_reasoning", "Strategic decision")
                
                # Validate action
                if action not in ACTIONS:
                    action = "Produce"
                
                # Ensure non-negative contribution
                contribution = max(0, contribution)
                
                return {
                    "action": action,
                    "target": target,
                    "contribution": contribution,
                    "explanation": action_reasoning,
                    "contribution_explanation": contribution_reasoning
                }
            
            except (json.JSONDecodeError, ValueError):
                # Fallback parsing
                pass
            
            # Simple fallback
            chosen_action = "Produce"
            chosen_target = None
            contribution = 0
            action_reasoning = "Strategic decision"
            contribution_reasoning = "Strategic decision"
            
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
                "explanation": action_reasoning,
                "contribution_explanation": contribution_reasoning
            }
        
        except Exception as e:
            print(f"✗ Error in ChatAgent.respond for {self.name}: {e}")
            return {
                "action": "Produce",
                "target": None,
                "contribution": 0,
                "explanation": f"Error: {str(e)[:30]}",
                "contribution_explanation": f"Error: {str(e)[:30]}"
            }