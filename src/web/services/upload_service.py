import uuid
import os
import shutil
import threading
import logging
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import current_app
from src.web.extensions import socketio
from src.web.utils.helpers import validate_video_mime, parse_time_to_seconds, formatFileSize, get_or_create_session_id
from src.web.services.job_service import ClipJob, active_jobs, process_clip_generation

logger = logging.getLogger(__name__)

# Store upload sessions
upload_sessions = {}

def init_upload_session(filename, filesize, filetype, user_id=None):
    """Initialize chunked upload session"""
    try:
        # Security: Sanitize filename
        filename = secure_filename(filename)
        if not filename:
            raise ValueError('Invalid filename')
        
        # Create upload session
        upload_id = str(uuid.uuid4())
        session_id = get_or_create_session_id()
        
        # Create temp directory for this upload
        upload_temp_dir = os.path.join(current_app.config['TEMP_UPLOAD_FOLDER'], upload_id)
        os.makedirs(upload_temp_dir, exist_ok=True)
        
        # Initialize session
        upload_sessions[upload_id] = {
            'id': upload_id,
            'filename': filename,
            'original_filename': filename,
            'size': filesize,
            'type': filetype,
            'chunks_received': set(),
            'total_chunks': 0,
            'session_id': session_id,
            'user_id': user_id,
            'created_at': datetime.now(),
            'last_activity': datetime.now(),
            'status': 'initialized',
            'temp_dir': upload_temp_dir
        }
        
        logger.info(f"Upload session initialized: {upload_id} for file: {filename} ({formatFileSize(filesize)})")
        
        return {
            'upload_id': upload_id,
            'chunk_size': current_app.config['CHUNK_SIZE'],
            'status': 'ready'
        }
        
    except Exception as e:
        logger.error(f"Upload init error: {str(e)}")
        raise

def handle_chunk_upload(chunk, upload_id, chunk_number, total_chunks, start_time=None, end_time=None):
    """Handle individual chunk upload"""
    if upload_id not in upload_sessions:
        raise ValueError('Invalid or expired upload session')
    
    session = upload_sessions[upload_id]
    
    # Check session timeout (2 hours)
    if datetime.now() - session['created_at'] > timedelta(hours=2):
        # Clean up
        if os.path.exists(session['temp_dir']):
            shutil.rmtree(session['temp_dir'])
        del upload_sessions[upload_id]
        raise ValueError('Upload session expired')
    
    # Update session
    session['last_activity'] = datetime.now()
    session['total_chunks'] = total_chunks
    
    # Store time parameters if provided
    if start_time and 'start_time' not in session:
        session['start_time'] = start_time
    if end_time and 'end_time' not in session:
        session['end_time'] = end_time
    
    # Save chunk
    chunk_path = os.path.join(session['temp_dir'], f'chunk_{chunk_number:06d}')
    chunk.save(chunk_path)
    
    # Track received chunks
    session['chunks_received'].add(chunk_number)
    chunks_received = len(session['chunks_received'])
    progress = int((chunks_received / total_chunks) * 100)
    
    # Calculate upload speed and ETA
    elapsed = (datetime.now() - session['created_at']).total_seconds()
    if elapsed > 0 and chunks_received > 0:
        chunks_per_second = chunks_received / elapsed
        remaining_chunks = total_chunks - chunks_received
        eta_seconds = remaining_chunks / chunks_per_second if chunks_per_second > 0 else 0
        
        if eta_seconds < 60:
            eta_text = f"{int(eta_seconds)}s"
        else:
            eta_text = f"{int(eta_seconds / 60)}m"
        
        message = f'Uploading... {progress}% (ETA: {eta_text})'
    else:
        message = f'Uploading... {progress}%'
    
    # Emit progress update via SocketIO
    socketio.emit('upload_progress', {
        'upload_id': upload_id,
        'status': 'uploading',
        'progress': progress,
        'message': message,
        'chunks_received': chunks_received,
        'total_chunks': total_chunks
    }, room=upload_id)
    
    # Check if all chunks received
    if chunks_received == total_chunks:
        # Start combining chunks
        session['status'] = 'combining'
        socketio.emit('upload_progress', {
            'upload_id': upload_id,
            'status': 'processing',
            'progress': 95,
            'message': 'Combining chunks...'
        }, room=upload_id)
        
        # Combine in background to not block response
        # We need to pass app_context to the thread
        app = current_app._get_current_object()
        threading.Thread(
            target=combine_and_process_upload,
            args=(upload_id, app)
        ).start()
    
    return {
        'status': 'success',
        'progress': progress,
        'chunks_received': chunks_received
    }

