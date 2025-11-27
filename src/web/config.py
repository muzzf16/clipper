import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'viral_clipper_secret_key_2025')
    PERMANENT_SESSION_LIFETIME = 604800  # 7 days in seconds
    
    # File upload configuration
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
    UPLOAD_FOLDER = 'uploads'
    TEMP_UPLOAD_FOLDER = 'temp_uploads'
    ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks
    
    # Database configuration - MongoDB
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/clippy')
