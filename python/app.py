"""
/**
 * @author: Meidlinger
 * @date: 2025-06-26
 */
"""

import os
import json
import logging
import tempfile
from pathlib import Path
import shutil
import time
from datetime import datetime
from threading import Lock
from typing import Set, List

from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

from embress_renamer import EmbressRenamer

app = Flask(__name__)

LOGS_PATH = os.getenv("LOG_PATH", "/app/python/logs")
MEDIA_PATH = os.getenv("MEDIA_PATH", "/app/media")
REGEX_PATH = os.getenv("REGEX_PATH", "regex_patterns.json")
WHITELIST_PATH = os.getenv("WHITELIST_PATH", "/app/python/conf/whitelist.json")
ACCESS_KEY = os.getenv("ACCESS_KEY", "12345")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 3600))
HISTORY_FILE = Path(LOGS_PATH) / "scan_history.log"

MAX_RETRIES = 3
RETRY_DELAY = 0.5


renamer = EmbressRenamer(MEDIA_PATH)
scheduler = BackgroundScheduler()

last_scan_result = None
scan_history: List[dict] = []

history_lock = Lock()
regex_lock = Lock()
whitelist_lock = Lock() 

def load_history() -> None:
    global scan_history, last_scan_result
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        scan_history = payload.get("history", [])
        last_scan_result = payload.get("last_scan")


def persist_history() -> None:
    with history_lock:
        with HISTORY_FILE.open("w", encoding="utf-8") as f:
            json.dump(
                {"history": scan_history, "last_scan": last_scan_result},
                f,
                ensure_ascii=False,
                indent=2,
            )



def load_regex_patterns() -> dict:
    path = Path(REGEX_PATH)
    if not path.exists():
        return {}
    with regex_lock, path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_regex_patterns(patterns: dict) -> None:
    path = Path(REGEX_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(MAX_RETRIES):
        try:
            # 创建带.json后缀的临时文件
            with tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                dir=str(path.parent),
                encoding="utf-8",
                suffix=".json",
            ) as tmp:
                json.dump(patterns, tmp, ensure_ascii=False, indent=2)
                tmp_name = tmp.name

            shutil.copy(tmp_name, str(path))
            os.unlink(tmp_name)  # 删除临时文件
            return
        except (OSError, IOError) as e:
            app.logger.warning(
                f"保存正则配置失败 (尝试 {attempt+1}/{MAX_RETRIES}): {str(e)}"
            )
            time.sleep(RETRY_DELAY)

    app.logger.error(f"保存正则配置失败，超过最大重试次数")


def _read_whitelist() -> Set[str]:
    path = Path(WHITELIST_PATH)
    if not path.exists():
        return set()
    with whitelist_lock, path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return set(map(str, data))
            return set()
        except json.JSONDecodeError:
            return set()


def _write_whitelist(entries: Set[str]) -> None:
    path = Path(WHITELIST_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with whitelist_lock, tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(path.parent), encoding="utf-8"
    ) as tmp:
        json.dump(sorted(entries), tmp, ensure_ascii=False, indent=2)
        tmp_name = tmp.name
    os.replace(tmp_name, path)



def scheduled_scan() -> None:
    global last_scan_result, scan_history
    try:
        app.logger.info("开始定时扫描 … …")
        result = renamer.scan_and_rename()
        last_scan_result = result
        scan_history.append(result)
        scan_history = scan_history[-50:]
        persist_history()
        app.logger.info(f"定时扫描完成: {result}")
    except Exception as exc:
        app.logger.exception("定时扫描失败")
        last_scan_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
        }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth", methods=["POST"])
def authenticate():
    data = request.get_json(silent=True) or {}
    if data.get("access_key") == ACCESS_KEY:
        return jsonify({"success": True, "message": "验证成功"})
    return jsonify({"success": False, "message": "访问密钥错误"})


@app.route("/api/status")
def get_status():
    return jsonify(
        {
            "media_path": MEDIA_PATH,
            "scan_interval": SCAN_INTERVAL,
            "last_scan": last_scan_result,
            "scheduler_running": scheduler.running,
            "total_scans": len(scan_history),
            "total_whitelist": len(_read_whitelist()),
        }
    )


@app.route("/api/history")
def get_history():
    sorted_history = sorted(
        scan_history, key=lambda x: x.get("timestamp", ""), reverse=True
    )
    return jsonify({"history": sorted_history, "total": len(scan_history)})


@app.route("/api/manual-scan", methods=["POST"])
def manual_scan():
    global last_scan_result, scan_history
    try:
        app.logger.info("开始手动扫描 … …")
        result = renamer.scan_and_rename()
        last_scan_result = result
        scan_history.append(result)
        scan_history = scan_history[-50:]
        persist_history()
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("手动扫描失败")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
        }
        last_scan_result = error_result
        return jsonify({"success": False, "result": error_result}), 500


@app.route("/api/scan-directory", methods=["POST"])
def scan_directory():
    global last_scan_result, scan_history
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 400
    try:
        app.logger.info(f"开始扫描子目录: {sub_path}")
        result = renamer.scan_and_rename(sub_path=sub_path)
        last_scan_result = result
        scan_history.append(result)
        scan_history = scan_history[-50:]
        persist_history()
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("扫描子目录失败")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
            "target": sub_path,
        }
        last_scan_result = error_result
        return jsonify({"success": False, "result": error_result}), 500



