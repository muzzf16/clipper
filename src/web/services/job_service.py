import uuid
import threading
import logging
import os
import json
from datetime import datetime, timedelta
from flask import current_app
from src.core.auto_peak_viral_clipper import AutoPeakViralClipper
from src.web.extensions import socketio
from src.web.utils.helpers import extract_caption_data
from database import update_one, find_many, update_many

logger = logging.getLogger(__name__)

# Initialize the clipper
clipper = AutoPeakViralClipper()

# Store active jobs
active_jobs = {}

class ClipJob:
    """Represents a clip generation job"""
    def __init__(self, job_id, user_id, session_id, url, duration, start_time=None, end_time=None, num_clips=1):
        self.job_id = job_id
        self.user_id = user_id  # Can be None for anonymous users
        self.session_id = session_id  # Always present
        self.url = url
        self.duration = duration
        self.start_time = start_time
        self.end_time = end_time
        self.num_clips = num_clips
        self.status = "starting"
        self.progress = 0
        self.message = "Initializing..."
        self.clip_data = {}
        self.generated_clips = []  # Store all generated clips
        self.error = None
        self.created_at = datetime.now()
        self.regeneration_status = None
        self.regeneration_progress = 0
        self.regeneration_job_id = None
        self.is_anonymous = user_id is None

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

def save_anonymous_clip(job):
    """Save anonymous clip to database"""
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
                    'generated_clips': job.generated_clips,
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

def process_clip_generation(job_id, app_context=None):
    """Background thread for clip generation"""
    # If app_context is provided, push it
    if app_context:
        app_context.push()
        
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
        logger.info(f"Generating clip for job {job_id} with URL: {job.url}, duration: {actual_duration}, start: {actual_start_time}, num_clips: {job.num_clips}")
        
        if job.num_clips > 1:
            # Multi-clip generation
            clips_data = clipper.generate_multiple_viral_clips(
                video_url=job.url,
                num_clips=job.num_clips,
                duration=actual_duration,
                start_time=actual_start_time
            )
            
            if clips_data:
                job.generated_clips = clips_data
                # Use the first clip as the primary one for backward compatibility
                clip_data = clips_data[0]
            else:
                clip_data = None
        else:
            # Single clip generation
            clip_data = clipper.generate_viral_clip(
                video_url=job.url,
                duration=actual_duration,
                start_time=actual_start_time
            )
            if clip_data:
                job.generated_clips = [clip_data]
        
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
                'clip_data': job.clip_data,
                'captions': caption_data
            }, room=job_id)
        else:
            job.error = "Clip generation failed"
            update_job_progress(job_id, "error", 0, "Clip generation failed")
            
    except Exception as e:
        job.error = str(e)
        update_job_progress(job_id, "error", 0, f"Error: {str(e)}")
    finally:
        if app_context:
            app_context.pop()

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
        logger.error(f"Video regeneration failed for job {job_id}: {e}")
        
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

def attempt_reconstruct_clip_data(job):
    """Attempt to reconstruct clip data from available files"""
    clips_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'clips')
    # Note: path adjustment needed because we are now in src/web/services
    # Original: os.path.join(os.path.dirname(__file__), 'clips') where __file__ was app.py
    # New: d:\Clippy\src\web\services\job_service.py -> d:\Clippy\clips
    # So we need to go up 3 levels? src/web/services -> src/web -> src -> root
    
    # Better way: use current_app.root_path if available, or relative path
    # But current_app might not be available in all contexts if not pushed
    # Let's assume we run from root
    
    if not os.path.exists(clips_dir):
        # Try relative to current working directory
        clips_dir = 'clips'
    
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
