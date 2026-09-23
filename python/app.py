"""
/**
 * @author: Meidlinger
 * @date: 2025-06-26
 */
"""

import hmac
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.schedulers.base import (  # type: ignore
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_STOPPED,
)
from ai_organizer import (
    auto_organizer,
    organize_enabled,
    organize_interval,
    organize_provider_id,
    reset_organize_attempts,
    set_organize_enabled,
    set_organize_interval,
    set_organize_provider_id,
)
from ai_renamer import AI_BASE_URL, AI_MODEL, ai_renamer, normalize_binding_path
from crypto_utils import decrypt, encrypt, mask
from database import config_db
from email_notifier import EmailNotifier
from embress_renamer import (  # type: ignore
    EmbressRenamer,
    OperationBusy,
    RegexLoader,
    WhitelistLoader,
)
from flask import Flask, jsonify, render_template, request  # type: ignore
from logging_utils import DailyFileHandler

LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
ACCESS_KEY = os.getenv("ACCESS_KEY", "12345")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 600))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

MAX_RETRIES = 3
RETRY_DELAY = 0.5

MEDIA_ROOT = Path(MEDIA_PATH).resolve()


def _safe_media_path(raw: str) -> Path:
    """把用户输入的子路径限制在媒体根目录内，阻止目录穿越"""
    target = (MEDIA_ROOT / (raw or "")).resolve()
    if target != MEDIA_ROOT and MEDIA_ROOT not in target.parents:
        raise ValueError("路径越界")
    return target


