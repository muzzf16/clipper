"""
User model and database operations - MongoDB Edition
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import json

# Import MongoDB functions
from database import (
    find_one, 
    find_many, 
    insert_one, 
    update_one, 
    delete_one, 
    delete_many
)

logger = logging.getLogger(__name__)


class User:
    """User model for Clippy"""
    
    def __init__(self, user_id: str = None, google_id: str = None, 
                 email: str = None, name: str = None, picture_url: str = None,
                 refresh_token: str = None, access_token: str = None,
                 token_expires_at: datetime = None, created_at: datetime = None,
                 last_login: datetime = None, is_active: bool = True):
        self.id = str(user_id) if user_id else None
        self.google_id = google_id
        self.email = email
        self.name = name
        self.picture_url = picture_url
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.token_expires_at = token_expires_at
        self.created_at = created_at or datetime.utcnow()
        self.last_login = last_login or datetime.utcnow()
        self.is_active = is_active
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create User instance from dictionary"""
        if not data:
            return None
            
        return cls(
            user_id=str(data.get('_id')),
            google_id=data.get('google_id'),
            email=data.get('email'),
            name=data.get('name'),
            picture_url=data.get('picture_url'),
            refresh_token=data.get('refresh_token'),
            access_token=data.get('access_token'),
            token_expires_at=data.get('token_expires_at'),
            created_at=data.get('created_at'),
            last_login=data.get('last_login'),
            is_active=data.get('is_active', True)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert User instance to dictionary"""
        return {
            'id': self.id,
            'google_id': self.google_id,
            'email': self.email,
            'name': self.name,
            'picture_url': self.picture_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'is_active': self.is_active
        }
    
    def save(self) -> bool:
        """Save user to database"""
        try:
            user_data = {
                'google_id': self.google_id,
                'email': self.email,
                'name': self.name,
                'picture_url': self.picture_url,
                'refresh_token': self.refresh_token,
                'access_token': self.access_token,
                'token_expires_at': self.token_expires_at,
                'last_login': self.last_login,
                'is_active': self.is_active
            }
            
            if self.created_at:
                user_data['created_at'] = self.created_at
            
            if self.id:
                # Update existing user by ID
                from bson.objectid import ObjectId
                update_one('users', {'_id': ObjectId(self.id)}, {'$set': user_data})
            else:
                # Insert or update by google_id
                # First check if user exists by google_id
                existing = find_one('users', {'google_id': self.google_id})
                
                if existing:
                    self.id = str(existing['_id'])
                    update_one('users', {'google_id': self.google_id}, {'$set': user_data})
                else:
                    user_data['created_at'] = datetime.utcnow()
                    self.created_at = user_data['created_at']
                    inserted_id = insert_one('users', user_data)
                    self.id = inserted_id
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save user: {e}")
            return False
    
    @classmethod
    def get_by_id(cls, user_id: str) -> Optional['User']:
        """Get user by ID"""
        try:
            from bson.objectid import ObjectId
            result = find_one('users', {'_id': ObjectId(user_id), 'is_active': True})
            return cls.from_dict(result)
        except Exception:
            return None
    
    @classmethod
    def get_by_google_id(cls, google_id: str) -> Optional['User']:
        """Get user by Google ID"""
        result = find_one('users', {'google_id': google_id})
        return cls.from_dict(result)
    
    @classmethod
    def get_by_email(cls, email: str) -> Optional['User']:
        """Get user by email"""
        result = find_one('users', {'email': email, 'is_active': True})
        return cls.from_dict(result)
    
    def update_tokens(self, refresh_token: str, access_token: str, expires_at: datetime) -> bool:
        """Update user tokens"""
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.token_expires_at = expires_at
        return self.save()
    
    def update_last_login(self) -> bool:
        """Update user's last login timestamp"""
        self.last_login = datetime.utcnow()
        return self.save()
    
    def deactivate(self) -> bool:
        """Deactivate user account"""
        self.is_active = False
        return self.save()
    
    def add_upload_history(self, video_id: str, video_title: str, 
                          video_url: str, status: str = 'completed') -> bool:
        """Add upload history for user"""
        try:
            history_data = {
                'user_id': self.id,
                'video_id': video_id,
                'video_title': video_title,
                'video_url': video_url,
                'upload_status': status,
                'uploaded_at': datetime.utcnow()
            }
            insert_one('upload_history', history_data)
            return True
        except Exception as e:
            logger.error(f"Failed to add upload history: {e}")
            return False
    
    def get_upload_history(self, limit: int = 50) -> list:
        """Get user's upload history"""
        return find_many(
            'upload_history', 
            {'user_id': self.id}, 
            limit=limit,
            sort=[('uploaded_at', -1)]
        )


class UserSession:
    """Manages user sessions"""
    
    @staticmethod
    def create_session(user_id: str, session_token: str, expires_at: datetime,
                      ip_address: str = None, user_agent: str = None) -> bool:
        """Create a new user session"""
        try:
            session_data = {
                'user_id': str(user_id),
                'session_token': session_token,
                'expires_at': expires_at,
                'created_at': datetime.utcnow(),
                'last_accessed': datetime.utcnow(),
                'ip_address': ip_address,
                'user_agent': user_agent
            }
            insert_one('user_sessions', session_data)
            return True
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return False
    
    @staticmethod
    def get_user_by_session(session_token: str) -> Optional[User]:
        """Get user by valid session token"""
        # Find session
        session = find_one('user_sessions', {
            'session_token': session_token,
            'expires_at': {'$gt': datetime.utcnow()}
        })
        
        if session:
            # Update last accessed
            update_one(
                'user_sessions', 
                {'session_token': session_token}, 
                {'$set': {'last_accessed': datetime.utcnow()}}
            )
            
            # Get user
            return User.get_by_id(session['user_id'])
            
        return None
    
    @staticmethod
    def invalidate_session(session_token: str) -> bool:
        """Invalidate a session"""
        try:
            delete_one('user_sessions', {'session_token': session_token})
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate session: {e}")
            return False
    
    @staticmethod
    def cleanup_expired_sessions() -> int:
        """Clean up expired sessions"""
        try:
            return delete_many('user_sessions', {'expires_at': {'$lt': datetime.utcnow()}})
        except Exception as e:
            logger.error(f"Failed to cleanup sessions: {e}")
            return 0


class PlatformConnection:
    """Manages platform connections for users"""
    
    @staticmethod
    def create_or_update(user_id: str, platform: str, platform_user_id: str,
                        platform_username: str = None, access_token: str = None,
                        refresh_token: str = None, token_expires_at: datetime = None,
                        scopes: str = None, metadata: Dict = None) -> bool:
        """Create or update a platform connection"""
        
        try:
            query = {
                'user_id': str(user_id),
                'platform': platform
            }
            
            update_data = {
                'platform_user_id': platform_user_id,
                'platform_username': platform_username,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expires_at': token_expires_at,
                'scopes': scopes,
                'metadata': metadata,
                'is_active': True,
                'last_used_at': datetime.utcnow()
            }
            
            # Add connected_at only on insert
            update_op = {
                '$set': update_data,
                '$setOnInsert': {'connected_at': datetime.utcnow()}
            }
            
            update_one('platform_connections', query, update_op, upsert=True)
            return True
        except Exception as e:
            logger.error(f"Failed to create/update platform connection: {e}")
            return False
    
    @staticmethod
    def get_connection(user_id: str, platform: str) -> Optional[Dict]:
        """Get a specific platform connection for a user"""
        return find_one('platform_connections', {
            'user_id': str(user_id),
            'platform': platform,
            'is_active': True
        })
    
    @staticmethod
    def get_user_connections(user_id: str) -> list:
        """Get all platform connections for a user"""
        return find_many(
            'platform_connections', 
            {'user_id': str(user_id), 'is_active': True},
            sort=[('connected_at', -1)]
        )
    
    @staticmethod
    def update_tokens(user_id: str, platform: str, access_token: str,
                     refresh_token: str, expires_at: datetime) -> bool:
        """Update tokens for a platform connection"""
        try:
            query = {
                'user_id': str(user_id),
                'platform': platform,
                'is_active': True
            }
            
            update = {
                '$set': {
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'token_expires_at': expires_at,
                    'last_used_at': datetime.utcnow()
                }
            }
            
            update_one('platform_connections', query, update)
            return True
        except Exception as e:
            logger.error(f"Failed to update platform tokens: {e}")
            return False
    
    @staticmethod
    def deactivate_connection(user_id: str, platform: str) -> bool:
        """Deactivate a platform connection"""
        try:
            query = {
                'user_id': str(user_id),
                'platform': platform
            }
            update_one('platform_connections', query, {'$set': {'is_active': False}})
            return True
        except Exception as e:
            logger.error(f"Failed to deactivate platform connection: {e}")
            return False
    
    @staticmethod
    def update_last_used(user_id: str, platform: str) -> bool:
        """Update last used timestamp for a connection"""
        try:
            query = {
                'user_id': str(user_id),
                'platform': platform,
                'is_active': True
            }
            update_one('platform_connections', query, {'$set': {'last_used_at': datetime.utcnow()}})
            return True
        except Exception as e:
            logger.error(f"Failed to update last used: {e}")
            return False
