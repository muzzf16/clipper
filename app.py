#!/usr/bin/env python3
"""
🎯 VIRAL CLIPPER WEB APP - MULTI-PAGE VERSION 🎯
Flask web application with multi-user OAuth support and multi-page architecture
"""

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

# For local development, allow OAuth over HTTP
import os
if os.getenv('FLASK_ENV') == 'development':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for, g
from flask_socketio import SocketIO, emit
import os
import json
import uuid
import threading
import time
from datetime import datetime, timedelta
# MongoDB is now used instead of PostgreSQL

# Import our modules
from src.core.auto_peak_viral_clipper import AutoPeakViralClipper
from src.captions.caption_fragment_fix import merge_fragmented_captions
from src.captions.ass_caption_update_system_v6 import ASSCaptionUpdateSystemV6 as ASSCaptionUpdateSystem

# Import auth modules
from auth import login_required, get_current_user, OAuthManager, User
from auth.decorators import youtube_service_required, logout_user
from database import init_db, get_db_connection

# TikTok imports
from auth.multi_platform_oauth import multi_platform_oauth
from auth.tiktok.api_client import TikTokAPIClient

# File upload imports
import hashlib
import shutil
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'viral_clipper_secret_key_2025')
app.config['PERMANENT_SESSION_LIFETIME'] = 604800  # 7 days in seconds

# File upload configuration
app.config['MAX_UPLOAD_SIZE'] = 5 * 1024 * 1024 * 1024  # 5GB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['TEMP_UPLOAD_FOLDER'] = 'temp_uploads'
app.config['ALLOWED_EXTENSIONS'] = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
app.config['CHUNK_SIZE'] = 10 * 1024 * 1024  # 10MB chunks

# Database configuration - MongoDB
app.config['MONGODB_URI'] = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/clippy')

