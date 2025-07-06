"""
/**
 * @author: Meidlinger
 * @date: 2025-06-26
 */
"""

import os
import json
import logging
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING, STATE_PAUSED
from embress_renamer import EmbressRenamer, WhitelistLoader
from database import config_db
from datetime import datetime, timedelta
from logging_utils import DailyFileHandler

LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
ACCESS_KEY = os.getenv("ACCESS_KEY", "12345")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 600))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


MAX_RETRIES = 3
RETRY_DELAY = 0.5

app = Flask(__name__)
app.logger.propagate = False
renamer = EmbressRenamer(MEDIA_PATH)
scheduler = BackgroundScheduler()

WHITELIST_ENDPOINTS = {
    "static",
    "index",
    "authenticate",
}


def _unauthorized():
    """统一401响应"""
    return jsonify({"success": False, "message": "未授权或密钥无效"}), 401


@app.before_request
def global_access_key_guard():
    """所有请求在真正进入视图函数前先经过这里"""
    # 2. 跳过豁免端点
    if request.endpoint in WHITELIST_ENDPOINTS:
        return
    key = (
        request.headers.get("X-Access-Key")
        or request.args.get("access_key")
        or (request.get_json(silent=True) or {}).get("access_key")
    )
    if key != ACCESS_KEY:
        app.logger.warning(
            "Unauthorized access: endpoint=%s ip=%s",
            request.endpoint,
            request.remote_addr,
        )
        return _unauthorized()


def scheduled_scan() -> None:
    try:
        app.logger.info("Start scheduled scanning … …")
        result = renamer.scan_and_rename()
        config_db.add_scan_history(result)
        app.logger.info(f"Scheduled scanning completed: {result}")
    except Exception as exc:
        app.logger.exception("Scheduled scanning failed")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
        }
        config_db.add_scan_history(error_result)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth", methods=["POST"])
def authenticate():
    data = request.get_json(silent=True) or {}
    if data.get("access_key") == ACCESS_KEY:
        return jsonify({"success": True, "message": "验证成功"})
    return jsonify({"success": False, "message": "访问密钥错误"})


from apscheduler.schedulers.base import STATE_RUNNING, STATE_PAUSED, STATE_STOPPED


@app.route("/api/status")
def get_status():
    job = scheduler.get_job(job_id="scan_job")
    scheduler_state = scheduler.state
    next_run_time = None

    if scheduler_state == STATE_RUNNING and job and job.next_run_time:
        next_run_time = job.next_run_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    elif scheduler_state == STATE_PAUSED:
        next_run_time = "已暂停"
    elif scheduler_state == STATE_STOPPED:
        next_run_time = "未启动"
    else:
        next_run_time = "未知"

    return jsonify(
        {
            "media_path": MEDIA_PATH,
            "scan_interval": SCAN_INTERVAL,
            "last_scan": config_db.get_last_scan_result(),
            "scheduler_running": scheduler_state,
            "total_scans": config_db.get_scan_history_count(),
            "total_whitelist": len(config_db.get_whitelist()),
            "next_scan_time": next_run_time,
            "scheduler_state_name": {0: "已停止", 1: "运行中", 2: "已暂停"}.get(
                scheduler_state, f"UNKNOWN({scheduler_state})"
            ),
        }
    )


@app.route("/api/scheduler/toggle", methods=["POST"])
def toggle_scheduler():
    try:
        state = scheduler.state

        if state == STATE_RUNNING:
            scheduler.pause()
            msg = "调度器已暂停"
        elif state == STATE_PAUSED:
            scheduler.resume()
            msg = "调度器已恢复"
        else:
            scheduler.start()
            msg = "调度器已启动"

        app.logger.info(msg)
        return jsonify(
            {
                "success": True,
                "running": scheduler.running,
                "state": scheduler.state,
                "message": msg,
            }
        )
    except Exception as exc:
        app.logger.exception("切换调度器状态失败")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/history/<filter_flag>")
def get_history(filter_flag: str):
    history = config_db.get_scan_history(filter_flag)
    return jsonify({"history": history, "total": len(history)})


