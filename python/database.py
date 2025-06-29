import sqlite3
from pathlib import Path
import os
import json
import threading

CONFIG_DB_PATH = os.getenv("CONFIG_DB_PATH", "conf/config.db")
DEFAULT_REGEX = {
    "episode_only": [
        "\\[(\\d{1,3})\\]",
        "第(\\d{1,3})集",
        "Episode\\s(\\d{1,3})",
        "-\\s(\\d{1,3})\\s-",
        "(?<![a-zA-Z0-9])E(\\d{1,3})(?!\\d)",
        "-\\s(\\d{1,3})(?=\\s|\\.|\\[|$)",
        "\\s+(\\d{1,3})(?=\\s\\[)",
        "\\s(\\d{1,3})(?=\\s\\()"
    ],
    "season_episode": [
        "[Ss](\\d{1,2})[Ee](\\d{1,3})",
        "第(\\d{1,2})季.?第(\\d{1,3})集",
        "Season\\s(\\d{1,2}).?Episode\\s(\\d{1,3})",
        "\\[(\\d{1,2})\\]\\[(\\d{1,3})\\]",
        "-\\s(\\d{1,2})\\s-\\s*(\\d{1,3})",
        "\\.(\\d{1,2})\\.(\\d{1,3})\\."
    ]
}

class ConfigDB:
    _instance = None
    _local = threading.local()
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    def _get_connection(self):
        """为每个线程获取独立的数据库连接"""
        if not hasattr(self._local, 'conn'):
            Path(CONFIG_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(CONFIG_DB_PATH, check_same_thread=False)
            self._local.cursor = self._local.conn.cursor()
            self._init_tables()
        return self._local.conn, self._local.cursor
    def _init_tables(self):
        """初始化数据库表"""
        conn, cursor = self._local.conn, self._local.cursor
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS regex_config (
                id INTEGER PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                pattern TEXT NOT NULL,
                UNIQUE(pattern_type, pattern)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS whitelist (
                file_path TEXT PRIMARY KEY
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                processed INTEGER DEFAULT 0,
                renamed INTEGER DEFAULT 0,
                target TEXT,
                data TEXT
            )
        ''')
        
        cursor.execute("SELECT COUNT(*) FROM regex_config")
        if cursor.fetchone()[0] == 0:
            for pattern_type, patterns in DEFAULT_REGEX.items():
                for pattern in patterns:
                    cursor.execute(
                        "INSERT OR IGNORE INTO regex_config (pattern_type, pattern) VALUES (?, ?)",
                        (pattern_type, pattern)
                    )
        
        conn.commit()

    
    def get_regex_patterns(self):
        conn, cursor = self._get_connection()
        cursor.execute("SELECT pattern_type, pattern FROM regex_config")
        patterns = {}
        for pattern_type, pattern in cursor.fetchall():
            patterns.setdefault(pattern_type, []).append(pattern)
        return patterns
    
    def update_regex_patterns(self, new_patterns):
        conn, cursor = self._get_connection()
        cursor.execute("DELETE FROM regex_config")
        for pattern_type, patterns in new_patterns.items():
            for pattern in patterns:
                cursor.execute(
                    "INSERT INTO regex_config (pattern_type, pattern) VALUES (?, ?)",
                    (pattern_type, pattern)
                )
        conn.commit()
    
    def get_whitelist(self):
        conn, cursor = self._get_connection()
        cursor.execute("SELECT file_path FROM whitelist")
        return {row[0] for row in cursor.fetchall()}
    
    def add_to_whitelist(self, file_path):
        conn, cursor = self._get_connection()
        cursor.execute(
            "INSERT OR IGNORE INTO whitelist (file_path) VALUES (?)",
            (file_path,)
        )
        conn.commit()
        return cursor.rowcount > 0
    
    def remove_from_whitelist(self, file_path):
        conn, cursor = self._get_connection()
        cursor.execute(
            "DELETE FROM whitelist WHERE file_path = ?",
            (file_path,)
        )
        conn.commit()
        return cursor.rowcount > 0
    def add_scan_history(self, result):
        """添加扫描历史记录"""
        conn, cursor = self._get_connection()
        cursor.execute('''
            INSERT INTO scan_history (timestamp, status, message, processed, renamed, target, data)
            VALUES (?, ?, ?,?, ?, ?, ?)
        ''', (
            result.get('timestamp'),
            result.get('status'),
            result.get('message'),
            result.get('processed', 0),
            result.get('renamed', 0),
            result.get('target'),
            json.dumps(result, ensure_ascii=False)
        ))
        conn.commit()
        
        cursor.execute('''
            DELETE FROM scan_history 
            WHERE id NOT IN (
                SELECT id FROM scan_history 
                ORDER BY timestamp DESC 
                LIMIT 50
            )
        ''')
        conn.commit()

    def get_scan_history(self):
        """获取扫描历史"""
        conn, cursor = self._get_connection()
        cursor.execute('''
            SELECT data FROM scan_history 
            ORDER BY timestamp DESC
        ''')
        history = []
        for row in cursor.fetchall():
            try:
                history.append(json.loads(row[0]))
            except:
                pass
        return history

    def get_last_scan_result(self):
        """获取最后一次扫描结果"""
        conn, cursor = self._get_connection()
        cursor.execute('''
            SELECT data FROM scan_history 
            ORDER BY timestamp DESC 
            LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row[0])
            except:
                pass
        return None
    def close(self):
        if hasattr(self._local, 'conn'):
            self._local.conn.close()

config_db = ConfigDB()