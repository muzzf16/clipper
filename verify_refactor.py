import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    print("Attempting to import create_app...")
    from src.web import create_app
    
    print("Attempting to create app...")
    app = create_app()
    
    print("App created successfully!")
    print(f"Registered blueprints: {list(app.blueprints.keys())}")
    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    
    print("Verification successful!")
    sys.exit(0)
except Exception as e:
    print(f"Verification failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