@app.route("/api/manual-scan", methods=["POST"])
def manual_scan():
    try:
        app.logger.info("Start manual scanning … …")
        result = renamer.scan_and_rename()
        config_db.add_scan_history(result)
        app.logger.info(f"Manual scanning completed: {result}")
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("Manual scanning failed")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
        }
        config_db.add_scan_history(error_result)
        return jsonify({"success": False, "result": error_result}), 500


@app.route("/api/scan-directory", methods=["POST"])
def scan_directory():
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 200
    try:
        app.logger.info(f"Start scan directory: {sub_path}")
        result = renamer.scan_and_rename(sub_path=sub_path)
        app.logger.info(f"Directory scan completed: {result}")
        if result.get("status") == "error":
            return jsonify({"success": False, "message": result.get("message")}), 200
        config_db.add_scan_history(result)
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("Directory scan failed")
        return jsonify({"success": False, "message": str(exc)}), 200


@app.route("/api/rollback-season", methods=["POST"])
def rollback_season():
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 400
    app.logger.info(f"Start rollback Season: {sub_path}")
    rollback_result = renamer.scan_and_rollback(sub_path)
    return jsonify(rollback_result.get("result", {})), rollback_result.get("code", 200)


@app.route("/api/regex-patterns", methods=["GET"])
def get_regex_patterns():
    try:
        patterns = config_db.get_regex_patterns()
        return jsonify({"success": True, "patterns": patterns})
    except Exception as exc:
        app.logger.exception("Reading regex configuration failed")
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
        config_db.update_regex_patterns(payload)
        return jsonify({"success": True, "message": "正则配置已更新"})
    except Exception as exc:
        app.logger.exception("Writing regex configuration failed")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/whitelist", methods=["POST"])
def add_to_whitelist():
    data = request.get_json(silent=True) or {}
    # 批量优先
    if "items" in data:
        try:
            summary = config_db.add_whitelist_items(data["items"])
            return jsonify({"success": summary["failed"] == [], **summary})
        except Exception as exc:
            app.logger.exception("Batch writing to whitelist failed")
            return jsonify({"success": False, "message": str(exc)}), 500
    # 兼容单条
    file_path = data.get("file_path")
    if not file_path:
        return jsonify({"success": False, "message": "缺少 file_path 或 items"}), 400
    try:
        inserted = config_db.add_to_whitelist(file_path)
        WhitelistLoader.force_reload()
        return jsonify(
            {
                "success": True,
                "inserted": inserted,
                "message": "加入白名单成功" if inserted else "已在白名单中",
            }
        )
    except Exception as exc:
        app.logger.exception("Writing to whitelist failed")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/whitelist", methods=["GET"])
def get_whitelist():
    try:
        entries = config_db.get_whitelist()
        return jsonify({"success": True, "whitelist": entries})
    except Exception as exc:
        app.logger.exception("Reading from whitelist failed")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/whitelist", methods=["DELETE"])
def delete_from_whitelist():
    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path")
    if not file_path:
        return jsonify({"success": False, "message": "缺少 file_path"}), 400
    try:
        removed = config_db.remove_from_whitelist(file_path)
        message = "移出白名单成功" if removed else "不在白名单中"
        WhitelistLoader.force_reload()
        return jsonify({"success": True, "removed": removed, "message": message})
    except Exception as exc:
        app.logger.exception("Writing to whitelist failed")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/change-records")
def get_change_records():
    try:
        # 获取分组的节目列表
        shows = config_db.get_change_records_by_shows(limit=200)
        return jsonify({"shows": shows, "total": len(shows)})
    except Exception as e:
        app.logger.error(f"Failed to get change records: {e}")
        return jsonify({"shows": [], "total": 0, "error": str(e)}), 500


