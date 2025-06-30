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
from logging.handlers import RotatingFileHandler
import datetime
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from embress_renamer import EmbressRenamer, WhitelistLoader
from database import config_db


LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
ACCESS_KEY = os.getenv("ACCESS_KEY", "12345")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 600))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


MAX_RETRIES = 3
RETRY_DELAY = 0.5

app = Flask(__name__)
renamer = EmbressRenamer(MEDIA_PATH)
scheduler = BackgroundScheduler()


def scheduled_scan() -> None:
    try:
        app.logger.info("开始定时扫描 … …")
        result = renamer.scan_and_rename()
        config_db.add_scan_history(result)
        app.logger.info(f"定时扫描完成: {result}")
    except Exception as exc:
        app.logger.exception("定时扫描失败")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.datetime.now().isoformat(),
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


@app.route("/api/status")
def get_status():
    return jsonify(
        {
            "media_path": MEDIA_PATH,
            "scan_interval": SCAN_INTERVAL,
            "last_scan": config_db.get_last_scan_result(),
            "scheduler_running": scheduler.running,
            "total_scans": len(config_db.get_scan_history()),
            "total_whitelist": len(config_db.get_whitelist()),
        }
    )


@app.route("/api/history")
def get_history():
    history = config_db.get_scan_history()
    return jsonify({"history": history, "total": len(history)})


@app.route("/api/manual-scan", methods=["POST"])
def manual_scan():
    try:
        app.logger.info("开始手动扫描 … …")
        result = renamer.scan_and_rename()
        config_db.add_scan_history(result)
        app.logger.info(f"手动扫描完成: {result}")
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("手动扫描失败")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.datetime.now().isoformat(),
        }
        config_db.add_scan_history(error_result)
        return jsonify({"success": False, "result": error_result}), 500


@app.route("/api/scan-directory", methods=["POST"])
def scan_directory():
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 400
    try:
        app.logger.info(f"开始扫描子目录: {sub_path}")
        result = renamer.scan_and_rename(sub_path=sub_path)
        config_db.add_scan_history(result)
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("扫描子目录失败")
        error_result = {
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.datetime.now().isoformat(),
            "target": sub_path,
        }
        config_db.add_scan_history(error_result)
        return jsonify({"success": False, "result": error_result}), 500


@app.route("/api/rollback-season", methods=["POST"])
def rollback_season():
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 400

    season_dir = Path(MEDIA_PATH) / sub_path
    rename_record_path = season_dir / "rename_record.json"
    rollback_record_path = season_dir / "rollback.json"

    if not season_dir.exists():
        return jsonify({"success": False, "message": "Season 目录不存在"}), 404
    if not rename_record_path.exists():
        return jsonify({"success": False, "message": "未找到 rename_record.json"}), 404

    try:
        original_records = json.loads(rename_record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        app.logger.exception("读取变更记录失败")
        return jsonify({"success": False, "message": f"读取记录失败: {exc}"}), 500

    rollback_results = []
    rolled_back_cnt = 0

    for rec in original_records:
        if (
            rec.get("type") != "rename"
            or rec.get("status") != "success"
            or rec.get("rollback") is True
        ):
            continue
        cur_path = Path(rec["path"])
        original_name = rec["original"]
        if not cur_path.exists():
            rollback_results.append(
                {
                    "type": "rollback",
                    "original": rec["new"],
                    "new": original_name,
                    "status": "failed",
                    "error": "文件不存在",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "path": rec["path"],
                }
            )
            continue

        try:
            changes = renamer._rename_file_and_subtitles(cur_path, original_name)
            if renamer._count_success_renames(changes):
                rolled_back_cnt += 1
                rollback_result = {
                    "type": "rollback",
                    "original": rec["new"],
                    "new": original_name,
                    "status": "rolled_back",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "path": str((cur_path.parent / original_name).absolute()),
                }
                rollback_results.append(rollback_result)
                rec["rollback"] = True
            else:
                rollback_results.append(
                    {
                        "type": "rollback",
                        "original": rec["new"],
                        "new": original_name,
                        "status": "failed",
                        "error": "重命名失败",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "path": rec["path"],
                    }
                )
        except Exception as exc:
            app.logger.exception("回滚出错")
            rollback_results.append(
                {
                    "type": "rollback",
                    "original": rec["new"],
                    "new": original_name,
                    "status": "failed",
                    "error": str(exc),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "path": rec["path"],
                }
            )
    try:
        rename_record_path.write_text(
            json.dumps(original_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        app.logger.exception("更新 rename_record.json 标记失败")
    if rollback_results:
        existing = []
        if rollback_record_path.exists():
            try:
                existing = json.loads(rollback_record_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        try:
            all_records = existing + rollback_results
            rollback_record_path.write_text(
                json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            app.logger.exception("写入 rollback.json 失败")

    return jsonify(
        {"success": True, "rolled_back": rolled_back_cnt, "results": rollback_results}
    )


@app.route("/api/regex-patterns", methods=["GET"])
def get_regex_patterns():
    try:
        patterns = config_db.get_regex_patterns()
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
        config_db.update_regex_patterns(payload)
        return jsonify({"success": True, "message": "正则配置已更新"})
    except Exception as exc:
        app.logger.exception("写入正则配置失败")
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
            app.logger.exception("批量写入白名单失败")
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
        app.logger.exception("写入白名单失败")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/whitelist", methods=["GET"])
def get_whitelist():
    try:
        entries = config_db.get_whitelist()
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
        removed = config_db.remove_from_whitelist(file_path)
        message = "移出白名单成功" if removed else "不在白名单中"
        WhitelistLoader.force_reload()
        return jsonify({"success": True, "removed": removed, "message": message})
    except Exception as exc:
        app.logger.exception("写入白名单失败")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/change-records")
def get_change_records():
    records = []
    media_path = Path(MEDIA_PATH)

    if not media_path.exists():
        return jsonify({"records": [], "total": 0})

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
                    season_records = json.loads(record_file.read_text(encoding="utf-8"))
                    for rec in season_records:
                        if (
                            rec.get("status") == "success"
                            and rec.get("type") != "nfo_delete"
                        ):
                            rec.update(
                                media_type=media_type_dir.name,
                                show=show_dir.name,
                                season=season_dir.name,
                                rollback=rec.get("rollback", False),
                            )
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
                "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
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

    LOGS_PATH.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_PATH / f"app_{datetime.datetime.now():%Y%m%d}.log"

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8"  # 10 MB
    )
    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    file_handler.setFormatter(logging.Formatter(fmt))

    # 配置 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # 避免重复添加
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        root_logger.addHandler(file_handler)


if __name__ == "__main__":
    setup_logging()
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
