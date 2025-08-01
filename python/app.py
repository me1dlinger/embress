"""
/**
 * @author: Meidlinger
 * @date: 2025-06-26
 */
"""

import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING, STATE_PAUSED
from embress_renamer import EmbressRenamer, WhitelistLoader
from email_notifier import EmailNotifier
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
email_notifier = EmailNotifier()

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
        email_notifier.send_notification(result)
    except Exception as exc:
        app.logger.exception("Scheduled scanning failed")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
        }
        config_db.add_scan_history(error_result)
        email_notifier.send_notification(error_result)


def enrich_path_fields(entries: list[dict]) -> list[dict]:
    enriched = []
    for item in entries:
        path_str = item.get("path")
        if not path_str:
            enriched.append(item)
            continue
        p = Path(path_str)
        enriched.append({**item, "file_name": p.name, "file_directory": str(p.parent)})
    return enriched


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
    last_scan = config_db.get_last_scan_result()
    last_effect_scan = config_db.get_last_effect_scan_result()
    if last_scan and "unrenamed_files" in last_scan:
        last_scan["unrenamed_files"] = enrich_path_fields(last_scan["unrenamed_files"])
    if last_effect_scan and "unrenamed_files" in last_effect_scan:
        last_effect_scan["unrenamed_files"] = enrich_path_fields(
            last_effect_scan["unrenamed_files"]
        )
    return jsonify(
        {
            "media_path": MEDIA_PATH,
            "scan_interval": SCAN_INTERVAL,
            "last_scan": last_scan,
            "last_effect_scan": last_effect_scan,
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
    historys = config_db.get_scan_history(filter_flag)
    for history in historys:
        if "unrenamed_files" in history:
            history["unrenamed_files"] = enrich_path_fields(history["unrenamed_files"])
    return jsonify({"history": historys, "total": len(historys)})


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


@app.route("/api/rename-file", methods=["POST"])
def rename_file():
    data = request.get_json(silent=True) or {}

    file_path = data.get("file_path")
    file_name = data.get("file_name")
    new_file_name = data.get("new_file_name")

    if not all([file_path, file_name, new_file_name]):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "缺少必要参数：file_path、file_name 或 new_file_name",
                }
            ),
            200,
        )

    try:
        from pathlib import Path

        original_file = Path(file_path) / file_name
        new_file = Path(file_path) / new_file_name

        if not original_file.exists():
            return (
                jsonify({"success": False, "message": f"文件不存在: {original_file}"}),
                200,
            )

        if new_file.exists():
            return (
                jsonify({"success": False, "message": f"目标文件已存在: {new_file}"}),
                200,
            )

        original_file.rename(new_file)

        return jsonify(
            {
                "success": True,
                "old_path": str(original_file),
                "new_path": str(new_file),
                "message": "重命名成功",
            }
        )

    except Exception as e:
        app.logger.exception("文件重命名失败")
        return jsonify({"success": False, "message": f"文件重命名失败: {str(e)}"}), 500


from flask import Flask, request, jsonify
from pathlib import Path


@app.route("/api/rollback", methods=["POST"])
def rollback_season():
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 200

    full_path = Path(MEDIA_PATH) / sub_path
    if not full_path.exists():
        return jsonify({"success": False, "message": f"路径不存在: {sub_path}"}), 200

    if full_path.is_file():
        app.logger.info(f"Detected file path, start rollback file: {sub_path}")
        rollback_result = renamer.rollback_single_file(sub_path)
    elif full_path.is_dir():
        app.logger.info(f"Start rollback Season: {sub_path}")
        rollback_result = renamer.scan_and_rollback(sub_path)
    else:
        return (
            jsonify({"success": False, "message": f"路径类型不明确: {sub_path}"}),
            200,
        )

    return jsonify(
        {"success": True, "result": rollback_result.get("result", {})}
    ), rollback_result.get("code", 200)


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


