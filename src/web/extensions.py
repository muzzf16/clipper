from flask_socketio import SocketIO
import logging

# Initialize SocketIO
socketio = SocketIO(cors_allowed_origins="*")

# Logger
logger = logging.getLogger(__name__)