# Initialize database
init_db(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize the clipper with ASS captions
clipper = AutoPeakViralClipper()

# Initialize OAuth manager
oauth_manager = OAuthManager()

# Store active jobs (now per user or session)
active_jobs = {}

# Store upload sessions
upload_sessions = {}

import logging
logger = logging.getLogger(__name__)

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMP_UPLOAD_FOLDER'], exist_ok=True)

class ClipJob:
    """Represents a clip generation job"""
    def __init__(self, job_id, user_id, session_id, url, duration, start_time=None, end_time=None):
        self.job_id = job_id
        self.user_id = user_id  # Can be None for anonymous users
        self.session_id = session_id  # Always present
        self.url = url
        self.duration = duration
        self.start_time = start_time
        self.end_time = end_time
        self.status = "starting"
        self.progress = 0
        self.message = "Initializing..."
        self.clip_data = {}  # Initialize as empty dict instead of None
        self.error = None
        self.created_at = datetime.now()
        self.regeneration_status = None
        self.regeneration_progress = 0
        self.regeneration_job_id = None
        self.is_anonymous = user_id is None


def get_or_create_session_id():
    """Get existing session ID or create a new one"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        session.permanent = True
    return session['session_id']


def save_anonymous_clip(job):
    """Save anonymous clip to database"""
    from database import update_one
    from datetime import datetime, timedelta
    
    try:
        # Upsert anonymous clip document
        update_one(
            'anonymous_clips',
            {'job_id': job.job_id},
            {
                '$set': {
                    'session_id': job.session_id,
                    'job_id': job.job_id,
                    'video_url': job.url,
                    'clip_path': job.clip_data.get('path') if job.clip_data else None,
                    'clip_data': job.clip_data,
                    'updated_at': datetime.utcnow(),
                    'expires_at': datetime.utcnow() + timedelta(days=7)
                },
                '$setOnInsert': {
                    'created_at': datetime.utcnow()
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to save anonymous clip: {e}")


def get_anonymous_clips(session_id):
    """Get anonymous clips for a session"""
    from database import find_many
    from datetime import datetime
    
    try:
        clips = find_many(
            'anonymous_clips',
            {
                'session_id': session_id,
                'expires_at': {'$gt': datetime.utcnow()}
            },
            limit=10,
            sort=[('created_at', -1)]
        )
        return clips
    except Exception as e:
        logger.error(f"Failed to get anonymous clips: {e}")
        return []


def convert_anonymous_clips_to_user(session_id, user_id):
    """Convert anonymous clips to user clips when they sign in"""
    from database import update_many
    from datetime import datetime
    
    try:
        result = update_many(
            'anonymous_clips',
            {
                'session_id': session_id,
                'converted_to_user_id': None
            },
            {
                '$set': {
                    'converted_to_user_id': user_id,
                    'converted_at': datetime.utcnow()
                }
            }
        )
        return result
    except Exception as e:
        logger.error(f"Failed to convert anonymous clips: {e}")
        return 0


def update_job_progress(job_id, status, progress, message):
    """Update job progress and emit to frontend"""
    if job_id in active_jobs:
        job = active_jobs[job_id]
        job.status = status
        job.progress = progress
        job.message = message
        
        # Emit to job-specific room
        socketio.emit('progress_update', {
            'job_id': job_id,
            'status': status,
            'progress': progress,
            'message': message
        }, room=job_id)


def process_clip_generation(job_id):
    """Background thread for clip generation"""
    try:
        job = active_jobs[job_id]
        
        update_job_progress(job_id, "processing", 5, "Starting clip generation...")
        
        # Calculate actual start time for processing
        if job.start_time is not None and job.end_time is not None:
            actual_start_time = job.start_time
            actual_duration = job.end_time - job.start_time
            update_job_progress(job_id, "processing", 10, "Using manual time selection...")
        else:
            actual_start_time = None
            actual_duration = job.duration
            update_job_progress(job_id, "processing", 10, "Using auto-detection...")
        
        update_job_progress(job_id, "processing", 20, "Downloading video...")
        
        # Generate the clip
        logger.info(f"Generating clip for job {job_id} with URL: {job.url}, duration: {actual_duration}, start: {actual_start_time}")
        
        clip_data = clipper.generate_viral_clip(
            video_url=job.url,
            duration=actual_duration,
            start_time=actual_start_time
        )
        
        logger.info(f"Clip generation result for job {job_id}: {type(clip_data)}, has data: {bool(clip_data)}")
        
        if clip_data:
            logger.info(f"Clip data keys: {list(clip_data.keys())}")
            job.clip_data = clip_data
            update_job_progress(job_id, "completed", 100, "Clip generated successfully!")
            
            # Extract caption data for editing
            caption_data = extract_caption_data(clip_data)
            job.clip_data['captions'] = caption_data
            logger.info(f"Added {len(caption_data)} captions to clip data")
            
            # Save anonymous clip to database if anonymous
            if job.is_anonymous:
                save_anonymous_clip(job)
            
            socketio.emit('clip_completed', {
                'job_id': job_id,
                'clip_data': job.clip_data,  # Use job.clip_data which includes captions
                'captions': caption_data
            }, room=job_id)
        else:
            job.error = "Clip generation failed"
            update_job_progress(job_id, "error", 0, "Clip generation failed")
            
    except Exception as e:
        job.error = str(e)
        update_job_progress(job_id, "error", 0, f"Error: {str(e)}")


# ==================== PAGE ROUTES ====================

@app.route('/')
def index():
    """Home page - Input form"""
    return render_template('pages/input.html')

@app.route('/process')
def process_page():
    """Processing page - Shows progress"""
    job_id = request.args.get('job_id')
    if not job_id:
        return redirect(url_for('index'))
    return render_template('pages/process.html', job_id=job_id)

@app.route('/edit')
def edit_page():
    """Edit captions page"""
    job_id = request.args.get('job_id')
    if not job_id:
        return redirect(url_for('index'))
    
    # Get job data
    user = get_current_user()
    session_id = get_or_create_session_id()
    
    if job_id not in active_jobs:
        return redirect(url_for('index'))
    
    job = active_jobs[job_id]
    
    # Check authorization
    if job.user_id:
        if not user or job.user_id != user.id:
            return redirect(url_for('index'))
    else:
        if job.session_id != session_id:
            return redirect(url_for('index'))
    
    # Check if job is completed
    if job.status != 'completed':
        # If not completed, redirect back to processing page
        logger.warning(f"Job {job_id} not completed, status: {job.status}")
        return redirect(url_for('process_page', job_id=job_id))
    
    if not job.clip_data:
        logger.error(f"Job {job_id} is completed but has no clip_data")
        # Try to refresh the clip data
        if hasattr(job, 'refresh_clip_data'):
            job.refresh_clip_data()
        
        if not job.clip_data:
            # Still no data, show error
            return render_template('pages/edit.html', 
                                 job_id=job_id, 
                                 clip_data={},
                                 error="Clip data not found. Please try regenerating the clip.")
    
    # Get clip data
    clip_data = job.clip_data
    
    # Log the clip data for debugging
    logger.info(f"Edit page - Job ID: {job_id}, Clip data keys: {list(clip_data.keys()) if clip_data else 'None'}")
    if clip_data:
        logger.info(f"Full clip_data: {json.dumps(clip_data, indent=2)}")
        if 'path' in clip_data:
            logger.info(f"Clip path: {clip_data['path']}")
        if 'captions' in clip_data:
            logger.info(f"Number of captions: {len(clip_data['captions'])}")
    else:
        logger.error(f"No clip data for job {job_id}")
    
    return render_template('pages/edit.html', 
                         job_id=job_id, 
                         clip_data=clip_data)

@app.route('/upload')
@login_required
def upload_page():
    """Upload page - Requires authentication"""
    job_id = request.args.get('job_id')
    if not job_id:
        return redirect(url_for('index'))
    
    # Verify user owns this clip
    user = get_current_user()
    
    if job_id not in active_jobs:
        return redirect(url_for('index'))
    
    job = active_jobs[job_id]
    
    # For anonymous jobs, convert them to user jobs
    if job.is_anonymous:
        job.user_id = user.id
        job.is_anonymous = False
        convert_anonymous_clips_to_user(job.session_id, user.id)
    elif job.user_id != user.id:
        return redirect(url_for('index'))
    
    return render_template('pages/upload.html', job_id=job_id)


# ==================== AUTH ROUTES ====================

@app.route('/api/auth/login')
def auth_login():
    """Initiate OAuth login flow"""
    # Store the current session ID to convert anonymous clips later
    session['pre_auth_session_id'] = get_or_create_session_id()
    
    redirect_uri = url_for('auth_callback', _external=True)
    authorization_url, state = oauth_manager.get_authorization_url(redirect_uri)
    
    # Store state in session for CSRF protection
    session['oauth_state'] = state
    
    return jsonify({
        'authorization_url': authorization_url,
        'status': 'redirect_required'
    })


@app.route('/api/auth/callback')
def auth_callback():
    """Handle OAuth callback"""
    # Verify state
    state = request.args.get('state')
    stored_state = session.pop('oauth_state', None)
    
    if not state or state != stored_state:
        return render_template('auth_error.html', error='Invalid state parameter')
    
    # Handle the callback
    redirect_uri = url_for('auth_callback', _external=True)
    user = oauth_manager.handle_oauth_callback(
        request.url, state, redirect_uri
    )
    
    if user:
        # Convert anonymous clips to user clips
        pre_auth_session_id = session.get('pre_auth_session_id')
        if pre_auth_session_id:
            converted_count = convert_anonymous_clips_to_user(pre_auth_session_id, user.id)
            print(f"Converted {converted_count} anonymous clips to user {user.email}")
        
        # Redirect to home page with success indicator
        return redirect(url_for('index', auth='success'))
    else:
        return render_template('auth_error.html', error='Authentication failed')


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """Logout user"""
    logout_user()
    return jsonify({'status': 'success', 'message': 'Logged out successfully'})


@app.route('/api/auth/status')
def auth_status():
    """Check authentication status"""
    user = get_current_user()
    session_id = get_or_create_session_id()
    
    response_data = {
        'authenticated': user is not None,
        'session_id': session_id
    }
    
    if user:
        response_data['user'] = user.to_dict()
    
    # Check for anonymous clips
    if not user:
        anonymous_clips = get_anonymous_clips(session_id)
        response_data['anonymous_clips_count'] = len(anonymous_clips)
    
    return jsonify(response_data)


# ==================== FILE UPLOAD HELPERS ====================

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_video_mime(file_path):
    """Validate file MIME type for security"""
    try:
        # Simple validation based on file header
        with open(file_path, 'rb') as f:
            header = f.read(12)
            # Check for common video file signatures
            if header[4:8] == b'ftyp':  # MP4, MOV
                return True
            elif header[:4] == b'\x1a\x45\xdf\xa3':  # MKV, WebM
                return True
            elif header[:4] == b'RIFF' and header[8:12] == b'AVI ':  # AVI
                return True
        return False
    except Exception:
        return False

def formatFileSize(size_bytes):
    """Format file size for logging"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

# ==================== API ROUTES ====================

@app.route('/api/generate_clip', methods=['POST'])
def generate_clip():
    """Start clip generation process - NO AUTHENTICATION REQUIRED"""
    user = get_current_user()  # May be None
    session_id = get_or_create_session_id()
    data = request.json
    
    # Validate input
    url = data.get('url', '').strip()
    if not url or 'youtube.com' not in url and 'youtu.be' not in url:
        return jsonify({'error': 'Invalid YouTube URL'}), 400
    
    duration = data.get('duration', 30)
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    
    # Convert MM:SS to seconds if provided
    if start_time:
        start_time = parse_time_to_seconds(start_time)
    if end_time:
        end_time = parse_time_to_seconds(end_time)
    
    # Create job
    job_id = str(uuid.uuid4())
    user_id = user.id if user else None
    job = ClipJob(job_id, user_id, session_id, url, duration, start_time, end_time)
    active_jobs[job_id] = job
    
    # Start background processing
    thread = threading.Thread(target=process_clip_generation, args=(job_id,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'job_id': job_id, 
        'status': 'started',
        'is_anonymous': user_id is None
    })


# ==================== FILE UPLOAD ROUTES ====================

@app.route('/api/init_upload', methods=['POST'])
def init_upload():
    """Initialize chunked upload session"""
    try:
        data = request.json
        filename = data.get('filename', '')
        filesize = data.get('size', 0)
        filetype = data.get('type', '')
        
        # Security: Sanitize filename
        filename = secure_filename(filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Validate file extension
        if not allowed_file(filename):
            return jsonify({'error': 'File type not allowed. Supported: MP4, MOV, AVI, MKV, WebM'}), 400
        
        # Validate file size
        if filesize <= 0 or filesize > app.config['MAX_UPLOAD_SIZE']:
            max_gb = app.config['MAX_UPLOAD_SIZE'] / (1024**3)
            return jsonify({'error': f'Invalid file size. Maximum: {max_gb}GB'}), 400
        
        # Create upload session
        upload_id = str(uuid.uuid4())
        session_id = get_or_create_session_id()
        user = get_current_user()
        
        # Create temp directory for this upload
        upload_temp_dir = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], upload_id)
        os.makedirs(upload_temp_dir, exist_ok=True)
        
        # Initialize session
        upload_sessions[upload_id] = {
            'id': upload_id,
            'filename': filename,
            'original_filename': data.get('filename', ''),  # Keep original for display
            'size': filesize,
            'type': filetype,
            'chunks_received': set(),
            'total_chunks': 0,
            'session_id': session_id,
            'user_id': user.id if user else None,
            'created_at': datetime.now(),
            'last_activity': datetime.now(),
            'status': 'initialized',
            'temp_dir': upload_temp_dir
        }
        
        logger.info(f"Upload session initialized: {upload_id} for file: {filename} ({formatFileSize(filesize)})")
        
        return jsonify({
            'upload_id': upload_id,
            'chunk_size': app.config['CHUNK_SIZE'],
            'status': 'ready'
        })
        
    except Exception as e:
        logger.error(f"Upload init error: {str(e)}")
        return jsonify({'error': 'Failed to initialize upload'}), 500


