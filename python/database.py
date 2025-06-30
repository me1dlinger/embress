"""
/**
 * @author: Meidlinger
 * @date: 2025-07-01
 */
"""

import os
import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

CONFIG_DB_PATH = os.getenv("CONFIG_DB_PATH", "data/conf/config.db")

DEFAULT_REGEX = {
    "episode_only": [
        r"\[(\d{1,3})\]",
        r"第(\d{1,3})集",
        r"Episode\s(\d{1,3})",
        r"-\s(\d{1,3})\s-",
        r"(?<![a-zA-Z0-9])E(\d{1,3})(?!\d)",
        r"-\s(\d{1,3})(?=\s|\.|\[|$)",
        r"\s+(\d{1,3})(?=\s\[)",
        r"\s(\d{1,3})(?=\s\()",
    ],
    "season_episode": [
        r"[Ss](\d{1,2})[Ee](\d{1,3})",
        r"第(\d{1,2})季.?第(\d{1,3})集",
        r"Season\s(\d{1,2}).?Episode\s(\d{1,3})",
        r"\[(\d{1,2})\]\[(\d{1,3})\]",
        r"-\s(\d{1,2})\s-\s*(\d{1,3})",
        r"\.(\d{1,2})\.(\d{1,3})\.",
    ],
}


# ========= 数据库单例 ========= #
class ConfigDB:
    """线程隔离 + 进程单例 + 全局一次初始化"""

    _instance = None
    _local = threading.local()
    _init_lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_connection(self):
        """为当前线程获取 / 创建独立连接"""
        if not hasattr(self._local, "conn"):
            Path(CONFIG_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(CONFIG_DB_PATH, check_same_thread=False)
            self._local.cursor = self._local.conn.cursor()

            # 并发优化
            self._local.cursor.execute("PRAGMA journal_mode=WAL;")
            self._local.cursor.execute("PRAGMA foreign_keys=ON;")

            # 确保全局只初始化一次
            self._ensure_initialized()

        return self._local.conn, self._local.cursor

    def _ensure_initialized(self):
        if ConfigDB._initialized:
            return

        with ConfigDB._init_lock:
            if not ConfigDB._initialized:
                self._init_tables()
                ConfigDB._initialized = True

    def _init_tables(self):
        conn, cursor = self._local.conn, self._local.cursor

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS regex_config (
                id INTEGER PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                pattern TEXT NOT NULL,
                UNIQUE(pattern_type, pattern)
            );
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS whitelist (
                path TEXT PRIMARY KEY,
                item_type TEXT NOT NULL DEFAULT 'file',
                added_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                processed INTEGER DEFAULT 0,
                renamed INTEGER DEFAULT 0,
                target TEXT,
                data TEXT
            );
        """
        )

        cursor.execute("SELECT COUNT(*) FROM regex_config;")
        if cursor.fetchone()[0] == 0:
            for p_type, patterns in DEFAULT_REGEX.items():
                for pat in patterns:
                    cursor.execute(
                        "INSERT OR IGNORE INTO regex_config (pattern_type, pattern) VALUES (?, ?)",
                        (p_type, pat),
                    )

        conn.commit()

        self._add_column_if_missing(
            "scan_history", "renamed_subtitle INTEGER DEFAULT 0"
        )
        self._add_column_if_missing("scan_history", "deleted_nfo INTEGER DEFAULT 0")

    def _add_column_if_missing(self, table: str, column_def: str):
        conn, cursor = self._get_connection()
        col_name = column_def.split()[0]  # 提取列名

        cursor.execute(f"PRAGMA table_info({table});")
        if col_name in (row[1].strip() for row in cursor.fetchall()):
            return

        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def};")
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    def get_regex_patterns(self):
        conn, cursor = self._get_connection()
        cursor.execute("SELECT pattern_type, pattern FROM regex_config;")
        patterns = {}
        for p_type, pat in cursor.fetchall():
            patterns.setdefault(p_type, []).append(pat)
        return patterns

    def update_regex_patterns(self, new_patterns: dict):
        conn, cursor = self._get_connection()
        cursor.execute("DELETE FROM regex_config;")
        for p_type, pats in new_patterns.items():
            for pat in pats:
                cursor.execute(
                    "INSERT INTO regex_config (pattern_type, pattern) VALUES (?, ?)",
                    (p_type, pat),
                )
        conn.commit()

    def get_whitelist(self):
        conn, cursor = self._get_connection()
        cursor.execute(
            "SELECT path, item_type, added_time FROM whitelist "
            "ORDER BY added_time DESC;"
        )
        return [
            {"path": row[0], "type": row[1], "timestamp": row[2]}
            for row in cursor.fetchall()
        ]

    def add_whitelist_items(self, items: list):
        """批量添加白名单"""
        conn, cursor = self._get_connection()
        inserted = skipped = 0
        failed = []

        for item in items:
            path = item.get("path")
            item_type = item.get("type", "file")
            ts = item.get("timestamp") or datetime.utcnow().isoformat()

            if not path:
                failed.append({"path": None, "error": "path 为空"})
                continue

            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO whitelist (path, item_type, added_time) "
                    "VALUES (?, ?, ?);",
                    (path, item_type, ts),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed.append({"path": path, "error": str(exc)})

        conn.commit()
        return {"inserted": inserted, "skipped": skipped, "failed": failed}

    def add_to_whitelist(self, file_path: str):
        return self.add_whitelist_items([{"path": file_path}])["inserted"] == 1

    def remove_from_whitelist(self, file_path: str):
        conn, cursor = self._get_connection()
        cursor.execute("DELETE FROM whitelist WHERE path = ?;", (file_path,))
        conn.commit()
        return cursor.rowcount > 0

    def add_scan_history(self, result: dict):
        conn, cursor = self._get_connection()
        cursor.execute(
            """
            INSERT INTO scan_history
              (timestamp, status, message, processed, renamed,
               renamed_subtitle, deleted_nfo, target, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
            (
                result.get("timestamp"),
                result.get("status"),
                result.get("message"),
                result.get("processed", 0),
                result.get("renamed_video", 0),
                result.get("renamed_subtitle", 0),
                result.get("deleted_nfo", 0),
                result.get("target"),
                json.dumps(result, ensure_ascii=False),
            ),
        )
        conn.commit()

        cursor.execute(
            """
            DELETE FROM scan_history
            WHERE id NOT IN (
                SELECT id FROM scan_history
                ORDER BY timestamp DESC
                LIMIT 50
            );
        """
        )
        conn.commit()

    def get_scan_history(self):
        conn, cursor = self._get_connection()
        cursor.execute("SELECT data FROM scan_history ORDER BY timestamp DESC;")
        history = []
        for (row,) in cursor.fetchall():
            try:
                history.append(json.loads(row))
            except json.JSONDecodeError:
                pass
        return history

    def get_last_scan_result(self):
        conn, cursor = self._get_connection()
        cursor.execute("SELECT data FROM scan_history ORDER BY timestamp DESC LIMIT 1;")
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                pass
        return None

    def close(self):
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            finally:
                del self._local.conn
                del self._local.cursor


config_db = ConfigDB()
