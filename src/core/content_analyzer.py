import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class ViralContentAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            print("⚠️ Warning: GEMINI_API_KEY not found. AI features will be disabled.")
            self.model = None
        else:
            genai.configure(api_key=self.api_key)
            model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
            print(f"🤖 Using Gemini model: {model_name}")
            self.model = genai.GenerativeModel(model_name)

    def analyze_transcript(self, transcript_text):
        """
        Analyze transcript to find the most viral segments.
        Returns a JSON object with start_time, end_time, and reasoning.
        """
        if not self.model:
            return None

        prompt = f"""
        You are a viral content expert. Analyze the following transcript from a video and identify the ONE single most viral, engaging, or funny segment (30-60 seconds long) that would perform best on TikTok/Shorts.

        Transcript:
        {transcript_text[:15000]}  # Limit to first ~15k chars to fit context window if needed

        Return ONLY a raw JSON object (no markdown formatting) with this structure:
        {{
            "start_time": <float, start time in seconds>,
            "end_time": <float, end time in seconds>,
            "score": <int, 1-10 viral potential>,
            "reason": "<string, why this is viral>",
            "title": "<string, a catchy title for this clip>"
        }}
        """

        try:
            response = self.model.generate_content(prompt)
            # Clean up response if it contains markdown code blocks
            text = response.text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.endswith('```'):
                text = text[:-3]
            
            return json.loads(text)
        except Exception as e:
            print(f"❌ AI Analysis failed: {e}")
            return None
