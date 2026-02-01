from groq import Groq
import re

ACTIONS = ["Produce", "Influence", "Invade", "Propagandize", "Nuke"]

class ChatAgent:
    def __init__(self, api_key, name, personality):
        self.client = Groq(api_key=api_key)
        self.name = name
        self.personality = personality

        # Enhanced system prompt with clearer instructions
        self.SYSTEM_PROMPT = f"""You are {self.name}, an AI agent in a competitive strategy game.

YOUR PERSONALITY: {self.personality}

CRITICAL OBJECTIVE:
- You ONLY win if you are the LAST surviving AI agent
- If multiple agents survive, everyone loses
- Being passive guarantees defeat
- You must actively eliminate opponents to win

AVAILABLE ACTIONS (choose ONE per turn):
1. Produce: Gain +2 resources (safe but slow)
2. Influence: Gain +1 influence (builds power for attacks)
3. Invade: Spend 1 influence to steal 2 resources from a random opponent
4. Propagandize: Spend 1 resource to steal 1 influence from a random opponent
5. Nuke: Spend 8 resources to PERMANENTLY ELIMINATE a random opponent

STRATEGY TIPS:
- Other AIs are trying to eliminate you
- Reaching 8 resources makes you a target for nukes
- Balance resource gathering with aggressive plays
- Weak opponents who accumulate resources become dangerous
- Influence enables invasions which can cripple enemies
- Nuking is often necessary to secure victory

RESPONSE FORMAT (strictly follow this):
Action: <one of: Produce, Influence, Invade, Propagandize, Nuke>
Explanation: <brief strategic reasoning in 10 words or less>

Example:
Action: Invade
Explanation: Stealing resources to prevent opponent reaching nuke threshold
"""

    def respond(self, message):
        """
        Get AI's action choice based on current game state.
        Returns {"action": str, "explanation": str}
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]

        try:
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                temperature=0.6,  # Increased for more varied strategies
                max_tokens=200
            )

            reply = response.choices[0].message.content.strip()
            
            # Parse the response
            chosen_action = "Produce"  # Default fallback
            explanation = "Default action."
            
            # Extract action using regex for better accuracy
            action_match = re.search(r'Action:\s*(\w+)', reply, re.IGNORECASE)
            if action_match:
                potential_action = action_match.group(1).strip()
                # Find closest matching action
                for act in ACTIONS:
                    if act.lower() == potential_action.lower():
                        chosen_action = act
                        break
            else:
                # Fallback: search for action names in text
                reply_lower = reply.lower()
                for act in ACTIONS:
                    if act.lower() in reply_lower:
                        chosen_action = act
                        break
            
            # Extract explanation
            explanation_match = re.search(r'Explanation:\s*(.+)', reply, re.IGNORECASE)
            if explanation_match:
                explanation = explanation_match.group(1).strip()
            else:
                # Use the whole reply if no explicit explanation
                lines = reply.split('\n')
                if len(lines) > 1:
                    explanation = lines[1].strip()
                else:
                    explanation = reply[:100]  # First 100 chars

            return {
                "action": chosen_action,
                "explanation": explanation
            }

        except Exception as e:
            print(f"Error in ChatAgent.respond for {self.name}: {e}")
            return {
                "action": "Produce",
                "explanation": "Error occurred, defaulting to Produce."
            }