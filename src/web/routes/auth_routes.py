from flask import Blueprint, request, session, url_for, jsonify, render_template, redirect
from auth import get_current_user, OAuthManager, logout_user
from src.web.utils.helpers import get_or_create_session_id
from src.web.services.job_service import convert_anonymous_clips_to_user, get_anonymous_clips
import logging

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
oauth_manager = OAuthManager()

@auth_bp.route('/api/auth/login')
def auth_login():
    """Initiate OAuth login flow"""
    try:
        # Store the current session ID to convert anonymous clips later
        session['pre_auth_session_id'] = get_or_create_session_id()
        
        redirect_uri = url_for('auth.auth_callback', _external=True)
        print(f"DEBUG: Generated OAuth redirect URI: {redirect_uri}")
        authorization_url, state = oauth_manager.get_authorization_url(redirect_uri)
        
        # Store state in session for CSRF protection
        session['oauth_state'] = state
        
        return jsonify({
            'authorization_url': authorization_url,
            'status': 'redirect_required'
        })
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500


@auth_bp.route('/api/auth/callback')
def auth_callback():
    """Handle OAuth callback"""
    # Verify state
    state = request.args.get('state')
    stored_state = session.pop('oauth_state', None)
    
    if not state or state != stored_state:
        return render_template('auth_error.html', error='Invalid state parameter')
    
    # Handle the callback
    redirect_uri = url_for('auth.auth_callback', _external=True)
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
        return redirect(url_for('pages.index', auth='success'))
    else:
        return render_template('auth_error.html', error='Authentication failed')


@auth_bp.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """Logout user"""
    logout_user()
    return jsonify({'status': 'success', 'message': 'Logged out successfully'})


@auth_bp.route('/api/auth/status')
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