@app.route('/api/upload_chunk', methods=['POST'])
def upload_chunk():
    """Handle individual chunk upload"""
    try:
        # Get chunk data
        chunk = request.files.get('chunk')
        upload_id = request.form.get('upload_id')
        chunk_number = int(request.form.get('chunk_number', 0))
        total_chunks = int(request.form.get('total_chunks', 1))
        
        # Get optional parameters (sent with first chunk)
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        
        # Validate
        if not chunk or not upload_id:
            return jsonify({'error': 'Missing required data'}), 400
        
        if upload_id not in upload_sessions:
            return jsonify({'error': 'Invalid or expired upload session'}), 400
        
        session = upload_sessions[upload_id]
        
        # Check session timeout (2 hours)
        if datetime.now() - session['created_at'] > timedelta(hours=2):
            # Clean up
            if os.path.exists(session['temp_dir']):
                shutil.rmtree(session['temp_dir'])
            del upload_sessions[upload_id]
            return jsonify({'error': 'Upload session expired'}), 400
        
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
            threading.Thread(
                target=combine_and_process_upload,
                args=(upload_id,)
            ).start()
        
        return jsonify({
            'status': 'success',
            'progress': progress,
            'chunks_received': chunks_received
        })
        
    except Exception as e:
        logger.error(f"Chunk upload error: {str(e)}")
        return jsonify({'error': 'Chunk upload failed'}), 500


