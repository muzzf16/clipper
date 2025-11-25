"""
Database connection management for Clippy - MongoDB Edition
Handles MongoDB connections with connection pooling
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
from datetime import datetime

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from flask import g, current_app

logger = logging.getLogger(__name__)


class MongoDBConnection:
    """Manages MongoDB database connections"""
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self._initialized = False
    
    def init_app(self, app):
        """Initialize database connection with Flask app"""
        # Get MongoDB URI from environment or app config
        mongodb_uri = app.config.get('MONGODB_URI', os.getenv('MONGODB_URI', 'mongodb://localhost:27017/clippy'))
        
        try:
            # Create MongoDB client
            self.client = MongoClient(
                mongodb_uri,
                maxPoolSize=20,
                minPoolSize=1,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000
            )
            
            # Get database name from URI or use default
            if '/' in mongodb_uri.split('://')[-1]:
                db_name = mongodb_uri.split('/')[-1].split('?')[0] or 'clippy'
            else:
                db_name = 'clippy'
            
            self.db = self.client[db_name]
            
            # Test connection
            self.client.server_info()
            
            self._initialized = True
            logger.info(f"MongoDB connection initialized successfully to database: {db_name}")
            
            # Create indexes
            self._create_indexes()
            
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {e}")
            raise
    
    def _create_indexes(self):
        """Create indexes for collections"""
        try:
            # Users collection indexes
            self.db.users.create_index("google_id", unique=True)
            self.db.users.create_index("email")
            
            # Upload history indexes
            self.db.upload_history.create_index("user_id")
            
            # User sessions indexes
            self.db.user_sessions.create_index("session_token", unique=True)
            self.db.user_sessions.create_index("expires_at")
            self.db.user_sessions.create_index("user_id")
            
            # Anonymous clips indexes
            self.db.anonymous_clips.create_index("session_id")
            self.db.anonymous_clips.create_index("job_id", unique=True)
            self.db.anonymous_clips.create_index("expires_at")
            
            logger.info("MongoDB indexes created successfully")
        except Exception as e:
            logger.warning(f"Failed to create some indexes: {e}")
    
    def get_db(self) -> Database:
        """Get database instance"""
        if not self._initialized:
            raise RuntimeError("MongoDB connection not initialized. Call init_app() first.")
        return self.db
    
    def close_connection(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")


# Global database connection instance
db_connection = MongoDBConnection()


def init_db(app):
    """Initialize database connection with Flask app"""
    db_connection.init_app(app)
    
    # Register teardown function
    app.teardown_appcontext(close_db)


def get_db() -> Database:
    """Get database instance for current request context"""
    if 'db' not in g:
        g.db = db_connection.get_db()
    return g.db


def close_db(error=None):
    """Close database connection for current request context"""
    g.pop('db', None)
    # MongoDB connections are pooled, no need to explicitly close per request


def get_db_connection() -> Database:
    """Get a direct database connection (for use outside Flask request context)"""
    return db_connection.get_db()


@contextmanager
def get_collection(collection_name: str) -> Collection:
    """Context manager for database collection operations"""
    db = get_db()
    collection = db[collection_name]
    
    try:
        yield collection
    except Exception as e:
        logger.error(f"Database operation failed on {collection_name}: {e}")
        raise


def find_one(collection_name: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find a single document"""
    with get_collection(collection_name) as collection:
        return collection.find_one(query)


def find_many(collection_name: str, query: Dict[str, Any], limit: int = 0, sort: List = None) -> List[Dict[str, Any]]:
    """Find multiple documents"""
    with get_collection(collection_name) as collection:
        cursor = collection.find(query)
        
        if sort:
            cursor = cursor.sort(sort)
        
        if limit > 0:
            cursor = cursor.limit(limit)
        
        return list(cursor)


def insert_one(collection_name: str, document: Dict[str, Any]) -> str:
    """Insert a single document"""
    with get_collection(collection_name) as collection:
        result = collection.insert_one(document)
        return str(result.inserted_id)


def update_one(collection_name: str, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False) -> int:
    """Update a single document"""
    with get_collection(collection_name) as collection:
        result = collection.update_one(query, update, upsert=upsert)
        return result.modified_count


def update_many(collection_name: str, query: Dict[str, Any], update: Dict[str, Any]) -> int:
    """Update multiple documents"""
    with get_collection(collection_name) as collection:
        result = collection.update_many(query, update)
        return result.modified_count


def delete_one(collection_name: str, query: Dict[str, Any]) -> int:
    """Delete a single document"""
    with get_collection(collection_name) as collection:
        result = collection.delete_one(query)
        return result.deleted_count


def delete_many(collection_name: str, query: Dict[str, Any]) -> int:
    """Delete multiple documents"""
    with get_collection(collection_name) as collection:
        result = collection.delete_many(query)
        return result.deleted_count
