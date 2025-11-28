from flask import Blueprint, request, jsonify, g, current_app
from auth import login_required, get_current_user
from auth.decorators import youtube_service_required
from src.web.utils.helpers import get_or_create_session_id, parse_time_to_seconds, extract_caption_data
from src.web.services.job_service import active_jobs, ClipJob, process_clip_generation, regenerate_video_background_ass, attempt_reconstruct_clip_data, convert_anonymous_clips_to_user
from src.web.extensions import socketio
import uuid
import threading
import os
import time
import logging
from src.captions.caption_fragment_fix import merge_fragmented_captions

api_bp = Blueprint('api', __name__)
logger = logging.getLogger(__name__)

@api_bp.route('/api/generate_clip', methods=['POST'])
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
    num_clips = data.get('num_clips', 1)
    
    # Convert MM:SS to seconds if provided
    if start_time:
        start_time = parse_time_to_seconds(start_time)
    if end_time:
        end_time = parse_time_to_seconds(end_time)
    
    # Create job
    job_id = str(uuid.uuid4())
    user_id = user.id if user else None
    job = ClipJob(job_id, user_id, session_id, url, duration, start_time, end_time, num_clips)
    active_jobs[job_id] = job
    
    # Start background processing
    # We need to pass app context to the thread
    app = current_app._get_current_object()
    thread = threading.Thread(target=process_clip_generation, args=(job_id, app.app_context()))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'job_id': job_id, 
        'status': 'started',
        'is_anonymous': user_id is None
    })

@api_bp.route('/api/job_status/<job_id>')
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

@api_bp.route('/api/user_activity')
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

@api_bp.route('/api/update_captions', methods=['POST'])
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

@api_bp.route('/api/upload_to_youtube', methods=['POST'])
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

@api_bp.route('/api/upload_history')
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

@api_bp.route('/api/available_clips')
def get_available_clips():
    """Get list of available clip files"""
    clips_dir = os.path.join(os.getcwd(), 'clips')
    clips = []
    
    if os.path.exists(clips_dir):
        for file in sorted(os.listdir(clips_dir)):
            if file.endswith('.mp4') and not file.endswith('_no_captions.mp4') and not file.startswith('.'):
                clips.append(file)
    
    return jsonify({'clips': clips})

@api_bp.route('/api/fix_job/<job_id>', methods=['POST'])
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

@api_bp.route('/api/refresh_video/<job_id>')
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

@api_bp.route('/api/debug/job/<job_id>')
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
        clips_dir = os.path.join(os.getcwd(), 'clips')
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
