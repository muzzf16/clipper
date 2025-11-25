import sys
import os
import traceback

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from src.core.viral_clipper_complete import ViralClipGenerator
    print("✅ Successfully imported ViralClipGenerator")
    
    clipper = ViralClipGenerator()
    print("✅ Successfully initialized ViralClipGenerator")
    
    # Test with a known short video (Rick Roll is reliable for testing)
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    print(f"🚀 Attempting to generate clip from: {test_url}")
    
    import ffmpeg
    
    try:
        result = clipper.generate_viral_clip(
            video_url=test_url,
            start_time=10,
            duration=10
        )
    except ffmpeg.Error as e:
        print(f"❌ FFmpeg Error: {e}")
        if e.stderr:
            print(f"🔴 Stderr: {e.stderr.decode('utf8')}")
        result = None
    except Exception as e:
        print(f"❌ General Exception: {e}")
        traceback.print_exc()
        result = None
    
    if result:
        print("🎉 Success! Result:", result)
    else:
        print("❌ Failed to generate clip (returned None)")

except Exception as e:
    print("\n❌ CRITICAL ERROR:")
    traceback.print_exc()
