"""
/**
 * AI 自动整理：定时识别散落在媒体库中的离散剧集文件，
 * 自动创建/复用「媒体类型/剧名/Season XX」目录并移动、重命名文件。
 * AI 仅输出结构化 JSON，由本模块解析、校验并执行。
 * @author: Meidlinger
 */
"""

import hashlib
import json
import logging
import os
import re
import shutil
import time
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ai_renamer import AIClient, ai_renamer, extract_json
from database import config_db
from embress_renamer import (
    AUDIO_EXTS,
    PICTURE_EXTS,
    SEASON_PATTERNS,
    SUBTITLE_EXTS,
    OperationBusy,
    WhitelistLoader,
    _operation_guard,
)
from logging_utils import get_logger
from prompt_loader import load_prompt

LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

VIDEO_EXTS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".ts",
    ".m2ts",
}
ASSOCIATED_EXTS = set().union(SUBTITLE_EXTS, AUDIO_EXTS, PICTURE_EXTS, {".nfo"})

# 每个批次提交给 AI 的文件数量，复用 AI_MAX_FILES 以控制单次 token 消耗
ORGANIZE_BATCH = int(os.getenv("AI_MAX_FILES", "80"))
# 提交给 AI 的已有剧名目录上限，避免结构清单过长浪费 token
MAX_STRUCTURE_SHOWS = int(os.getenv("ORGANIZE_MAX_STRUCTURE", "200"))

ORGANIZE_ENABLED_KEY = "auto_organize_enabled"
ORGANIZE_INTERVAL_KEY = "auto_organize_interval"
ORGANIZE_ATTEMPTED_KEY = "auto_organize_attempted"
ORGANIZE_ATTEMPTED_SIG_KEY = "auto_organize_attempted_sig"
ORGANIZE_PROVIDER_KEY = "auto_organize_provider_id"
DEFAULT_ORGANIZE_INTERVAL = int(os.getenv("AUTO_ORGANIZE_INTERVAL", "3600"))
# 尝试缓存有效期（秒）：超时后允许对暂缓文件重新评估
ORGANIZE_ATTEMPT_TTL = int(os.getenv("AUTO_ORGANIZE_TTL", "86400"))

_ILLEGAL_CHARS = re.compile(r'[\\/<>:"|?*\x00-\x1f]')


def organize_enabled() -> bool:
    """读取开关状态"""
    return str(config_db.get_setting(ORGANIZE_ENABLED_KEY, "0")).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def set_organize_enabled(enabled: bool):
    config_db.set_setting(ORGANIZE_ENABLED_KEY, "1" if enabled else "0")
    if enabled:
        # 重新开启时清空历史尝试记录，立即重新评估全部散落文件
        reset_organize_attempts()


def reset_organize_attempts():
    """清空尝试缓存，使全部散落文件重新进入待整理列表"""
    config_db.set_setting(ORGANIZE_ATTEMPTED_KEY, "{}")


def organize_interval() -> int:
    raw = config_db.get_setting(ORGANIZE_INTERVAL_KEY)
    try:
        value = int(raw) if raw is not None else DEFAULT_ORGANIZE_INTERVAL
    except (TypeError, ValueError):
        value = DEFAULT_ORGANIZE_INTERVAL
    return value if value >= 60 else DEFAULT_ORGANIZE_INTERVAL


def set_organize_interval(seconds: int):
    config_db.set_setting(ORGANIZE_INTERVAL_KEY, str(int(seconds)))