@app.route("/api/regex-patterns", methods=["GET"])
def get_regex_patterns():
    try:
        patterns = load_regex_patterns()
        return jsonify({"success": True, "patterns": patterns})
    except Exception as exc:
        app.logger.exception("读取正则配置失败")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/regex-patterns", methods=["POST"])
def update_regex_patterns():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "message": "请求体必须为 JSON 对象"}), 400
    if not {"season_episode", "episode_only"}.issubset(payload.keys()):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "缺少必要字段: season_episode / episode_only",
                }
            ),
            400,
        )
    try:
        save_regex_patterns(payload)
        return jsonify({"success": True, "message": "正则配置已更新"})
    except Exception as exc:
        app.logger.exception("写入正则配置失败")
        return jsonify({"success": False, "message": str(exc)}), 500



@app.route("/api/whitelist", methods=["POST"])
def add_to_whitelist():
    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path")
    if not file_path:
        return jsonify({"success": False, "message": "缺少 file_path"}), 400
    try:
        entries = _read_whitelist()
        if file_path in entries:
            return jsonify(
                {"success": True, "inserted": False, "message": "已在白名单中"}
            )
        entries.add(file_path)
        _write_whitelist(entries)
        return jsonify({"success": True, "inserted": True, "message": "加入白名单成功"})
    except Exception as exc:
        app.logger.exception("写入白名单失败")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/whitelist", methods=["GET"])
def get_whitelist():
    try:
        entries = sorted(_read_whitelist())
        return jsonify({"success": True, "whitelist": entries})
    except Exception as exc:
        app.logger.exception("读取白名单失败")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/whitelist", methods=["DELETE"])
def delete_from_whitelist():
    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path")
    if not file_path:
        return jsonify({"success": False, "message": "缺少 file_path"}), 400
    try:
        entries = _read_whitelist()
        if file_path not in entries:
            return jsonify(
                {"success": True, "removed": False, "message": "不在白名单中"}
            )
        entries.remove(file_path)
        _write_whitelist(entries)
        return jsonify({"success": True, "removed": True, "message": "移出白名单成功"})
    except Exception as exc:
        app.logger.exception("写入白名单失败")
        return jsonify({"success": False, "message": str(exc)}), 500

@app.route("/api/change-records")
def get_change_records():
    """获取所有变更记录（排除 skip）"""
    records = []
    media_path = Path(MEDIA_PATH)
    if not media_path.exists():
        return jsonify({"records": []})

    for media_type_dir in media_path.iterdir():
        if not media_type_dir.is_dir():
            continue
        for show_dir in media_type_dir.iterdir():
            if not show_dir.is_dir():
                continue
            for season_dir in show_dir.iterdir():
                if not season_dir.is_dir():
                    continue
                record_file = season_dir / "rename_record.json"
                if not record_file.exists():
                    continue

                try:
                    with open(record_file, "r", encoding="utf-8") as f:
                        season_records = json.load(f)
                    for rec in season_records:
                        if rec.get("status") == "skip":
                            continue
                        rec["media_type"] = media_type_dir.name
                        rec["show"] = show_dir.name
                        rec["season"] = season_dir.name
                        records.append(rec)
                except Exception as e:
                    app.logger.error(f"读取变更记录失败 {record_file}: {e}")

    records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return jsonify({"records": records[:200], "total": len(records)})


@app.route("/api/logs")
def get_logs():
    log_dir = Path(LOGS_PATH)
    if not log_dir.exists():
        return jsonify({"logs": []})
    logs = []
    for log_file in sorted(log_dir.glob("*.log"), reverse=True):
        stat = log_file.stat()
        logs.append(
            {
                "name": log_file.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return jsonify({"logs": logs})


@app.route("/api/logs/<filename>")
def get_log_content(filename: str):
    log_dir = Path(LOGS_PATH)
    log_file = log_dir / filename
    if not log_file.exists() or not filename.endswith(".log"):
        return jsonify({"error": "日志文件不存在"}), 404
    try:
        with log_file.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        content = "".join(lines[-1000:])
        return jsonify(
            {"filename": filename, "content": content, "total_lines": len(lines)}
        )
    except Exception as exc:
        app.logger.exception("读取日志失败")
        return jsonify({"error": f"读取日志失败: {exc}"}), 500



def setup_logging() -> None:
    if app.debug:
        return
    log_dir = Path(LOGS_PATH)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)


if __name__ == "__main__":
    setup_logging()
    load_history()
    if not scheduler.running:
        scheduler.add_job(
            func=scheduled_scan,
            trigger="interval",
            seconds=SCAN_INTERVAL,
            id="scan_job",
            name="文件扫描任务",
            replace_existing=True,
        )
        scheduler.start()
        app.logger.info(f"定时任务已启动，扫描间隔: {SCAN_INTERVAL} 秒")
    port = int(os.getenv("FLASK_PORT", 15000))
    app.run(host="0.0.0.0", port=port, debug=False)
