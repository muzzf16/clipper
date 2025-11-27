import time
import os
import shutil
import threading
import logging
from database import get_db_connection
from flask import current_app

logger = logging.getLogger(__name__)

def cleanup_expired_clips():
    """Cleanup expired anonymous clips periodically"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute('SELECT cleanup_expired_anonymous_clips()')
        conn.commit()
        logger.info("Cleaned up expired anonymous clips")
    except Exception as e:
        logger.error(f"Error cleaning up clips: {e}")
    finally:
        cur.close()
        conn.close()

def cleanup_old_uploads(app):
    """Clean up old uploaded files"""
    try:
        now = time.time()
        
        # Clean uploaded videos older than 24 hours
        upload_folder = app.config['UPLOAD_FOLDER']
        if os.path.exists(upload_folder):
            for filename in os.listdir(upload_folder):
                filepath = os.path.join(upload_folder, filename)
                if os.path.isfile(filepath):
                    if os.path.getmtime(filepath) < now - 86400:  # 24 hours
                        os.remove(filepath)
                        logger.info(f"Cleaned up old upload: {filename}")
        
        # Clean abandoned temp uploads older than 2 hours
        temp_upload_folder = app.config['TEMP_UPLOAD_FOLDER']
        if os.path.exists(temp_upload_folder):
            for upload_id in os.listdir(temp_upload_folder):
                dirpath = os.path.join(temp_upload_folder, upload_id)
                if os.path.isdir(dirpath):
                    if os.path.getmtime(dirpath) < now - 7200:  # 2 hours
                        shutil.rmtree(dirpath)
                        logger.info(f"Cleaned up abandoned upload: {upload_id}")
                    
    except Exception as e:
        logger.error(f"Upload cleanup error: {str(e)}")

def schedule_cleanup(app):
    """Background thread for cleanup"""
    while True:
        time.sleep(3600)  # Run every hour
        with app.app_context():
            cleanup_expired_clips()
            cleanup_old_uploads(app)

def start_cleanup_thread(app):
    """Start the cleanup thread"""
    cleanup_thread = threading.Thread(target=schedule_cleanup, args=(app,))
    cleanup_thread.daemon = True
    cleanup_thread.start()