def combine_and_process_upload(upload_id):
    """Combine chunks and start processing"""
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
        thread = threading.Thread(target=process_clip_generation, args=(upload_id,))
        thread.daemon = True
        thread.start()
        
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


@app.route('/api/job_status/<job_id>')
def job_status(job_id):
    """Get job status - accessible by session or user"""
    user = get_current_user()
    session_id = get_or_create_session_id()
    
    if job_id not in active_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = active_jobs[job_id]
    
    # Check authorization
    if job.user_id:
        # User job - must match user
        if not user or job.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
    else:
        # Anonymous job - must match session
        if job.session_id != session_id:
            return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify({
        'job_id': job_id,
        'status': job.status,
        'progress': job.progress,
        'message': job.message,
        'clip_data': job.clip_data,
        'error': job.error,
        'is_anonymous': job.is_anonymous
    })


@app.route('/api/user_activity')
@login_required
def user_activity():
    """Get user's recent activity"""
    user = get_current_user()
    
    # Get user's recent clips
    recent_clips = []
    for job_id, job in active_jobs.items():
        if job.user_id == user.id and job.status == 'completed':
            recent_clips.append({
                'job_id': job_id,
                'original_title': job.clip_data.get('original_title', 'Untitled') if job.clip_data else 'Untitled',
                'duration': job.clip_data.get('duration', 30) if job.clip_data else 30,
                'created_at': job.created_at.isoformat()
            })
    
    # Sort by date
    recent_clips.sort(key=lambda x: x['created_at'], reverse=True)
    
    return jsonify({
        'recent_clips': recent_clips[:10]
    })