@app.route("/api/change-records/show", methods=["POST"])
def get_change_records_by_show():
    data = request.get_json(silent=True) or {}
    media_type = data.get("media_type")
    show_name = data.get("show_name")
    if not media_type or not show_name:
        return jsonify({"success": False, "message": "缺少参数"}), 400
    try:
        records = config_db.get_change_records_by_show(media_type, show_name, limit=200)
        media_root_path = Path(MEDIA_PATH).resolve()
        for record in records:
            try:
                absolute_path = Path(record["path"]).resolve()
                record["relative_path"] = str(
                    absolute_path.relative_to(media_root_path)
                )
            except ValueError:
                media_str = str(media_root_path)
                record["relative_path"] = record["path"].replace(media_str + os.sep, "")
        return jsonify({"records": records, "total": len(records)})
    except Exception as e:
        app.logger.error(f"Failed to get change records for show {show_name}: {e}")
        return jsonify({"records": [], "total": 0, "error": str(e)}), 500


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
        app.logger.exception("Failed to read log")
        return jsonify({"error": f"读取日志失败: {exc}"}), 500


def setup_logging() -> None:
    LOGS_PATH.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    formatter = logging.Formatter(fmt)

    file_handler = DailyFileHandler(log_dir=LOGS_PATH, base_name="app")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    if not any(isinstance(h, DailyFileHandler) for h in root_logger.handlers):
        root_logger.addHandler(file_handler)
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(console_handler)
    app.logger.propagate = True
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    werkzeug_logger.handlers.clear()
    werkzeug_logger.addHandler(file_handler)
    werkzeug_logger.addHandler(console_handler)
    werkzeug_logger.propagate = False


def init_change_record():
    try:
        if config_db._init_change_record_table():
            app.logger.info(
                "The change_record table already exists, skip initialization"
            )
        else:
            app.logger.info(
                "The change_record table does not exist. Create a table and migrate historical data"
            )

            media_path = Path(MEDIA_PATH)
            if not media_path.exists():
                app.logger.warning(f"The media path not found: {MEDIA_PATH}")
                return
            all_records = []
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
                            season_records = json.loads(
                                record_file.read_text(encoding="utf-8")
                            )
                            for rec in season_records:
                                if (
                                    rec.get("show_name") == None
                                    or rec.get("season_name") is None
                                    or rec.get("media_type") is None
                                ):
                                    rec["show_name"] = show_dir.name
                                    rec["season_name"] = season_dir.name
                                    rec["media_type"] = media_type_dir.name
                                    rec["season_dir"] = str(season_dir.absolute())
                            all_records.extend(season_records)
                            app.logger.info(
                                f"Read {len(season_records)} records from  {record_file}"
                            )
                        except Exception as e:
                            app.logger.error(
                                f"Failed to read change record: {record_file}: {e}"
                            )
            if all_records:
                app.logger.info(
                    f"Read {len(all_records)} records to the change_decord table"
                )
                config_db.add_change_records(all_records)
            else:
                app.logger.info("No readable records found")
            app.logger.info("change_record initialization successful")
    except Exception as exc:
        app.logger.error(f"change_record initialization failed: {exc}")
        raise RuntimeError("Unable to initialize change_record") from exc


def get_aligned_start(interval_seconds: int) -> datetime:
    now = datetime.now()
    anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (now - anchor).total_seconds()
    next_interval_index = int(elapsed // interval_seconds) + 1
    aligned_seconds = next_interval_index * interval_seconds
    aligned_time = anchor + timedelta(seconds=aligned_seconds)

    return aligned_time


if __name__ == "__main__":
    setup_logging()

    init_change_record()
    if not scheduler.running:
        scheduler.add_job(
            func=scheduled_scan,
            trigger="interval",
            seconds=600,
            id="scan_job",
            name="文件扫描任务",
            start_date=get_aligned_start(SCAN_INTERVAL),
            replace_existing=True,
        )
        scheduler.start()
        app.logger.info(
            f"The scheduled task has been initiated, scan interval: {SCAN_INTERVAL}, first execution time: {get_aligned_start(SCAN_INTERVAL)}"
        )
    port = int(os.getenv("FLASK_PORT", 15000))
    app.run(host="0.0.0.0", port=port, debug=False)