@app.route("/api/config/scan-interval", methods=["POST"])
def update_scan_interval():
    """更新扫描间隔配置并重新调度任务"""
    global SCAN_INTERVAL

    data = request.get_json(silent=True) or {}
    new_interval = data.get("scan_interval")

    if not new_interval:
        return jsonify({"success": False, "message": "缺少 scan_interval 参数"}), 200
    try:
        new_interval = int(new_interval)
    except ValueError:
        return jsonify({"success": False, "message": "scan_interval 必须是整数"}), 200

    try:
        # 更新全局变量
        SCAN_INTERVAL = new_interval

        # 获取当前任务
        job = scheduler.get_job("scan_job")

        if job:
            # 更新任务间隔
            scheduler.reschedule_job(
                "scan_job",
                trigger="interval",
                seconds=SCAN_INTERVAL,
                start_date=get_aligned_start(SCAN_INTERVAL),
            )
            app.logger.info(
                f"已更新扫描间隔为 {SCAN_INTERVAL} 秒，下次执行时间: {get_aligned_start(SCAN_INTERVAL)}"
            )
        else:
            # 如果任务不存在，创建新任务
            scheduler.add_job(
                func=scheduled_scan,
                trigger="interval",
                seconds=SCAN_INTERVAL,
                id="scan_job",
                name="文件扫描任务",
                start_date=get_aligned_start(SCAN_INTERVAL),
                replace_existing=True,
            )
            app.logger.info(
                f"已创建新的扫描任务，间隔为 {SCAN_INTERVAL} 秒，首次执行时间: {get_aligned_start(SCAN_INTERVAL)}"
            )

        return jsonify(
            {
                "success": True,
                "scan_interval": SCAN_INTERVAL,
                "next_run_time": get_aligned_start(SCAN_INTERVAL).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "message": f"扫描间隔已更新为 {SCAN_INTERVAL} 秒",
            }
        )
    except Exception as e:
        app.logger.error(f"更新扫描间隔失败: {str(e)}")
        return (
            jsonify({"success": False, "message": f"更新扫描间隔失败: {str(e)}"}),
            200,
        )


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
        enriched = enrich_path_fields(entries)
        return jsonify({"success": True, "whitelist": enriched})
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
                season_absolute_path = Path(record["season_dir"]).resolve()
                record["relative_path"] = str(
                    absolute_path.relative_to(media_root_path)
                )
                record["season_relative_path"] = str(
                    season_absolute_path.relative_to(media_root_path)
                )
            except ValueError:
                media_str = str(media_root_path)
                record["relative_path"] = record["path"].replace(media_str + os.sep, "")
                record["season_relative_path"] = record["season_dir"].replace(
                    media_str + os.sep, ""
                )
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


def get_aligned_start(interval_seconds: int) -> datetime:
    now = datetime.now()
    anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (now - anchor).total_seconds()
    next_interval_index = int(elapsed // interval_seconds) + 1
    aligned_seconds = next_interval_index * interval_seconds
    aligned_time = anchor + timedelta(seconds=aligned_seconds)

    return aligned_time


def clean_old_logs():
    """清理超过5天的日志文件"""
    log_dir = Path(LOGS_PATH)
    if not log_dir.exists():
        return
    cutoff_time = datetime.now() - timedelta(days=5)
    deleted_files = []

    for log_file in log_dir.glob("*.log"):
        # 只处理emby_renamer_和app_开头的日志文件
        if not (
            log_file.name.startswith("emby_renamer_")
            or log_file.name.startswith("app_")
        ):
            continue

        # 获取文件修改时间
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
        if mtime < cutoff_time:
            try:
                log_file.unlink()
                deleted_files.append(log_file.name)
            except Exception as e:
                app.logger.error(
                    f"Failed to delete old log file {log_file.name}: {str(e)}"
                )

    if deleted_files:
        app.logger.info(
            f"Deleted {len(deleted_files)} old log files: {', '.join(deleted_files)}"
        )
    else:
        app.logger.debug("No old log files to delete")


if __name__ == "__main__":
    setup_logging()
    clean_old_logs()
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
        scheduler.add_job(
            func=clean_old_logs,
            trigger="cron",
            hour=1,
            minute=0,
            id="log_cleanup_job",
            name="日志清理任务",
            replace_existing=True,
        )
        scheduler.start()
        app.logger.info(
            f"The scheduled task has been initiated, scan interval: {SCAN_INTERVAL}, first execution time: {get_aligned_start(SCAN_INTERVAL)}"
        )
    port = int(os.getenv("FLASK_PORT", 15000))
    app.run(host="0.0.0.0", port=port, debug=False)
