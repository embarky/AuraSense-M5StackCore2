# ai_services.py

import json
import google.generativeai as genai

# ==========================================
# 1. Configuration Constants
# ==========================================
AI_CONFIG_FILE = "caa_ai.json"

class SmartSpaceAI:
    def __init__(self):
        """
        Initializes the Gemini AI engine using the local configuration file.
        Safely loads the API key without hardcoding it.
        """
        self.model = None
        try:
            # 💡 Safely read your custom key file
            with open(AI_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                api_key = config.get("gemini_api_key")
            
            if not api_key:
                raise ValueError("API Key not found in config file.")

            # Configure the Gemini client
            genai.configure(api_key=api_key)
            
            # Initialize the gemini-1.5-flash model 
            # (Lightning fast, highly suitable for real-time IoT responses)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            print("✅ [AI Layer] Gemini Assistant is online and ready to think.")
            
        except FileNotFoundError:
            print(f"❌ [AI Layer] Error: '{AI_CONFIG_FILE}' not found. AI features disabled.")
        except Exception as e:
            print(f"❌ [AI Layer] Initialization failed: {e}")

    def generate_health_advice(self, indoor_temp, indoor_hum, eco2, tvoc, outdoor_temp, outdoor_desc):
        """
        Analyzes the real-time environmental context and generates actionable advice.
        """
        if not self.model:
            return "AI Assistant is currently offline. Please check your API configuration."

        # 💡 The Core Brain: Constructing the Prompt for the LLM
        prompt = f"""
        You are a caring "Smart Home Health Butler".
        Please analyze the following real-time indoor and outdoor environmental data:

        [Indoor Environment]
        - Temperature: {indoor_temp}°C
        - Humidity: {indoor_hum}%
        - CO2: {eco2} ppm (Note: >1000 is slightly high, >1500 is severe)
        - TVOC: {tvoc} ppb
        
        [Outdoor Environment]
        - Temperature: {outdoor_temp}°C
        - Weather condition: {outdoor_desc}

        [Your Task]
        Based on this data, provide a short, friendly, and highly actionable health or comfort tip for the user.
        
        [Strict Requirements]
        1. Must be written in English.
        2. The tone should be warm, professional, and like a real human butler.
        3. Must consider the "indoor vs. outdoor difference" (e.g., if indoor CO2 is high but it's freezing outside, suggest cracking a window slightly rather than fully opening it).
        4. Length limit: Keep it under 2 sentences and maximum 40 words. (It needs to fit cleanly on a UI screen).
        5. Do NOT use any Markdown formatting (no bolding, no asterisks). Output pure text only.
        """

        try:
            # Call Gemini for inference
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ [AI Layer] Inference failed: {e}")
            # Fallback response to prevent system crashes during API timeouts
            if eco2 and float(eco2) > 1000:
                return "CO2 levels are a bit high. Consider ventilating the room slightly."
            return "Your environment is stable. Keep up the good work!"

# ==========================================
# Standalone Test Module
# (You can run this file directly to test if your Key works)
# ==========================================
if __name__ == "__main__":
    print("🧪 Testing AI inference capabilities...")
    ai = SmartSpaceAI()
    
    # Simulate extreme conditions (very stuffy inside, quite cold outside)
    test_advice = ai.generate_health_advice(
        indoor_temp=26.5, 
        indoor_hum=65, 
        eco2=1800, 
        tvoc=200, 
        outdoor_temp=5.0, 
        outdoor_desc="light rain"
    )
    print("-" * 40)
    print(f"🤖 AI Butler Advice:\n{test_advice}")
    print("-" * 40)