def _safe_child(name: str) -> str:
    """校验纯文件名：不含目录分隔符，且不是 . 或 .."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("非法文件名")
    if os.path.basename(name) != name:
        raise ValueError("非法文件名")
    return name

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
    if not hmac.compare_digest(str(key or ""), ACCESS_KEY):
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


def _job_next_run_time(job_id: str):
    """返回任务下次执行时间字符串，未运行返回 None"""
    job = scheduler.get_job(job_id)
    if not job or job.next_run_time is None:
        return None
    return job.next_run_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def scheduled_organize() -> None:
    """定时智能整理：把散落的剧集文件归类到规范目录"""
    if not organize_enabled():
        return
    try:
        app.logger.info("Start scheduled auto organizing … …")
        result = auto_organizer.run()
        app.logger.info("Auto organizing completed: %s", result.get("status"))
        # 无候选文件时不留痕，避免污染扫描历史
        if result.get("processed") or result.get("status") == "error":
            config_db.add_scan_history(result)
        if result.get("status") == "completed" and result.get("moved"):
            email_notifier.send_notification(result)
    except Exception as exc:
        app.logger.exception("Scheduled auto organizing failed")
        error_result = {
            "status": "error",
            "scan_type": "organize",
            "message": str(exc),
            "timestamp": datetime.now().isoformat(),
            "target": "AUTO",
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


@app.route("/api/status")
def get_status():
    job = scheduler.get_job("scan_job")
    if not job:
        scheduler_state = STATE_STOPPED
        next_run_time = None
    elif job.next_run_time is None:
        scheduler_state = STATE_PAUSED
        next_run_time = "已暂停"
    else:
        scheduler_state = STATE_RUNNING
        next_run_time = job.next_run_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")

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
            "scheduler_state_name": {
                STATE_STOPPED: "已停止",
                STATE_RUNNING: "运行中",
                STATE_PAUSED: "已暂停",
            }.get(scheduler_state, f"UNKNOWN({scheduler_state})"),
            "ai_enabled": ai_renamer.is_configured(),
            "organize_enabled": organize_enabled(),
            "organize_interval": organize_interval(),
            "organize_provider_id": organize_provider_id(),
            "organize_next_run_time": _job_next_run_time("organize_job"),
        }
    )


@app.route("/api/scheduler/toggle", methods=["POST"])
def toggle_scheduler():
    try:
        job = scheduler.get_job("scan_job")
        if not job:
            return jsonify({"success": False, "message": "扫描任务不存在"}), 404

        if job.next_run_time is None:
            job.resume()
            msg = "扫描任务已启动"
            running = True
        else:
            job.pause()
            msg = "扫描任务已停止"
            running = False

        app.logger.info(msg)
        return jsonify(
            {
                "success": True,
                "scan_job_running": running,
                "message": msg,
            }
        )
    except Exception as exc:
        app.logger.exception("切换扫描任务状态失败")
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
    except OperationBusy as exc:
        return jsonify({"success": False, "message": str(exc)}), 409
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
        _safe_media_path(sub_path)
    except ValueError:
        return jsonify({"success": False, "message": "路径越界"}), 200
    try:
        app.logger.info(f"Start scan directory: {sub_path}")
        result = renamer.scan_and_rename(sub_path=sub_path)
        app.logger.info(f"Directory scan completed: {result}")
        if result.get("status") == "error":
            return jsonify({"success": False, "message": result.get("message")}), 200
        config_db.add_scan_history(result)
        return jsonify({"success": True, "result": result})
    except OperationBusy as exc:
        return jsonify({"success": False, "message": str(exc)}), 409
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
        parent = _safe_media_path(file_path)
        file_name = _safe_child(file_name)
        new_file_name = _safe_child(new_file_name)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 200

    try:
        original_file = parent / file_name
        new_file = parent / new_file_name

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


@app.route("/api/rollback", methods=["POST"])
def rollback_season():
    data = request.get_json(silent=True) or {}
    sub_path = data.get("sub_path")
    if not sub_path:
        return jsonify({"success": False, "message": "缺少 sub_path"}), 200

    try:
        full_path = _safe_media_path(sub_path)
    except ValueError:
        return jsonify({"success": False, "message": "路径越界"}), 200
    if not full_path.exists():
        return jsonify({"success": False, "message": f"路径不存在: {sub_path}"}), 200

    try:
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
    except OperationBusy as exc:
        return jsonify({"success": False, "message": str(exc)}), 409

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
        RegexLoader.force_reload()
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


def _provider_public(provider) -> dict:
    return {
        "id": provider["id"],
        "name": provider["name"],
        "base_url": provider["base_url"],
        "model": provider["model"],
        "enabled": provider["enabled"],
        "is_default": provider["is_default"],
        "has_key": bool(provider.get("api_key")),
        "key_hint": mask(provider.get("api_key") or ""),
        "timestamp": provider.get("timestamp"),
    }


@app.route("/api/ai/status")
def ai_status():
    default = config_db.get_default_ai_provider()
    return jsonify(
        {
            "success": True,
            "configured": ai_renamer.is_configured(),
            "env_ready": bool(AI_BASE_URL),
            "base_url": AI_BASE_URL,
            "model": AI_MODEL,
            "default_provider": _provider_public(default) if default else None,
            "provider_count": len(config_db.get_ai_providers()),
            "bindings": len(config_db.get_ai_bindings()),
        }
    )


@app.route("/api/ai/providers", methods=["GET"])
def get_ai_providers():
    return jsonify(
        {
            "success": True,
            "providers": [_provider_public(p) for p in config_db.get_ai_providers()],
        }
    )


@app.route("/api/ai/providers", methods=["POST"])
def save_ai_provider():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url:
        return jsonify({"success": False, "message": "名称与 Base URL 必填"}), 200
    model = (data.get("model") or "").strip() or None
    enabled = bool(data.get("enabled", True))
    is_default = bool(data.get("is_default", False))
    api_key = data.get("api_key")
    provider_id = data.get("id")

    try:
        if provider_id:
            fields = {
                "name": name,
                "base_url": base_url,
                "model": model,
                "enabled": enabled,
                "is_default": is_default,
            }
            if api_key is not None and str(api_key).strip() != "":
                fields["api_key"] = encrypt(str(api_key).strip())
            config_db.update_ai_provider(int(provider_id), **fields)
            return jsonify({"success": True, "id": int(provider_id), "message": "已更新"})

        encrypted = encrypt(str(api_key).strip()) if api_key else None
        new_id = config_db.add_ai_provider(
            name, base_url, encrypted, model, enabled, is_default
        )
        return jsonify({"success": True, "id": new_id, "message": "已添加"})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 200


@app.route("/api/ai/providers", methods=["DELETE"])
def delete_ai_provider():
    data = request.get_json(silent=True) or {}
    provider_id = data.get("id")
    if not provider_id:
        return jsonify({"success": False, "message": "缺少 id"}), 200
    removed = config_db.remove_ai_provider(int(provider_id))
    return jsonify(
        {
            "success": True,
            "removed": removed,
            "message": "已删除" if removed else "未找到该供应商",
        }
    )


@app.route("/api/ai/providers/test", methods=["POST"])
def test_ai_provider():
    data = request.get_json(silent=True) or {}
    provider_id = data.get("id")
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    api_key = data.get("api_key")
    model = (data.get("model") or "").strip() or None

    if provider_id and not base_url:
        provider = config_db.get_ai_provider(int(provider_id))
        if not provider:
            return jsonify({"success": False, "message": "供应商不存在"}), 200
        base_url = provider["base_url"]
        model = model or provider.get("model")
        api_key = decrypt(provider.get("api_key") or "")
    elif provider_id and (api_key is None or str(api_key).strip() == ""):
        provider = config_db.get_ai_provider(int(provider_id))
        if provider:
            api_key = decrypt(provider.get("api_key") or "")

    if not base_url:
        return jsonify({"success": False, "message": "缺少 Base URL"}), 200
    try:
        ok, message = ai_renamer.test(base_url, api_key or "", model)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 200
    return jsonify({"success": bool(ok), "message": message}), 200


@app.route("/api/ai/bindings", methods=["GET"])
def get_ai_bindings():
    return jsonify({"success": True, "bindings": config_db.get_ai_bindings()})


@app.route("/api/ai/bindings", methods=["POST"])
def add_ai_binding():
    data = request.get_json(silent=True) or {}
    try:
        path = normalize_binding_path(data.get("path"))
    except ValueError:
        return jsonify({"success": False, "message": "路径不合法"}), 200
    if not path:
        return jsonify({"success": False, "message": "缺少 path"}), 200
    try:
        target = _safe_media_path(path)
    except ValueError:
        return jsonify({"success": False, "message": "路径越界"}), 200
    if not target.is_dir():
        return jsonify({"success": False, "message": "目录不存在于媒体库中"}), 200

    model = (data.get("model") or "").strip() or None
    prompt = (data.get("prompt") or "").strip() or None
    provider_id = data.get("provider_id")
    provider_id = int(provider_id) if provider_id else None
    if provider_id and not config_db.get_ai_provider(provider_id):
        return jsonify({"success": False, "message": "供应商不存在"}), 200
    config_db.add_ai_binding(path, model, prompt, provider_id)
    return jsonify({"success": True, "message": "AI 绑定已保存"})


@app.route("/api/ai/bindings", methods=["DELETE"])
def delete_ai_binding():
    data = request.get_json(silent=True) or {}
    try:
        path = normalize_binding_path(data.get("path"))
    except ValueError:
        return jsonify({"success": False, "message": "路径不合法"}), 200
    if not path:
        return jsonify({"success": False, "message": "缺少 path"}), 200
    removed = config_db.remove_ai_binding(path)
    return jsonify(
        {
            "success": True,
            "removed": removed,
            "message": "已解除绑定" if removed else "未找到该绑定",
        }
    )


@app.route("/api/organize/preview")
def organize_preview():
    """预览当前散落在媒体库中的待整理视频文件"""
    try:
        # 按当前提示词/模型刷新一次缓存有效性，避免展示过期结论
        auto_organizer.sync_attempt_cache()
        files = auto_organizer.preview_loose_files()
        cached = sum(1 for item in files if item["cached"])
        return jsonify(
            {
                "success": True,
                "count": len(files),
                "cached_count": cached,
                "files": files[:200],
            }
        )
    except Exception as exc:
        app.logger.exception("Failed to preview loose files")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/reset", methods=["POST"])
def reset_organize_cache():
    """清空整理尝试缓存，让全部散落文件重新参与整理"""
    try:
        reset_organize_attempts()
        return jsonify({"success": True, "message": "已清空整理缓存，全部散落文件将重新参与整理"})
    except Exception as exc:
        app.logger.exception("Failed to reset organize cache")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/records")
def organize_records():
    """返回 AI 整理产生的变更记录（含已还原），用于详情展示与还原操作"""
    try:
        media_root = Path(MEDIA_PATH).resolve()
        records = config_db.get_organize_change_records(
            run_id=request.args.get("run_id"), limit=500
        )
        for record in records:
            try:
                record["relative_path"] = str(
                    Path(record["path"]).resolve().relative_to(media_root)
                )
            except ValueError:
                record["relative_path"] = record["path"]
            if record.get("original_dir"):
                original_path = Path(record["original_dir"]) / record.get("original")
                record["original_path"] = str(original_path)
                try:
                    record["original_relative_path"] = str(
                        original_path.resolve().relative_to(media_root)
                    )
                except ValueError:
                    record["original_relative_path"] = str(original_path)
            else:
                record["original_path"] = record.get("original")
                record["original_relative_path"] = record.get("original")
        return jsonify({"success": True, "records": records, "total": len(records)})
    except Exception as exc:
        app.logger.exception("Failed to read organize records")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/restore", methods=["POST"])
def restore_organize():
    """还原 AI 整理结果：按剧集 / 按 Season / 按片名"""
    data = request.get_json(silent=True) or {}
    scope = data.get("scope")
    if scope not in ("show", "season", "file"):
        return jsonify({"success": False, "message": "scope 需为 show / season / file"}), 200
    if scope == "file" and not data.get("path"):
        return jsonify({"success": False, "message": "缺少 path"}), 200
    if scope in ("show", "season") and not (
        data.get("media_type") and data.get("show_name")
    ):
        return jsonify({"success": False, "message": "缺少剧集信息"}), 200
    try:
        result = auto_organizer.restore(
            scope=scope,
            media_type=data.get("media_type"),
            show_name=data.get("show_name"),
            season_name=data.get("season_name"),
            path=data.get("path"),
            run_id=data.get("run_id"),
        )
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("Restoring organize result failed")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/toggle", methods=["POST"])
def toggle_organize():
    """开启/关闭定时智能整理开关"""
    data = request.get_json(silent=True) or {}
    enable = bool(data.get("enabled"))
    try:
        set_organize_enabled(enable)
        job = scheduler.get_job("organize_job")
        if job:
            if enable:
                job.resume()
            else:
                job.pause()
        app.logger.info("Auto organize switch set to %s", enable)
        return jsonify(
            {
                "success": True,
                "organize_enabled": enable,
                "organize_next_run_time": _job_next_run_time("organize_job"),
                "message": "已开启定时智能整理" if enable else "已关闭定时智能整理",
            }
        )
    except Exception as exc:
        app.logger.exception("Failed to toggle auto organize")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/interval", methods=["POST"])
def update_organize_interval():
    """更新智能整理执行间隔"""
    data = request.get_json(silent=True) or {}
    try:
        seconds = int(data.get("interval"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "interval 必须为整数秒"}), 200
    if seconds < 60 or seconds > 86400:
        return jsonify({"success": False, "message": "interval 需在 60-86400 秒之间"}), 200
    try:
        set_organize_interval(seconds)
        if scheduler.get_job("organize_job"):
            scheduler.reschedule_job(
                "organize_job",
                trigger="interval",
                seconds=seconds,
                start_date=get_aligned_start(seconds),
            )
        return jsonify(
            {
                "success": True,
                "organize_interval": seconds,
                "organize_next_run_time": _job_next_run_time("organize_job"),
                "message": f"整理间隔已更新为 {seconds} 秒",
            }
        )
    except Exception as exc:
        app.logger.exception("Failed to update auto organize interval")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/run", methods=["POST"])
def run_organize_now():
    """立即执行一次智能整理"""
    if not ai_renamer.is_configured():
        return jsonify({"success": False, "message": "未配置可用的 AI 供应商"}), 200
    try:
        app.logger.info("Start manual auto organizing … …")
        result = auto_organizer.run()
        config_db.add_scan_history(result)
        if result.get("status") == "error":
            return (
                jsonify(
                    {"success": False, "message": result.get("message"), "result": result}
                ),
                200,
            )
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        app.logger.exception("Manual auto organizing failed")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/provider", methods=["POST"])
def update_organize_provider():
    """指定智能整理所使用的模型供应商"""
    data = request.get_json(silent=True) or {}
    provider_id = data.get("provider_id")
    try:
        set_organize_provider_id(provider_id)
        return jsonify(
            {
                "success": True,
                "organize_provider_id": organize_provider_id(),
                "message": "已更新智能整理模型",
            }
        )
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "provider_id 不合法"}), 200
    except Exception as exc:
        app.logger.exception("Failed to update organize provider")
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/organize/history")
def organize_history():
    """返回 AI 自动整理的执行历史"""
    try:
        limit = request.args.get("limit", default=20, type=int)
        limit = max(1, min(limit or 20, 100))
        return jsonify({"success": True, "history": config_db.get_organize_history(limit)})
    except Exception as exc:
        app.logger.exception("Failed to read organize history")
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
    log_dir = Path(LOGS_PATH).resolve()
    if Path(filename).name != filename or not filename.endswith(".log"):
        return jsonify({"error": "非法文件名"}), 400
    log_file = (log_dir / filename).resolve()
    if log_dir not in log_file.parents or not log_file.exists():
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
        if not (
            log_file.name.startswith("emby_renamer_")
            or log_file.name.startswith("app_")
            or log_file.name.startswith("email_notifier_")
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
        # 扫描任务（默认暂停）
        scan_job = scheduler.add_job(
            func=scheduled_scan,
            trigger="interval",
            seconds=SCAN_INTERVAL,
            id="scan_job",
            name="文件扫描任务",
            start_date=get_aligned_start(SCAN_INTERVAL),
            replace_existing=True,
        )
        scan_job.pause()

        # 智能整理任务（按开关状态决定是否运行）
        organize_job = scheduler.add_job(
            func=scheduled_organize,
            trigger="interval",
            seconds=organize_interval(),
            id="organize_job",
            name="智能整理任务",
            start_date=get_aligned_start(organize_interval()),
            replace_existing=True,
        )
        if organize_enabled():
            organize_job.resume()
        else:
            organize_job.pause()

        # 日志清理任务（始终运行）
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
            "Scheduler started. scan_job is paused by default, log_cleanup_job is active."
        )

    port = int(os.getenv("FLASK_PORT", 15000))
    try:
        from waitress import serve  # type: ignore

        app.logger.info("Serving with waitress on 0.0.0.0:%s", port)
        serve(
            app,
            host="0.0.0.0",
            port=port,
            threads=int(os.getenv("SERVER_THREADS", "8")),
        )
    except ImportError:
        app.logger.warning("waitress 未安装，回退到 Flask 开发服务器")
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
