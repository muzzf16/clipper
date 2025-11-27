from flask import request
from flask_socketio import emit, join_room
from src.web.extensions import socketio

def register_socket_events(socketio):
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        # Get job_id from query params if available
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