def organize_provider_id() -> Optional[int]:
    """智能整理使用的供应商 id，未指定时返回 None（走默认供应商）"""
    raw = config_db.get_setting(ORGANIZE_PROVIDER_KEY)
    if raw in (None, "", "null"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_organize_provider_id(provider_id) -> None:
    if provider_id in (None, "", "null"):
        config_db.set_setting(ORGANIZE_PROVIDER_KEY, "")
    else:
        config_db.set_setting(ORGANIZE_PROVIDER_KEY, str(int(provider_id)))
    # 更换模型后清空尝试缓存，用新模型重新评估
    reset_organize_attempts()


def _clean_component(text) -> Optional[str]:
    """清洗目录/剧名分段：拒绝含路径分隔符的内容，去除其它非法字符"""
    if text is None:
        return None
    raw = str(text)
    if "/" in raw or "\\" in raw:
        return None
    name = _ILLEGAL_CHARS.sub("", raw).strip().strip(".")
    if not name or name in (".", ".."):
        return None
    return name


def _clean_target_name(original_name: str, proposed) -> Optional[str]:
    """校验 AI 给出的目标文件名：必须是纯文件名且扩展名与原文件一致"""
    if not proposed:
        return None
    raw = str(proposed)
    if "/" in raw or "\\" in raw:
        return None
    name = _ILLEGAL_CHARS.sub("", raw).strip().strip('"').strip()
    if not name or name in (".", ".."):
        return None
    if Path(name).name != name:
        return None
    if Path(name).suffix.lower() != Path(original_name).suffix.lower():
        return None
    return name


class AutoOrganizer:
    def __init__(self, media_path: str = None):
        self.media_root = Path(media_path or MEDIA_PATH).resolve()
        self.logger = get_logger(
            name="AIOrganizer",
            log_dir=LOGS_PATH,
            base_name="ai_organizer",
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            to_console=True,
        )

    # ---------- 候选文件收集 ---------- #
    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.media_root).as_posix()
        except ValueError:
            return ""

    def _load_attempted(self) -> Dict[str, str]:
        """读取尝试缓存，返回 {绝对路径: 文件签名}；过期条目自动丢弃"""
        raw = config_db.get_setting(ORGANIZE_ATTEMPTED_KEY, "{}") or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        now = time.time()
        fresh: Dict[str, str] = {}
        for key, value in data.items():
            parts = str(value).split(":")
            signature = ":".join(parts[:2]) if len(parts) >= 2 else str(value)
            try:
                recorded_at = float(parts[2]) if len(parts) >= 3 else 0.0
            except ValueError:
                recorded_at = 0.0
            # 超过 TTL 的条目失效，允许重新评估
            if recorded_at and now - recorded_at > ORGANIZE_ATTEMPT_TTL:
                continue
            fresh[key] = signature
        return fresh

    def sync_attempt_cache(self) -> None:
        """提示词或所用模型变化时清空尝试缓存，避免旧结论阻止重新整理"""
        signature = self._current_context_signature()
        stored = config_db.get_setting(ORGANIZE_ATTEMPTED_SIG_KEY, "")
        if stored != signature:
            config_db.set_setting(ORGANIZE_ATTEMPTED_KEY, "{}")
            config_db.set_setting(ORGANIZE_ATTEMPTED_SIG_KEY, signature)

    def _current_context_signature(self) -> str:
        prompt = load_prompt("organize_system.txt")
        digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
        return f"{digest}:{organize_provider_id()}"

    @staticmethod
    def _signature(path: Path) -> str:
        try:
            stat = path.stat()
        except OSError:
            return ""
        return f"{int(stat.st_mtime)}:{stat.st_size}"

    def _scan_loose(self) -> List[Tuple[Path, bool]]:
        """扫描散落视频文件，返回 (文件, 是否命中尝试缓存)"""
        result: List[Tuple[Path, bool]] = []
        if not self.media_root.exists():
            return result
        attempted = self._load_attempted()
        for dirpath, dirnames, filenames in os.walk(self.media_root):
            current = Path(dirpath)
            if any(pat.search(current.name) for pat in SEASON_PATTERNS):
                dirnames[:] = []  # 已在规范的 Season 目录内，整棵子树跳过
                continue
            for filename in filenames:
                file_path = current / filename
                if file_path.suffix.lower() not in VIDEO_EXTS:
                    continue
                abs_str = str(file_path.absolute())
                if WhitelistLoader.is_whitelisted(abs_str):
                    continue
                cached = attempted.get(abs_str) == self._signature(file_path)
                result.append((file_path, cached))
        result.sort(key=lambda item: str(item[0]))
        return result

    def collect_loose_files(self) -> List[Path]:
        """待整理文件（排除命中的尝试缓存）"""
        return [path for path, cached in self._scan_loose() if not cached]

    def preview_loose_files(self) -> List[Dict]:
        """预览用：返回全部散落文件及其是否被暂缓"""
        return [
            {"path": self.relative(path), "cached": cached}
            for path, cached in self._scan_loose()
        ]

    def _earliest_file_name(self, season_dir: Path) -> Optional[str]:
        """返回该 Season 目录中创建时间最早的文件名，作为命名风格样例"""
        best_name = None
        best_ts = None
        try:
            entries = list(season_dir.iterdir())
        except OSError:
            return None
        for entry in entries:
            if not entry.is_file() or entry.suffix.lower() not in VIDEO_EXTS:
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            ts = getattr(stat, "st_birthtime", None) or stat.st_ctime
            if best_ts is None or ts < best_ts:
                best_ts, best_name = ts, entry.name
        return best_name

    def _snapshot_structure(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        """实时扫描媒体库结构：媒体类型 -> 剧名 -> {Season 目录: 该季最早的文件名样例}"""
        structure: Dict[str, Dict[str, Dict[str, str]]] = {}
        if not self.media_root.exists():
            return structure
        total = 0
        for media_type_dir in sorted(self.media_root.iterdir(), key=lambda p: p.name):
            if not media_type_dir.is_dir():
                continue
            shows: Dict[str, Dict[str, str]] = {}
            for show_dir in sorted(media_type_dir.iterdir(), key=lambda p: p.name):
                if not show_dir.is_dir():
                    continue
                seasons: Dict[str, str] = {}
                try:
                    season_dirs = sorted(show_dir.iterdir(), key=lambda p: p.name)
                except OSError:
                    season_dirs = []
                for season_dir in season_dirs:
                    if not season_dir.is_dir():
                        continue
                    if not any(
                        pattern.search(season_dir.name) for pattern in SEASON_PATTERNS
                    ):
                        continue
                    sample = self._earliest_file_name(season_dir)
                    seasons[season_dir.name] = sample or ""
                shows[show_dir.name] = seasons
                total += 1
                if total >= MAX_STRUCTURE_SHOWS:
                    break
            structure[media_type_dir.name] = shows
            if total >= MAX_STRUCTURE_SHOWS:
                break
        return structure

    # ---------- AI 规划 ---------- #
    def _build_messages(
        self, files: List[str], structure: Dict[str, Dict[str, Dict[str, str]]]
    ) -> List[Dict]:
        payload = {"media_root_structure": structure, "files": files}
        return [
            {"role": "system", "content": load_prompt("organize_system.txt")},
            {
                "role": "user",
                "content": "请整理以下散落的视频文件：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ]

    def plan(self, files: List[Path]) -> Tuple[List[Dict], bool, Dict]:
        """请求 AI 生成整理计划，返回 (items, ai_responded, stats)"""
        stats = {"model": "", "batches": 0, "media_types": 0, "shows": 0, "seasons": 0}
        if not files:
            return [], False, stats
        config = ai_renamer.config_for(organize_provider_id())
        if not config or not config.get("base_url"):
            self.logger.warning("智能整理：未配置可用的 AI 供应商")
            return [], False, stats

        stats["model"] = config.get("model") or ""
        client = AIClient(
            base_url=config["base_url"],
            api_key=config.get("api_key") or "",
            model=config["model"],
        )
        structure = self._snapshot_structure()
        stats["media_types"] = len(structure)
        stats["shows"] = sum(len(shows) for shows in structure.values())
        stats["seasons"] = sum(
            len(seasons) for shows in structure.values() for seasons in shows.values()
        )
        rel_map = {self.relative(p): p for p in files}
        rels = list(rel_map.keys())
        items: List[Dict] = []
        responded = False
        for start in range(0, len(rels), ORGANIZE_BATCH):
            batch = rels[start : start + ORGANIZE_BATCH]
            stats["batches"] += 1
            try:
                raw = client.chat(
                    self._build_messages(batch, structure), model=config["model"]
                )
                data = extract_json(raw) or {}
                responded = True
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                KeyError,
                ValueError,
            ) as exc:
                self.logger.error("智能整理 AI 请求失败: %s", exc)
                continue
            except Exception as exc:  # 兜底，绝不影响主流程
                self.logger.exception("智能整理 AI 异常: %s", exc)
                continue
            for item in data.get("items", []) if isinstance(data, dict) else []:
                rel = item.get("file")
                if rel in rel_map:
                    item["_abs"] = str(rel_map[rel])
                    items.append(item)
        return items, responded, stats

    # ---------- 执行计划 ---------- #
    def _build_target(self, item: Dict) -> Optional[Tuple[Path, Path]]:
        original = Path(item["_abs"])
        media_type = _clean_component(item.get("media_type"))
        show_name = _clean_component(item.get("show_name"))
        if not media_type or not show_name:
            return None
        try:
            season = int(float(item.get("season") or 1))
        except (TypeError, ValueError):
            season = 1
        if season < 0 or season > 99:
            season = 1
        target_name = _clean_target_name(original.name, item.get("target_name"))
        if not target_name:
            return None
        season_dir = self.media_root / media_type / show_name / f"Season {season:02d}"
        return season_dir / target_name, season_dir

    def _move_with_associates(self, src: Path, dst: Path):
        """移动主文件，并同步移动同名的字幕/音频/图片/NFO 附属文件"""
        src_stem, dst_stem = src.stem, dst.stem
        associates: List[Path] = []
        for sibling in src.parent.iterdir():
            if not sibling.is_file() or sibling == src:
                continue
            if sibling.suffix.lower() not in ASSOCIATED_EXTS:
                continue
            if re.match(re.escape(src_stem) + r"(\.|$)", sibling.stem, re.I):
                associates.append(sibling)

        shutil.move(str(src), str(dst))
        moved_associates = 0
        for assoc in associates:
            remainder = assoc.name[len(src_stem) :]
            new_path = dst.parent / f"{dst_stem}{remainder}"
            if new_path.exists():
                continue
            try:
                shutil.move(str(assoc), str(new_path))
                moved_associates += 1
            except Exception as exc:
                self.logger.warning("附属文件移动失败 %s: %s", assoc.name, exc)
        return moved_associates

    def _cleanup_empty_dirs(self, path: Path) -> int:
        """清理被搬空的原目录（保留媒体根目录及其一级子目录），返回清理数量"""
        root = self.media_root
        current = path
        removed = 0
        while current != root and current.parent != root and current != current.parent:
            try:
                if not current.is_dir() or any(current.iterdir()):
                    return removed
                current.rmdir()
                removed += 1
            except OSError:
                return removed
            current = current.parent
        return removed

    def execute(self, items: List[Dict]) -> Tuple[int, int, int, List[Dict]]:
        moved = failed = skipped = 0
        records: List[Dict] = []
        self._last_run_stats = {
            "associates_moved": 0,
            "dirs_created": 0,
            "dirs_cleaned": 0,
        }
        for item in items:
            original = Path(item["_abs"])
            rel_from = self.relative(original)
            if not original.exists():
                skipped += 1
                continue
            target = self._build_target(item)
            if not target:
                skipped += 1
                records.append(
                    {"from": rel_from, "status": "skip", "reason": "AI 结果不合法"}
                )
                continue
            target_path, season_dir = target
            try:
                if target_path == original:
                    skipped += 1
                    continue
                if target_path.exists():
                    skipped += 1
                    records.append(
                        {
                            "from": rel_from,
                            "status": "skip",
                            "reason": "目标已存在",
                        }
                    )
                    continue
                if not season_dir.exists():
                    self._last_run_stats["dirs_created"] += 1
                season_dir.mkdir(parents=True, exist_ok=True)
                self._last_run_stats["associates_moved"] += self._move_with_associates(
                    original, target_path
                )
                moved += 1
                records.append(
                    {
                        "from": rel_from,
                        "to": self.relative(target_path),
                        "media_type": target_path.parent.parent.parent.name,
                        "show_name": target_path.parent.parent.name,
                        "season": target_path.parent.name,
                        "status": "success",
                    }
                )
                self._last_run_stats["dirs_cleaned"] += self._cleanup_empty_dirs(
                    original.parent
                )
            except Exception as exc:
                failed += 1
                self.logger.exception("智能整理移动失败: %s", original)
                records.append(
                    {"from": rel_from, "status": "failed", "error": str(exc)}
                )
        return moved, failed, skipped, records

    def _remember_attempts(self, files: List[Path], exclude: Optional[set] = None):
        """记录本轮已尝试但未成功整理的文件，避免下轮重复消耗 token（带时间戳，可过期重试）

        exclude 中的文件（AI 结果不合法、移动失败等）不写入缓存，以便下轮重试。
        """
        exclude = exclude or set()
        existing = self._load_attempted()
        updated: Dict[str, str] = {}
        now = int(time.time())
        for file_path in files:
            if not file_path.exists():
                continue
            abs_str = str(file_path.absolute())
            if abs_str in exclude:
                continue
            signature = self._signature(file_path)
            if not signature:
                continue
            updated[abs_str] = f"{signature}:{now}"
        # 保留其它仍然存在于磁盘上的历史记录，剔除已消失的条目
        for abs_str, signature in existing.items():
            if abs_str in updated or abs_str in exclude:
                continue
            if Path(abs_str).exists():
                updated[abs_str] = f"{signature}:{now}"
        try:
            config_db.set_setting(
                ORGANIZE_ATTEMPTED_KEY,
                json.dumps(updated, ensure_ascii=False),
            )
        except Exception as exc:
            self.logger.warning("写入整理尝试记录失败: %s", exc)

    # ---------- 对外入口 ---------- #
    def run(self) -> Dict:
        try:
            with _operation_guard():
                return self._do_run()
        except OperationBusy as exc:
            return {
                "status": "error",
                "scan_type": "organize",
                "message": str(exc),
                "processed": 0,
                "renamed": 0,
                "timestamp": datetime.now().isoformat(),
                "target": "AUTO",
            }

    def _do_run(self) -> Dict:
        # 提示词或所用模型变化时，先清空旧的尝试缓存
        self.sync_attempt_cache()
        milestones: List[Dict] = []

        def mark(phase: str, title: str, detail: str, status: str = "ok"):
            milestones.append(
                {
                    "phase": phase,
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            )

        files = self.collect_loose_files()
        result = {
            "status": "completed",
            "scan_type": "organize",
            "processed": len(files),
            "renamed": 0,
            "moved": 0,
            "skipped": 0,
            "failed": 0,
            "items": [],
            "milestones": milestones,
            "timestamp": datetime.now().isoformat(),
            "target": "AUTO",
        }
        mark("program", "扫描媒体库", f"发现 {len(files)} 个未归入 Season 目录的散落视频文件")
        if not files:
            self.logger.info("智能整理：没有发现需要整理的散落剧集文件")
            return result
        if not ai_renamer.is_configured():
            mark("program", "检查模型配置", "未配置可用的 AI 供应商", "error")
            result.update({"status": "error", "message": "未配置可用的 AI 供应商"})
            return result

        self.logger.info("智能整理：发现 %d 个候选文件，开始请求 AI", len(files))
        items, responded, stats = self.plan(files)
        mark(
            "program",
            "构建媒体库结构快照",
            f"{stats['media_types']} 个媒体类型 / {stats['shows']} 个剧集 / "
            f"{stats['seasons']} 个季目录（含每季创建时间最早的文件名样例）",
        )
        if not responded:
            mark("ai", "请求模型", "调用失败，请检查供应商配置与网络", "error")
            result.update({"status": "error", "message": "AI 请求失败，请检查供应商配置"})
            return result

        mark(
            "ai",
            "请求模型",
            f"模型 {stats['model'] or '(默认)'} · 共 {stats['batches']} 批 · {len(files)} 个文件",
        )
        if not items:
            # AI 未给出任何可用结果（如提示词缺失/解析失败），不写入尝试缓存，
            # 保证修正配置后这些文件仍可被重新整理
            mark("ai", "AI 判断", "AI 未返回可执行的整理计划，本批文件保留待下次重试", "warn")
            result["message"] = "AI 未返回可执行的整理计划，这批文件将保留待下次重试"
            self.logger.warning("智能整理：AI 未返回可用结果，本次不缓存候选文件")
            return result

        for item in items[:30]:
            confidence = item.get("confidence")
            confidence_text = (
                f"置信度 {confidence}" if isinstance(confidence, (int, float)) else ""
            )
            reason = item.get("reason") or ""
            detail = (
                f"{item.get('file')} → "
                f"{item.get('media_type')}/{item.get('show_name')}/Season {item.get('season')}"
            )
            if confidence_text or reason:
                detail += f" · {' · '.join(x for x in (confidence_text, reason) if x)}"
            mark("ai", "AI 判断归属", detail)
        if len(items) > 30:
            mark("ai", "AI 判断归属", f"…… 其余 {len(items) - 30} 条判断已省略")

        self.logger.info("智能整理：开始执行 %d 条计划", len(items))
        moved, failed, skipped, records = self.execute(items)
        run_stats = getattr(self, "_last_run_stats", {})
        mark("program", "校验并执行计划", f"共 {len(items)} 条计划进入执行阶段")
        mark(
            "program",
            "创建 / 复用目录",
            f"新建季目录 {run_stats.get('dirs_created', 0)} 个，其余复用已有目录",
        )
        mark(
            "program",
            "移动并重命名文件",
            f"主文件 {moved} 个 · 附属文件（字幕/音频/图片/NFO）{run_stats.get('associates_moved', 0)} 个",
        )
        if run_stats.get("dirs_cleaned"):
            mark("program", "清理空目录", f"移除被搬空的原目录 {run_stats['dirs_cleaned']} 个")
        if skipped:
            mark("program", "跳过文件", f"{skipped} 个文件被跳过（目标已存在或结果不合法）", "warn")
        if failed:
            mark("program", "移动失败", f"{failed} 个文件移动失败，将保留待下轮重试", "error")

        result.update(
            {
                "renamed": moved,
                "moved": moved,
                "failed": failed,
                "skipped": skipped,
                "processed": len(items),
                "items": records[:200],
            }
        )
        self._remember_attempts(files, exclude=self._retryable_paths(records))
        recorded = self._persist_change_records(records)
        mark("program", "写入变更记录", f"已记录 {recorded} 条整理变更，可在变更记录中查看或还原")
        self.logger.info(
            "智能整理完成：移动 %d，跳过 %d，失败 %d", moved, skipped, failed
        )
        return result

    def _persist_change_records(self, records: List[Dict]) -> int:
        """把成功的整理动作写入变更记录，使其出现在「变更记录」中并标注来源

        类型使用 organize 而非 rename，回滚逻辑只处理 rename，因此不会误触发回滚。
        同时记录原文件所在目录，便于后续按剧集/季/片名精准还原。
        """
        change_records = []
        for record in records:
            if record.get("status") != "success" or not record.get("to"):
                continue
            target_path = self.media_root / record["to"]
            origin_path = self.media_root / record["from"]
            change_records.append(
                {
                    "path": str(target_path.absolute()),
                    "original": Path(record["from"]).name,
                    "new": target_path.name,
                    "type": "organize",
                    "status": "success",
                    "timestamp": datetime.now().isoformat(),
                    "media_type": record.get("media_type"),
                    "show_name": record.get("show_name"),
                    "season_name": record.get("season"),
                    "rollback": 0,
                    "season_dir": str(target_path.parent.absolute()),
                    "original_dir": str(origin_path.parent.absolute()),
                    "source": "ai-organize",
                }
            )
        if not change_records:
            return 0
        try:
            config_db.add_change_records(change_records)
        except Exception as exc:
            self.logger.warning("写入整理变更记录失败: %s", exc)
            return 0
        return len(change_records)

    def _retryable_paths(self, records: List[Dict]) -> set:
        """返回需要下轮重试的文件绝对路径（AI 结果不合法 / 移动失败）"""
        paths = set()
        for record in records:
            if record.get("status") == "failed" or record.get("reason") == "AI 结果不合法":
                rel = record.get("from")
                if rel:
                    paths.add(str((self.media_root / rel).absolute()))
        return paths

    # ---------- 还原 ---------- #
    def restore(
        self,
        scope: str,
        media_type: str = None,
        show_name: str = None,
        season_name: str = None,
        path: str = None,
    ) -> Dict:
        """还原 AI 整理结果：scope 支持 show（按剧集）/ season（按季）/ file（按片名）"""
        try:
            with _operation_guard():
                return self._do_restore(scope, media_type, show_name, season_name, path)
        except OperationBusy as exc:
            return {
                "success": False,
                "message": str(exc),
                "restored": 0,
                "skipped": 0,
                "failed": 0,
                "items": [],
            }

    def _do_restore(
        self, scope: str, media_type: str, show_name: str, season_name: str, path: str
    ) -> Dict:
        if scope == "file":
            records = config_db.get_organize_change_records(path=path, only_active=True)
        elif scope == "season":
            records = config_db.get_organize_change_records(
                media_type=media_type,
                show_name=show_name,
                season_name=season_name,
                only_active=True,
            )
        elif scope == "show":
            records = config_db.get_organize_change_records(
                media_type=media_type, show_name=show_name, only_active=True
            )
        else:
            return {
                "success": False,
                "message": "不支持的还原范围",
                "restored": 0,
                "skipped": 0,
                "failed": 0,
                "items": [],
            }

        if not records:
            return {
                "success": True,
                "scope": scope,
                "restored": 0,
                "skipped": 0,
                "failed": 0,
                "items": [],
                "message": "没有可还原的整理记录",
            }

        restored = skipped = failed = 0
        items: List[Dict] = []
        for record in records:
            cur_path = Path(record["path"])
            original_name = record.get("original")
            rel_cur = self.relative(cur_path) or str(cur_path)
            original_dir = record.get("original_dir")
            if not original_dir or not original_name:
                skipped += 1
                items.append(
                    {"from": rel_cur, "status": "skip", "reason": "缺少原始路径信息"}
                )
                continue
            target = Path(original_dir) / original_name
            if not cur_path.exists():
                # 源文件已不存在，直接标记为已还原
                config_db.update_change_record_rollback(
                    record["path"], original_name, True
                )
                restored += 1
                items.append(
                    {
                        "from": rel_cur,
                        "to": self.relative(target) or str(target),
                        "status": "success",
                        "reason": "源文件已不存在，仅标记为已还原",
                    }
                )
                continue
            if target.exists():
                skipped += 1
                items.append(
                    {"from": rel_cur, "status": "skip", "reason": "原位置已存在同名文件"}
                )
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                self._move_with_associates(cur_path, target)
                config_db.update_change_record_rollback(
                    record["path"], original_name, True
                )
                restored += 1
                items.append(
                    {
                        "from": rel_cur,
                        "to": self.relative(target) or str(target),
                        "status": "success",
                    }
                )
                self._cleanup_empty_dirs(cur_path.parent)
            except Exception as exc:
                failed += 1
                self.logger.exception("还原整理文件失败: %s", cur_path)
                items.append({"from": rel_cur, "status": "failed", "error": str(exc)})

        self.logger.info(
            "智能整理还原：成功 %d，跳过 %d，失败 %d", restored, skipped, failed
        )
        return {
            "success": True,
            "scope": scope,
            "restored": restored,
            "skipped": skipped,
            "failed": failed,
            "items": items[:200],
        }


auto_organizer = AutoOrganizer()