from flask import Blueprint, render_template, request, redirect, url_for, send_from_directory, current_app, session
from auth import login_required, get_current_user
from src.web.utils.helpers import get_or_create_session_id
from src.web.services.job_service import active_jobs, convert_anonymous_clips_to_user
import logging
import json
import os

pages_bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

@pages_bp.route('/')
def index():
    """Home page - Input form"""
    return render_template('pages/input.html')

@pages_bp.route('/process')
def process_page():
    """Processing page - Shows progress"""
    job_id = request.args.get('job_id')
    if not job_id:
        return redirect(url_for('pages.index'))
    return render_template('pages/process.html', job_id=job_id)

@pages_bp.route('/edit')
def edit_page():
    """Edit captions page"""
    job_id = request.args.get('job_id')
    if not job_id:
        return redirect(url_for('pages.index'))
    
    # Get job data
    user = get_current_user()
    session_id = get_or_create_session_id()
    
    if job_id not in active_jobs:
        return redirect(url_for('pages.index'))
    
    job = active_jobs[job_id]
    
    # Check authorization
    if job.user_id:
        if not user or job.user_id != user.id:
            return redirect(url_for('pages.index'))
    else:
        if job.session_id != session_id:
            return redirect(url_for('pages.index'))
    
    # Check if job is completed
    if job.status != 'completed':
        # If not completed, redirect back to processing page
        logger.warning(f"Job {job_id} not completed, status: {job.status}")
        return redirect(url_for('pages.process_page', job_id=job_id))
    
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
    generated_clips = getattr(job, 'generated_clips', [])
    
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
                         clip_data=clip_data,
                         generated_clips=generated_clips)

@pages_bp.route('/upload')
@login_required
def upload_page():
    """Upload page - Requires authentication"""
    job_id = request.args.get('job_id')
    if not job_id:
        return redirect(url_for('pages.index'))
    
    # Verify user owns this clip
    user = get_current_user()
    
    if job_id not in active_jobs:
        return redirect(url_for('pages.index'))
    
    job = active_jobs[job_id]
    
    # For anonymous jobs, convert them to user jobs
    if job.is_anonymous:
        job.user_id = user.id
        job.is_anonymous = False
        convert_anonymous_clips_to_user(job.session_id, user.id)
    elif job.user_id != user.id:
        return redirect(url_for('pages.index'))
    
    return render_template('pages/upload.html', job_id=job_id)

@pages_bp.route('/clips/<filename>')
def serve_clip(filename):
    """Serve video clips"""
    # Use current_app.root_path to find the clips directory relative to the app root
    # Assuming clips is in the root directory (d:\Clippy\clips)
    # We need to be careful about the path. 
    # If we run from d:\Clippy, clips is just 'clips'.
    
    # In app.py: send_from_directory('clips', filename)
    # We should use absolute path or configured path
    clips_dir = os.path.join(os.getcwd(), 'clips')
    response = send_from_directory(clips_dir, filename)
    
    # Add headers for video files
    if filename.endswith('.mp4'):
        response.headers['Content-Type'] = 'video/mp4'
        response.headers['Accept-Ranges'] = 'bytes'
    elif filename.endswith('.ass'):
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    
    return response