def combine_and_process_upload(upload_id, app):
    """Combine chunks and start processing"""
    with app.app_context():
        try:
            session = upload_sessions.get(upload_id)
            if not session:
                return
            
            # Generate final filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_filename = secure_filename(session['filename'])
            final_filename = f"upload_{timestamp}_{safe_filename}"
            final_path = os.path.join(app.config['UPLOAD_FOLDER'], final_filename)
            
            # Combine chunks
            with open(final_path, 'wb') as outfile:
                for i in range(session['total_chunks']):
                    chunk_path = os.path.join(session['temp_dir'], f'chunk_{i:06d}')
                    if os.path.exists(chunk_path):
                        with open(chunk_path, 'rb') as infile:
                            # Read in 1MB blocks for memory efficiency
                            while True:
                                data = infile.read(1024 * 1024)
                                if not data:
                                    break
                                outfile.write(data)
            
            # Validate the video file
            socketio.emit('upload_progress', {
                'upload_id': upload_id,
                'status': 'processing',
                'progress': 98,
                'message': 'Validating video...'
            }, room=upload_id)
            
            # Security: Validate MIME type
            if not validate_video_mime(final_path):
                os.remove(final_path)
                raise ValueError("Invalid video file")
            
            # Validate with ffprobe
            try:
                import ffmpeg
                probe = ffmpeg.probe(final_path)
                video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
                if not video_streams:
                    os.remove(final_path)
                    raise ValueError("No video stream found")
                
                duration = float(probe['format']['duration'])
                if duration < 1:
                    os.remove(final_path)
                    raise ValueError("Video too short")
                    
            except ffmpeg.Error as e:
                os.remove(final_path)
                raise ValueError(f"Invalid video format: {str(e)}")
            
            # Clean up temp chunks
            shutil.rmtree(session['temp_dir'])
            
            # Create job for processing
            video_url = f"local://{final_filename}"
            job = ClipJob(
                upload_id,
                session.get('user_id'),
                session['session_id'],
                video_url,
                30,  # Default duration
                parse_time_to_seconds(session.get('start_time')),
                parse_time_to_seconds(session.get('end_time'))
            )
            active_jobs[upload_id] = job
            
            # Update progress
            socketio.emit('upload_progress', {
                'upload_id': upload_id,
                'status': 'processing',
                'progress': 100,
                'message': 'Upload complete! Processing video...'
            }, room=upload_id)
            
            # Clean up session
            del upload_sessions[upload_id]
            
            # Start processing
            # Pass app context to the thread if needed, but process_clip_generation handles it if passed?
            # Actually process_clip_generation in job_service doesn't take app context arg yet, I should add it or handle it there.
            # I added app_context support to process_clip_generation in job_service.py
            
            # We are already in a thread with app context here.
            # process_clip_generation starts a new thread? No, in app.py it was started as a thread.
            # Here we are already in a background thread (combine_and_process_upload).
            # So we can just call process_clip_generation directly?
            # But process_clip_generation in job_service is designed to be run in a thread?
            # In app.py: thread = threading.Thread(target=process_clip_generation, args=(job_id,))
            
            # If I call it directly, it will run in this thread. That's fine.
            process_clip_generation(upload_id)
            
        except Exception as e:
            logger.error(f"Combine and process error: {str(e)}")
            
            # Clean up on error
            if upload_id in upload_sessions:
                session = upload_sessions[upload_id]
                if os.path.exists(session['temp_dir']):
                    shutil.rmtree(session['temp_dir'])
                del upload_sessions[upload_id]
            
            # Notify error
            socketio.emit('upload_progress', {
                'upload_id': upload_id,
                'status': 'error',
                'progress': 0,
                'message': f'Processing failed: {str(e)}'
            }, room=upload_id)
