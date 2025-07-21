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
from typing import Dict, List
import functools
import time


def retry_db_operation(max_retries=3, delay=0.1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        time.sleep(delay * (2**attempt))  # 指数退避
                        continue
                    raise
            return None

        return wrapper

    return decorator


CONFIG_DB_PATH = os.getenv("CONFIG_DB_PATH", "data/conf/config.db")
DEFAULT_REGEX_PATH = os.getenv("DEFAULT_REGEX_PATH", "/app/conf/regex_pattern.json")


def load_regex_from_file():
    try:
        if os.path.exists(DEFAULT_REGEX_PATH):
            with open(DEFAULT_REGEX_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"加载正则表达式文件失败: {e}")
    return {
        "episode_only": [
            r"\[(\d{1,3}(?:\.\d)?)\]",
            r"第(\d{1,3}(?:\.\d)?)集",
            r"Episode\s(\d{1,3}(?:\.\d)?)",
            r"-\s(\d{1,3}(?:\.\d)?)\s-",
            r"(?<![a-zA-Z0-9])E(\d{1,3}(?:\.\d)?)(?!\d)",
            r"-\s(\d{1,3}(?:\.\d)?)(?=\s|\.|\[|$)",
            r"\s+(\d{1,3}(?:\.\d)?)(?=\s\[)",
            r"\s(\d{1,3}(?:\.\d)?)(?=\s\()",
            r"(?<=\.)(\d{2,3})(?=\.[A-Za-z][a-zA-Z])",
        ],
        "season_episode": [
            r"\[S(\d{1,2})E(\d{1,3}(?:\.\d)?)\]",
            r"[Ss](\d{1,2})[Ee](\d{1,3}(?:\.\d)?)",
            r"第(\d{1,2})季.?第(\d{1,3}(?:\.\d)?)集",
            r"Season\s(\d{1,2}).?Episode\s(\d{1,3}(?:\.\d)?)",
            r"\[(\d{1,2})\]\[(\d{1,3}(?:\.\d)?)\]",
            r"-\s(\d{1,2})\s-\s*(\d{1,3}(?:\.\d)?)",
            r"\.(\d{1,2})\.(\d{1,3}(?:\.\d)?)\.",
        ],
    }


DEFAULT_REGEX = load_regex_from_file()


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
            self._local.conn = sqlite3.connect(
                CONFIG_DB_PATH, check_same_thread=False, timeout=30.0  # 添加30秒超时
            )
            self._local.cursor = self._local.conn.cursor()

            # 并发优化
            self._local.cursor.execute("PRAGMA journal_mode=WAL;")
            self._local.cursor.execute("PRAGMA foreign_keys=ON;")
            self._local.cursor.execute("PRAGMA busy_timeout=30000;")  # 30秒忙等待
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
        self._add_column_if_missing("scan_history", "scan_type TEXT")
        self._add_column_if_missing("scan_history", "renamed_audio INTEGER DEFAULT 0")
        self._add_column_if_missing("scan_history", "renamed_picture INTEGER DEFAULT 0")
        self._init_change_record_table()

    def _init_change_record_table(self):
        conn, cursor = self._get_connection()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='change_record';"
        )
        change_record_exists = cursor.fetchone() is not None
        if not change_record_exists:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS change_record (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    original TEXT NOT NULL,
                    new TEXT,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    media_type TEXT,
                    show_name TEXT,
                    season_name TEXT,
                    rollback INTEGER DEFAULT 0,
                    season_dir TEXT NOT NULL
                );
                """
            )

            # 创建索引
            cursor.execute(
                "CREATE INDEX idx_change_record_season_dir ON change_record(season_dir);"
            )
            cursor.execute(
                "CREATE INDEX idx_change_record_timestamp ON change_record(timestamp DESC);"
            )
            cursor.execute(
                "CREATE INDEX idx_change_record_path ON change_record(path);"
            )
            return False
        else:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_change_record_season_dir ON change_record(season_dir);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_change_record_timestamp ON change_record(timestamp DESC);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_change_record_path ON change_record(path);"
            )
            return True

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
            ts = item.get("timestamp") or datetime.now().isoformat()

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

    @retry_db_operation()
    def add_scan_history(self, result: dict):
        conn, cursor = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                """
                INSERT INTO scan_history
                (timestamp, status, scan_type, message, processed, renamed,
                renamed_subtitle, renamed_audio, renamed_picture, deleted_nfo, target, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
                (
                    result.get("timestamp"),
                    result.get("status"),
                    result.get("scan_type", "scan"),
                    result.get("message"),
                    result.get("processed", 0),
                    result.get("renamed", 0),
                    result.get("renamed_subtitle", 0),
                    result.get("renamed_audio", 0),
                    result.get("renamed_picture", 0),
                    result.get("deleted_nfo", 0),
                    result.get("target"),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise sqlite3.OperationalError(f"添加扫描历史失败: {e}")

    def get_scan_history(self, filter_flag: str):
        conn, cursor = self._get_connection()
        if filter_flag == "1":
            cursor.execute(
                "SELECT data FROM scan_history "
                "WHERE deleted_nfo > 0 "
                "OR renamed > 0 "
                "OR renamed_subtitle > 0 "
                "OR renamed_audio > 0 "
                "OR renamed_picture > 0 "
                "ORDER BY timestamp DESC LIMIT 50;"
            )
        else:
            cursor.execute(
                "SELECT data FROM scan_history ORDER BY timestamp DESC LIMIT 50;"
            )
        history = []
        for (row,) in cursor.fetchall():
            try:
                history.append(json.loads(row))
            except json.JSONDecodeError:
                pass
        return history

    def get_scan_history_count(self):
        conn, cursor = self._get_connection()
        cursor.execute("SELECT count(*) FROM scan_history;")
        return cursor.fetchone()[0]

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

    def get_last_effect_scan_result(self):
        conn, cursor = self._get_connection()
        cursor.execute(
            "SELECT data FROM scan_history "
            "WHERE deleted_nfo > 0 "
            "OR renamed > 0 "
            "OR renamed_subtitle > 0 "
            "OR renamed_audio > 0 "
            "OR renamed_picture > 0 "
            "ORDER BY timestamp DESC LIMIT 1;"
        )
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                pass
        return None

    def add_change_records(self, records: List[Dict]):
        """批量添加变更记录到数据库，避免重复"""
        conn, cursor = self._get_connection()
        for record in records:
            path = record.get("path")
            original = record.get("original")
            record_type = record.get("type")
            season_dir = record.get("season_dir")
            status = record.get("status")
            if self.record_exists(path, original, record_type, status):
                updates = {
                    "new": record.get("new"),
                    "status": record.get("status"),
                    "error": record.get("error"),
                    "timestamp": datetime.now().isoformat(),
                    "rollback": record.get("rollback", 0),
                }

                if record.get("status") != "skip":
                    updates = {k: v for k, v in updates.items() if v is not None}
                    if updates:
                        self.update_existing_record(
                            path, original, record_type, **updates
                        )
            else:
                cursor.execute(
                    """
                    INSERT INTO change_record 
                    (path, original, new, type, status, error, timestamp, media_type, 
                    show_name, season_name, rollback, season_dir)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        path,
                        original,
                        record.get("new"),
                        record_type,
                        record.get("status"),
                        record.get("error"),
                        record.get("timestamp"),
                        record.get("media_type"),
                        record.get("show_name"),
                        record.get("season_name"),
                        1 if record.get("rollback") else 0,
                        season_dir,
                    ),
                )
        conn.commit()

    def get_change_records_by_shows(self, limit: int = 200) -> List[Dict]:
        conn, cursor = self._get_connection()
        cursor.execute(
            """
            SELECT 
                media_type,show_name,
                COUNT(*) as record_count,
                MAX(timestamp) as latest_timestamp,
                GROUP_CONCAT(DISTINCT type) as types
            FROM change_record 
            WHERE status = 'success'
            GROUP BY media_type,show_name
            ORDER BY latest_timestamp DESC 
            LIMIT ?
            """,
            (limit,),
        )

        columns = [desc[0] for desc in cursor.description]
        shows = []
        for row in cursor.fetchall():
            show_data = dict(zip(columns, row))
            show_data["types"] = (
                show_data["types"].split(",") if show_data["types"] else []
            )
            shows.append(show_data)

        conn.close()
        return shows

    def get_change_records_by_show(
        self, media_type: str, show_name: str, limit: int = 100
    ) -> List[Dict]:
        conn, cursor = self._get_connection()
        cursor.execute(
            """
            SELECT path, original, new, type, status, error, timestamp,
                media_type, show_name, season_name, rollback, season_dir
            FROM change_record 
            WHERE status = 'success' AND media_type = ? AND show_name = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
            """,
            (media_type, show_name, limit),
        )

        columns = [desc[0] for desc in cursor.description]
        records = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return records

    def record_exists(
        self, path: str, original: str, record_type: str, status: str
    ) -> bool:
        """检查记录是否已存在"""
        conn, cursor = self._get_connection()
        cursor.execute(
            "SELECT COUNT(*) FROM change_record WHERE path = ? AND original = ? AND type = ? AND status = ?",
            (path, original, record_type, status),
        )
        return cursor.fetchone()[0] > 0

    def update_existing_record(
        self, path: str, original: str, record_type: str, **updates
    ):
        """更新现有记录"""
        conn, cursor = self._get_connection()
        update_fields = []
        values = []
        for field, value in updates.items():
            if field in ["new", "status", "error", "timestamp", "rollback"]:
                update_fields.append(f"{field} = ?")
                if field == "rollback":
                    values.append(1 if value else 0)
                else:
                    values.append(value)

        if not update_fields:
            return

        values.extend([path, original, record_type])
        cursor.execute(
            f"UPDATE change_record SET {', '.join(update_fields)} WHERE path = ? AND original = ? AND type = ?",
            values,
        )
        conn.commit()

    def update_change_record_rollback(
        self, path: str, original: str, rollback: bool = True
    ):
        conn, cursor = self._get_connection()
        cursor.execute(
            "UPDATE change_record SET rollback = ? WHERE path = ? AND original = ?",
            (1 if rollback else 0, path, original),
        )
        conn.commit()

    def get_season_change_records(self, season_dir: str) -> List[Dict]:
        conn, cursor = self._get_connection()
        cursor.execute(
            """
            SELECT path, original, new, type, status, error, timestamp, 
                media_type, rollback
            FROM change_record 
            WHERE season_dir = ?
            ORDER BY timestamp DESC
            """,
            (season_dir,),
        )

        records = []
        for row in cursor.fetchall():
            records.append(
                {
                    "path": row[0],
                    "original": row[1],
                    "new": row[2],
                    "type": row[3],
                    "status": row[4],
                    "error": row[5],
                    "timestamp": row[6],
                    "media_type": row[7],
                    "rollback": bool(row[8]),
                }
            )

        return records

    def close(self):
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            finally:
                del self._local.conn
                del self._local.cursor


config_db = ConfigDB()
