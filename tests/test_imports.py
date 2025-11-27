import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src.core.content_analyzer import ViralContentAnalyzer
    print("✅ ViralContentAnalyzer imported successfully")
except ImportError as e:
    print(f"❌ Failed to import ViralContentAnalyzer: {e}")

try:
    from src.core.viral_clipper_complete import ViralClipGenerator
    print("✅ ViralClipGenerator imported successfully")
except ImportError as e:
    print(f"❌ Failed to import ViralClipGenerator: {e}")