@app.route('/api/update_captions', methods=['POST'])
def update_captions():
    """Update captions - accessible by session or user"""
    user = get_current_user()
    session_id = get_or_create_session_id()
    data = request.json
    job_id = data.get('job_id')
    captions = data.get('captions', [])
    caption_position = data.get('caption_position', 'bottom')
    caption_position_percent = data.get('caption_position_percent', 80)  # Default 80% from top
    speaker_colors = data.get('speaker_colors', {})
    speaker_settings = data.get('speaker_settings', {})
    end_screen = data.get('end_screen', {})
    
    if job_id not in active_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = active_jobs[job_id]
    
    # Check authorization
    if job.user_id:
        if not user or job.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
    else:
        if job.session_id != session_id:
            return jsonify({'error': 'Unauthorized'}), 403
    
    if not job.clip_data:
        return jsonify({'error': 'No clip data available'}), 400
    
    try:
        # Preprocess captions to fix fragmentation
        avg_text_length = sum(len(c.get('text', '')) for c in captions) / len(captions) if captions else 0
        
        if avg_text_length < 5:
            captions = merge_fragmented_captions(captions)
        
        # Create regeneration job ID
        regen_job_id = f"regen_{str(uuid.uuid4())[:8]}"
        job.regeneration_job_id = regen_job_id
        
        # Start background regeneration
        regeneration_thread = threading.Thread(
            target=regenerate_video_background_ass, 
            args=(job_id, captions, caption_position, caption_position_percent, speaker_colors, speaker_settings, end_screen)
        )
        regeneration_thread.daemon = True
        regeneration_thread.start()
        
        return jsonify({
            'status': 'success', 
            'message': 'Caption update started',
            'regeneration_job_id': regen_job_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to start caption update: {str(e)}'}), 500


@app.route('/api/upload_to_youtube', methods=['POST'])
@youtube_service_required
def upload_to_youtube():
    """Upload clip to YouTube - REQUIRES AUTHENTICATION"""
    try:
        user = get_current_user()
        youtube_service = g.youtube_service
        
        data = request.json
        job_id = data.get('job_id')
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        privacy_status = data.get('privacy_status', 'private')
        
        if job_id not in active_jobs:
            return jsonify({'error': 'Job not found'}), 404
        
        job = active_jobs[job_id]
        
        # For anonymous jobs, convert them to user jobs upon upload
        if job.is_anonymous:
            # Update job ownership
            job.user_id = user.id
            job.is_anonymous = False
            
            # Convert in database
            convert_anonymous_clips_to_user(job.session_id, user.id)
        elif job.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        if not job.clip_data:
            return jsonify({'error': 'No clip available for upload'}), 400
        
        if not title:
            return jsonify({'error': 'Title is required'}), 400
        
        video_path = job.clip_data['path']
        
        if not os.path.exists(video_path):
            return jsonify({'error': 'Video file not found'}), 404
        
        # Upload to YouTube
        from googleapiclient.http import MediaFileUpload
        
        body = {
            'snippet': {
                'title': title[:100],
                'description': f"{description}\n\n#Shorts"[:5000],
                'tags': ['Shorts', 'Viral', 'Clips', 'AI', 'AutoGenerated'],
                'categoryId': '22',
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False,
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        insert_request = youtube_service.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        error = None
        retry = 0
        
        while response is None:
            try:
                status, response = insert_request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    socketio.emit('upload_progress', {
                        'job_id': job_id,
                        'progress': progress
                    }, room=f"user_{user.id}")
                    
            except Exception as e:
                error = e
                if retry < 3:
                    retry += 1
                    time.sleep(2 ** retry)
                else:
                    raise
        
        if response and 'id' in response:
            video_id = response['id']
            video_url = f'https://www.youtube.com/watch?v={video_id}'
            
            # Save upload history
            user.add_upload_history(
                video_id=video_id,
                video_title=title,
                video_url=video_url,
                status='completed'
            )
            
            return jsonify({
                'status': 'success',
                'video_id': video_id,
                'url': video_url,
                'message': f'Successfully uploaded: {title}'
            })
        else:
            return jsonify({
                'error': 'Upload completed but no video ID returned'
            }), 500
            
    except Exception as e:
        logger.error(f"YouTube upload failed: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Check if it's a scope issue
        if "insufficient authentication scopes" in str(e).lower() or "insufficientPermissions" in str(e):
            return jsonify({
                'error': 'Your account needs to be re-authenticated to enable YouTube uploads. Please sign out and sign in again.',
                'error_type': 'insufficient_scopes',
                'needs_reauth': True
            }), 403
        
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


@app.route('/api/upload_history')
def get_upload_history():
    """Get user's upload history - only for authenticated users"""
    user = get_current_user()
    
    if not user:
        return jsonify({'uploads': []})
    
    history = user.get_upload_history(limit=20)
    
    return jsonify({
        'uploads': [
            {
                'video_id': item['video_id'],
                'title': item['video_title'],
                'url': item['video_url'],
                'uploaded_at': item['uploaded_at'].isoformat() if item['uploaded_at'] else None,
                'status': item['upload_status']
            }
            for item in history
        ]
    })


# ==================== STATIC FILE ROUTES ====================

@app.route('/clips/<filename>')
def serve_clip(filename):
    """Serve video clips"""
    response = send_from_directory('clips', filename)
    
    # Add headers for video files
    if filename.endswith('.mp4'):
        response.headers['Content-Type'] = 'video/mp4'
        response.headers['Accept-Ranges'] = 'bytes'
    elif filename.endswith('.ass'):
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    
    return response


# ==================== WEBSOCKET EVENTS ====================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    # Get job_id from query params if available
    from flask_socketio import join_room
    
    job_id = request.args.get('job_id')
    if job_id:
        join_room(job_id)
        emit('connected', {'room': job_id, 'type': 'job'})
        print(f'Client connected to job room: {job_id}')
    
    # Also handle upload_id for file uploads
    upload_id = request.args.get('upload_id')
    if upload_id:
        join_room(upload_id)
        emit('connected', {'room': upload_id, 'type': 'upload'})
        print(f'Client connected to upload room: {upload_id}')


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected')


# ==================== HELPER FUNCTIONS ====================

def parse_time_to_seconds(time_str):
    """Convert MM:SS or seconds to seconds"""
    if not time_str:
        return None
    
    time_str = str(time_str).strip()
    
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            try:
                minutes = int(parts[0])
                seconds = int(parts[1])
                return minutes * 60 + seconds
            except ValueError:
                return None
    else:
        try:
            return float(time_str)
        except ValueError:
            return None
    
    return None


def extract_caption_data(clip_data):
    """Extract caption data from subtitle files"""
    subtitle_file = clip_data.get('subtitle_file')
    if not subtitle_file or not os.path.exists(subtitle_file):
        return []
    
    if subtitle_file.endswith('.srt'):
        return extract_captions_from_srt_fixed(subtitle_file)
    elif subtitle_file.endswith('.ass'):
        return extract_captions_from_ass_fixed(subtitle_file)
    
    return []


def extract_captions_from_srt_fixed(srt_file_path: str):
    """Extract captions from SRT file"""
    captions = []
    
    try:
        with open(srt_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace('\\n', '\n')
        subtitle_blocks = content.strip().split('\n\n')
        
        for block in subtitle_blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:
                try:
                    index = int(lines[0])
                    timing = lines[1]
                    text = '\n'.join(lines[2:])
                    
                    if ' --> ' in timing:
                        start_time_str, end_time_str = timing.split(' --> ')
                        
                        speaker = 'Speaker 1'
                        if text.startswith('[') and '] ' in text:
                            speaker_end = text.find('] ')
                            speaker = text[1:speaker_end]
                            text = text[speaker_end + 2:]
                        
                        captions.append({
                            'text': text.strip(),
                            'speaker': speaker,
                            'start_time': start_time_str.strip(),
                            'end_time': end_time_str.strip(),
                            'index': index
                        })
                        
                except Exception:
                    continue
        
        return captions
        
    except Exception as e:
        print(f"Error reading SRT file: {e}")
        return []


def extract_captions_from_ass_fixed(ass_file_path: str):
    """Extract captions from ASS file"""
    captions = []
    
    try:
        with open(ass_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            if line.startswith('Dialogue:'):
                try:
                    parts = line.split(',', 9)
                    if len(parts) >= 10:
                        start_time = parts[1]
                        end_time = parts[2]
                        speaker = parts[3] if parts[3] else 'Speaker 1'
                        text = parts[9]
                        
                        import re
                        text = re.sub(r'{[^}]*}', '', text)
                        text = text.strip()
                        
                        if text:
                            captions.append({
                                'text': text,
                                'speaker': speaker,
                                'start_time': start_time,
                                'end_time': end_time,
                                'index': len(captions)
                            })
                            
                except Exception:
                    continue
        
        return captions
        
    except Exception as e:
        print(f"Error reading ASS file: {e}")
        return []


def regenerate_video_background_ass(job_id, updated_captions, caption_position='bottom', caption_position_percent=80, speaker_colors=None, speaker_settings=None, end_screen=None):
    """Background thread for video regeneration using ASS caption system"""
    try:
        job = active_jobs[job_id]
        original_clip_data = job.clip_data
        
        # Default speaker colors if not provided
        if speaker_colors is None:
            speaker_colors = {
                '1': '#FF4500',
                '2': '#00BFFF',
                '3': '#00FF88'
            }
        
        # Default end_screen if not provided
        if end_screen is None:
            end_screen = {}
        
        job.regeneration_status = 'processing'
        job.regeneration_progress = 10
        
        socketio.emit('regeneration_update', {
            'job_id': job_id,
            'regeneration_job_id': job.regeneration_job_id,
            'status': 'processing',
            'progress': 10,
            'message': 'Creating captions using ASS system...'
        }, room=job_id)
        
        subtitle_file = original_clip_data.get('subtitle_file')
        original_video_path = original_clip_data['path']
        
        if not subtitle_file:
            raise Exception('Caption file not found')
        
        job.regeneration_progress = 30
        socketio.emit('regeneration_update', {
            'job_id': job_id,
            'regeneration_job_id': job.regeneration_job_id,
            'status': 'processing',
            'progress': 30,
            'message': f'Synchronizing {len(updated_captions)} captions with original speech timing...'
        }, room=job_id)
        
        # CRITICAL FIX: Use the video duration for proper caption distribution
        video_duration = job.duration if hasattr(job, 'duration') else 30.0
        success = clipper.update_captions_ass(
            subtitle_file, 
            updated_captions, 
            video_duration,
            caption_position,
            caption_position_percent,
            speaker_colors,
            speaker_settings,
            end_screen
        )
        
        if not success:
            raise Exception('Failed to update captions using ASS system')
        
        job.regeneration_progress = 50
        socketio.emit('regeneration_update', {
            'job_id': job_id,
            'regeneration_job_id': job.regeneration_job_id,
            'status': 'processing',
            'progress': 50,
            'message': f'Speech-synchronized captions created - burning into video...'
        }, room=job_id)
        
        temp_ass_path = original_video_path.replace('.mp4', '_ASS_temp.mp4')
        base_video_path = original_video_path.replace('.mp4', '_temp_switching.mp4')
        
        if not os.path.exists(base_video_path):
            no_caption_path = original_video_path.replace('.mp4', '_no_captions.mp4')
            if os.path.exists(no_caption_path):
                base_video_path = no_caption_path
            else:
                base_video_path = original_video_path
        
        job.regeneration_progress = 70
        socketio.emit('regeneration_update', {
            'job_id': job_id,
            'regeneration_job_id': job.regeneration_job_id,
            'status': 'processing',
            'progress': 70,
            'message': 'Burning ASS captions into video...'
        }, room=job_id)
        
        success = clipper.burn_captions_into_video_debug(
            base_video_path,
            subtitle_file,
            temp_ass_path
        )
        
        if not success:
            raise Exception('Failed to burn ASS captions into video')
        
        job.regeneration_progress = 90
        socketio.emit('regeneration_update', {
            'job_id': job_id,
            'regeneration_job_id': job.regeneration_job_id,
            'status': 'processing',
            'progress': 90,
            'message': 'Finalizing video...'
        }, room=job_id)
        
        if os.path.exists(original_video_path):
            os.remove(original_video_path)
        
        os.rename(temp_ass_path, original_video_path)
        
        job.clip_data['updated_at'] = datetime.now().isoformat()
        job.clip_data['caption_updates'] = len(updated_captions)
        job.clip_data['ass_captions_applied'] = True
        
        # Update anonymous clip in database if needed
        if job.is_anonymous:
            save_anonymous_clip(job)
        
        job.regeneration_status = 'completed'
        job.regeneration_progress = 100
        
        socketio.emit('regeneration_complete', {
            'job_id': job_id,
            'regeneration_job_id': job.regeneration_job_id,
            'status': 'completed',
            'progress': 100,
            'message': f'Video updated with speech-synchronized captions!'
        }, room=job_id)
        
    except Exception as e:
        print(f"Video regeneration failed for job {job_id}: {e}")
        
        if job_id in active_jobs:
            job = active_jobs[job_id]
            job.regeneration_status = 'failed'
            job.regeneration_progress = 0
            
            socketio.emit('regeneration_error', {
                'job_id': job_id,
                'regeneration_job_id': job.regeneration_job_id,
                'status': 'failed',
                'error': str(e)
            }, room=job_id)


@app.route('/api/available_clips')
def get_available_clips():
    """Get list of available clip files"""
    clips_dir = os.path.join(os.path.dirname(__file__), 'clips')
    clips = []
    
    if os.path.exists(clips_dir):
        for file in sorted(os.listdir(clips_dir)):
            if file.endswith('.mp4') and not file.endswith('_no_captions.mp4') and not file.startswith('.'):
                clips.append(file)
    
    return jsonify({'clips': clips})

@app.route('/api/fix_job/<job_id>', methods=['POST'])
def fix_job_data(job_id):
    """Fix missing job data by reconstructing from files"""
    if job_id not in active_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = active_jobs[job_id]
    
    # Try to reconstruct clip data
    reconstructed = attempt_reconstruct_clip_data(job)
    if reconstructed:
        if not job.clip_data:
            job.clip_data = {}
        
        # Update job clip data with reconstructed data
        job.clip_data.update(reconstructed)
        
        # Extract captions if subtitle file exists
        if reconstructed.get('subtitle_file'):
            caption_data = extract_caption_data({'subtitle_file': reconstructed['subtitle_file']})
            job.clip_data['captions'] = caption_data
        
        return jsonify({
            'success': True,
            'message': 'Job data reconstructed',
            'clip_data': job.clip_data
        })
    
    return jsonify({'error': 'Could not reconstruct job data'}), 400

@app.route('/api/refresh_video/<job_id>')
def refresh_video(job_id):
    """Refresh video data"""
    user = get_current_user()
    session_id = get_or_create_session_id()
    
    if job_id not in active_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = active_jobs[job_id]
    
    # Check authorization
    if job.user_id:
        if not user or job.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
    else:
        if job.session_id != session_id:
            return jsonify({'error': 'Unauthorized'}), 403
    
    if not job.clip_data:
        return jsonify({'error': 'No clip data available'}), 400
    
    caption_data = extract_caption_data(job.clip_data)
    job.clip_data['captions'] = caption_data
    
    video_path = job.clip_data['path']
    filename = os.path.basename(video_path)
    cache_buster = str(int(time.time()))
    
    return jsonify({
        'status': 'success',
        'clip_data': job.clip_data,
        'captions': caption_data,
        'video_url': f"/clips/{filename}?v={cache_buster}"
    })


@app.route('/api/debug/job/<job_id>')
def debug_job(job_id):
    """Debug endpoint to check job data"""
    if job_id not in active_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = active_jobs[job_id]
    
    # Check if files exist
    files_info = {}
    if job.clip_data and 'path' in job.clip_data:
        video_path = job.clip_data['path']
        files_info['video_exists'] = os.path.exists(video_path)
        files_info['video_path'] = video_path
        files_info['video_size'] = os.path.getsize(video_path) if os.path.exists(video_path) else 0
    else:
        # Try to find video files based on patterns
        clips_dir = os.path.join(os.path.dirname(__file__), 'clips')
        possible_files = []
        if os.path.exists(clips_dir):
            for file in os.listdir(clips_dir):
                if file.endswith('.mp4') and not file.endswith('_no_captions.mp4'):
                    possible_files.append(file)
        files_info['possible_video_files'] = possible_files
    
    if job.clip_data and 'subtitle_file' in job.clip_data:
        subtitle_path = job.clip_data['subtitle_file']
        files_info['subtitle_exists'] = os.path.exists(subtitle_path)
        files_info['subtitle_path'] = subtitle_path
    
    # Try to reconstruct clip data if missing
    reconstructed_data = None
    if not job.clip_data or not job.clip_data.get('path'):
        reconstructed_data = attempt_reconstruct_clip_data(job)
    
    return jsonify({
        'job_id': job_id,
        'status': job.status,
        'progress': job.progress,
        'message': job.message,
        'clip_data_keys': list(job.clip_data.keys()) if job.clip_data else None,
        'has_captions': 'captions' in job.clip_data if job.clip_data else False,
        'captions_count': len(job.clip_data.get('captions', [])) if job.clip_data else 0,
        'files_info': files_info,
        'error': job.error,
        'reconstructed_data': reconstructed_data
    })

def attempt_reconstruct_clip_data(job):
    """Attempt to reconstruct clip data from available files"""
    clips_dir = os.path.join(os.path.dirname(__file__), 'clips')
    
    # Look for video files that might match this job
    video_patterns = [
        f"auto_peak_clip_*_{job.start_time or job.duration}s.mp4",
        f"auto_peak_clip__{job.start_time or job.duration}s.mp4",
        f"clip_{job.job_id}.mp4"
    ]
    
    import glob
    for pattern in video_patterns:
        matches = glob.glob(os.path.join(clips_dir, pattern))
        if matches:
            video_path = matches[0]
            video_filename = os.path.basename(video_path)
            
            # Look for corresponding subtitle file
            subtitle_path = video_path.replace('.mp4', '_captions.ass')
            
            return {
                'path': video_path,
                'filename': video_filename,
                'subtitle_file': subtitle_path if os.path.exists(subtitle_path) else None,
                'reconstructed': True
            }
    
    return None


# ==================== ERROR PAGES ====================

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


# ==================== CLEANUP ====================

def cleanup_expired_clips():
    """Cleanup expired anonymous clips periodically"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute('SELECT cleanup_expired_anonymous_clips()')
        conn.commit()
        print("Cleaned up expired anonymous clips")
    except Exception as e:
        print(f"Error cleaning up clips: {e}")
    finally:
        cur.close()
        conn.close()


def cleanup_old_uploads():
    """Clean up old uploaded files"""
    try:
        now = time.time()
        
        # Clean uploaded videos older than 24 hours
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(filepath):
                if os.path.getmtime(filepath) < now - 86400:  # 24 hours
                    os.remove(filepath)
                    logger.info(f"Cleaned up old upload: {filename}")
        
        # Clean abandoned temp uploads older than 2 hours
        for upload_id in os.listdir(app.config['TEMP_UPLOAD_FOLDER']):
            dirpath = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], upload_id)
            if os.path.isdir(dirpath):
                if os.path.getmtime(dirpath) < now - 7200:  # 2 hours
                    shutil.rmtree(dirpath)
                    logger.info(f"Cleaned up abandoned upload: {upload_id}")
                    
    except Exception as e:
        logger.error(f"Upload cleanup error: {str(e)}")


def schedule_cleanup():
    while True:
        time.sleep(3600)  # Run every hour
        cleanup_expired_clips()
        cleanup_old_uploads()  # Add upload cleanup


if __name__ == '__main__':
    # Ensure required directories exist
    os.makedirs('clips', exist_ok=True)
    os.makedirs('downloads', exist_ok=True)
    
    # Run migration for anonymous clips
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("anonymous_clips_migration", "migrations/002_anonymous_clips.py")
        migration_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration_module)
        migration_module.run_migration()
    except Exception as e:
        print(f"Migration warning: {e}")
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=schedule_cleanup)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    print("🎯 Starting Multi-Page Viral Clipper Web App...")
    print("🌐 Access at: http://localhost:5000")
    print("📄 Multi-page architecture enabled")
    print("🔓 Anonymous clip generation: ENABLED")
    print("🔐 Authentication: OPTIONAL (required for upload)")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
