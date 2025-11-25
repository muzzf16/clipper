"""Database package for Clippy multi-user support - MongoDB Edition"""

import os
from .mongodb_connection import (
    get_db, 
    init_db, 
    close_db, 
    get_db_connection,
    find_one,
    find_many,
    insert_one,
    update_one,
    update_many,
    delete_one,
    delete_many
)

__all__ = [
    'get_db', 
    'init_db', 
    'close_db', 
    'get_db_connection',
    'find_one',
    'find_many',
    'insert_one',
    'update_one',
    'update_many',
    'delete_one',
    'delete_many'
]

