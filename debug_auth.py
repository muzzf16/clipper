import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    print(f"CWD: {os.getcwd()}")
    print(f"Sys path: {sys.path}")
    
    import auth
    print("Auth imported successfully")
    print(f"Auth file: {auth.__file__}")
    
    from src.web.routes import auth_routes
    print("Auth routes imported successfully")
    
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
