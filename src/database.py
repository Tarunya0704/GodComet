"""Database operations"""
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any

class DatabaseManager:
    """Manages SQLite database for task history"""
    
    def __init__(self, db_path: str = 'data/automation.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                result TEXT,
                error TEXT,
                execution_time REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tool_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                success BOOLEAN,
                execution_time REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_task(self, task_id: str, command: str, status: str, 
                  result: Dict = None, error: str = None, execution_time: float = 0):
        """Save task to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO tasks 
            (id, command, status, created_at, completed_at, result, error, execution_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_id,
            command,
            status,
            datetime.now().isoformat(),
            datetime.now().isoformat() if status == 'completed' else None,
            json.dumps(result) if result else None,
            error,
            execution_time
        ))
        
        conn.commit()
        conn.close()
    
    def log_tool_usage(self, tool_name: str, success: bool, execution_time: float):
        """Log tool usage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tool_usage (tool_name, timestamp, success, execution_time)
            VALUES (?, ?, ?, ?)
        ''', (tool_name, datetime.now().isoformat(), success, execution_time))
        
        conn.commit()
        conn.close()
    
    def get_recent_tasks(self, limit: int = 10) -> List:
        """Get recent tasks"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?', (limit,))
        tasks = cursor.fetchall()
        conn.close()
        return tasks