#!/usr/bin/env python3
"""
🎯 VIRAL CLIPPER WEB APP - MODULAR VERSION 🎯
Flask web application with multi-user OAuth support and multi-page architecture
"""

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

# For local development, allow OAuth over HTTP
import os
if os.getenv('FLASK_ENV') == 'development':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from src.web import create_app, socketio
from src.web.services.cleanup_service import start_cleanup_thread

app = create_app()

if __name__ == '__main__':
    # Ensure required directories exist
    os.makedirs('clips', exist_ok=True)
    os.makedirs('downloads', exist_ok=True)
    
    # Check for GEMINI_API_KEY
    if os.getenv('GEMINI_API_KEY'):
        print("✅ GEMINI_API_KEY found")
    else:
        print("⚠️ GEMINI_API_KEY not found in environment variables")
    
    # Start cleanup thread
    start_cleanup_thread(app)
    
    print("🎯 Starting Modular Viral Clipper Web App...")
    print("🌐 Access at: http://localhost:5000")
    print("📄 Multi-page architecture enabled")
    print("🔓 Anonymous clip generation: ENABLED")
    print("🔐 Authentication: OPTIONAL (required for upload)")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
