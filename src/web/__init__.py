from flask import Flask
from src.web.config import Config
from src.web.extensions import socketio
from src.web.routes import pages_bp, auth_bp, api_bp, upload_bp
from src.web.sockets import register_socket_events
from database import init_db
import os

def create_app(config_class=Config):
    app = Flask(__name__, 
                template_folder='../../templates',
                static_folder='../../static')
    app.config.from_object(config_class)
    
    # Initialize extensions
    init_db(app)
    socketio.init_app(app)
    
    # Register blueprints
    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(upload_bp)
    
    # Register socket events
    register_socket_events(socketio)
    
    # Ensure upload directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['TEMP_UPLOAD_FOLDER'], exist_ok=True)
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        return render_template('500.html'), 500
        
    return app
