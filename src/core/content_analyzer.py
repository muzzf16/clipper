import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class ViralContentAnalyzer:
    def __init__(self, api_key=None, system_instruction=None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            print("⚠️ Warning: GEMINI_API_KEY not found. AI features will be disabled.")
            self.model = None
        else:
            genai.configure(api_key=self.api_key)
            model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
            print(f"🤖 Using Gemini model: {model_name}")
            
            # Default system instruction if none provided
            if system_instruction is None:
                system_instruction = """You are a world-class viral content expert and video editor. Your goal is to identify the most engaging, shareable, and high-potential moments from video transcripts. You understand pacing, humor, emotional hooks, and what makes content go viral on platforms like TikTok, YouTube Shorts, and Instagram Reels."""
            
            self.model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_instruction
            )

    def analyze_transcript(self, transcript_text, num_clips=1):
        """
        Analyze transcript to find the most viral segments.
        Returns a list of JSON objects with start_time, end_time, and reasoning.
        """
        if not self.model:
            return None

        if num_clips == 1:
            prompt = f"""
            Analyze the following transcript from a video and identify the ONE single most viral, engaging, or funny segment (30-60 seconds long) that would perform best on TikTok/Shorts.

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
        else:
            prompt = f"""
            Analyze the following transcript from a video and identify the top {num_clips} most viral, engaging, or funny segments (each 30-60 seconds long) that would perform best on TikTok/Shorts.
            Ensure the segments do not overlap.

            Transcript:
            {transcript_text[:25000]}  # Increased limit for multi-clip analysis

            Return ONLY a raw JSON list of objects (no markdown formatting) with this structure:
            [
                {{
                    "start_time": <float, start time in seconds>,
                    "end_time": <float, end time in seconds>,
                    "score": <int, 1-10 viral potential>,
                    "reason": "<string, why this is viral>",
                    "title": "<string, a catchy title for this clip>"
                }},
                ...
            ]
            """

        try:
            response = self.model.generate_content(prompt)
            # Clean up response if it contains markdown code blocks
            text = response.text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.endswith('```'):
                text = text[:-3]
            
            result = json.loads(text)
            
            # Normalize result to always be a list
            if isinstance(result, dict):
                return [result]
            return result
            
        except Exception as e:
            print(f"❌ AI Analysis failed: {e}")
            return None
        except Exception as e:
            print(f"❌ AI Analysis failed: {e}")
            return None
