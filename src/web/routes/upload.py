from flask import Blueprint, request, jsonify
from auth import login_required, get_current_user
from src.web.services.upload_service import init_upload_session, handle_chunk_upload
import logging

upload_bp = Blueprint('upload', __name__)
logger = logging.getLogger(__name__)

@upload_bp.route('/api/init_upload', methods=['POST'])
def init_upload():
    """Initialize chunked upload session"""
    try:
        data = request.json
        filename = data.get('filename', '')
        filesize = data.get('size', 0)
        filetype = data.get('type', '')
        
        user = get_current_user()
        user_id = user.id if user else None
        
        result = init_upload_session(filename, filesize, filetype, user_id)
        
        return jsonify(result)
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Upload init error: {str(e)}")
        return jsonify({'error': 'Failed to initialize upload'}), 500


@upload_bp.route('/api/upload_chunk', methods=['POST'])
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
        
        result = handle_chunk_upload(
            chunk, 
            upload_id, 
            chunk_number, 
            total_chunks, 
            start_time, 
            end_time
        )
        
        return jsonify(result)
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Chunk upload error: {str(e)}")
        return jsonify({'error': 'Chunk upload failed'}), 500
