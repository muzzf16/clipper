import os
import uuid
from flask import session, current_app
import re

def get_or_create_session_id():
    """Get existing session ID or create a new one"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        session.permanent = True
    return session['session_id']

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

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
