"""
/**
 * @author: Meidlinger
 * @date: 2025-06-29
 */
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set, Union
from database import config_db
import time

from logging_utils import get_logger

LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


STATUS_RENAMED = "renamed"
STATUS_FAILED = "failed"
STATUS_SKIP = "skip"
STATUS_UNMATCHED = "unmatched"
STATUS_WHITELIST = "whitelisted"
STATUS_UNPROCESSED = "unprocessed"

SUBTITLE_EXTS: Set[str] = {".ass", ".srt", ".vtt", ".sub"}
AUDIO_EXTS: Set[str] = {".mka", ".flac"}
PICTURE_EXTS: Set[str] = {".jpg", ".png", ".jpeg"}
ADDITION_CHANGE: Set[str] = {
    "subtitle_rename",
    "audio_rename",
    "picture_rename",
    "nfo_delete",
}

SEASON_PATTERNS = [
    re.compile(r"season[ _\-]?(\d{1,2})", re.I),
    re.compile(r"s(\d{1,2})$", re.I),
    re.compile(r"第(\d{1,2})季"),
]


class WhitelistLoader:
    _cache: Dict[str, Union[Set[str], List[Path]]] = None
    _cache_time: float = 0
    _ttl = 5

    @classmethod
    def whitelist(cls) -> Dict[str, Union[Set[str], List[Path]]]:
        now = time.time()
        FULL_MEDIA_PATH = Path(MEDIA_PATH).resolve()
        if cls._cache is None or now - cls._cache_time > cls._ttl:
            entries = config_db.get_whitelist()
            file_set: Set[str] = set()
            dir_list: List[Path] = []
            for entry in entries:
                if entry.get("type") == "directory":
                    raw = entry["path"].strip().lstrip("/\\")
                    path = (FULL_MEDIA_PATH / raw).resolve()
                    dir_list.append(path)
                else:
                    file_set.add(str(entry["path"]))
            cls._cache = {"files": file_set, "dirs": dir_list}
            cls._cache_time = now
        return cls._cache

    @classmethod
    def is_whitelisted(cls, abs_path: str) -> bool:
        wl = cls.whitelist()
        if abs_path in wl["files"]:
            return True
        path = Path(abs_path)
        for d in wl["dirs"]:
            try:
                if path.is_relative_to(d):
                    return True
            except ValueError:
                continue
        return False

    @classmethod
    def force_reload(cls):
        """手动刷新缓存"""
        cls._cache = None
        cls._cache_time = 0


class RegexLoader:
    _cache_mtime: float = 0.0
    _patterns: Dict[str, List[str]] = {}

    @classmethod
    def patterns(cls) -> Dict[str, List[str]]:
        return config_db.get_regex_patterns()


class EmbressRenamer:
    def __init__(self, media_path: str):
        self.media_path = Path(media_path)
        self.logger = self._setup_logger()
        self._pending_change_records: List[Dict] = []
        self._seasons_to_update: Set[Path] = set()

    def _setup_logger(self) -> logging.Logger:
        return get_logger(
            name="EmbressRenamer",
            log_dir=LOGS_PATH,
            base_name="emby_renamer",
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            to_console=True,
        )

    def _extract_episode_info(
        self, filename: str
    ) -> Optional[Tuple[Optional[int], Union[int, float], Optional[Tuple[int, int]]]]:
        """提取集数信息，返回 (季数, 集数, 匹配位置)"""
        p_cfg = RegexLoader.patterns()

        # (季,集) 模式
        for pat in p_cfg.get("season_episode", []):
            if m := re.search(pat, filename, re.I):
                season = int(m.group(1))
                episode = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
                return season, episode, m.span()

        # 仅集数模式
        for pat in p_cfg.get("episode_only", []):
            if m := re.search(pat, filename, re.I):
                episode_str = m.group(1)
                episode = float(episode_str) if "." in episode_str else int(episode_str)
                return None, episode, m.span()

        return None

    def _get_season_from_path(self, file_path: Path) -> Optional[int]:
        for part in file_path.parts:
            if m := re.search(r"[Ss]eason\s*(\d{1,2})", part, re.I):
                return int(m.group(1))
        return None

    def _generate_new_filename(
        self,
        original: str,
        season: Optional[int],
        episode: Union[int, float],
        match_span: Optional[Tuple[int, int]] = None,
    ) -> str:
        season_fmt = season if season is not None else 1
        ep_fmt = (
            f"{episode:.1f}".rstrip("0").rstrip(".")
            if isinstance(episode, float)
            else f"{episode:02d}"
        )
        new_seg = f"S{season_fmt:02d}E{ep_fmt}"

        # 检查是否已经是期望的格式
        if re.search(rf"\[{re.escape(new_seg)}\]", original, re.I) or re.search(
            rf"\bS{season_fmt:02d}E{re.escape(ep_fmt)}\b", original, re.I
        ):
            return original

        if match_span:
            start, end = match_span
            matched_text = original[start:end]

            # 如果匹配的是 [数字] 格式，直接替换整个匹配部分
            if re.match(r"\[\d{1,3}(?:\.\d)?\]", matched_text):
                new_filename = original[:start] + f"[{new_seg}]" + original[end:]
                return self._normalize_filename(new_filename)

            # 如果匹配的是其他格式，找到数字部分进行替换
            inner_match = re.search(r"\d{1,3}(?:\.\d)?", matched_text)
            if inner_match:
                inner_start, inner_end = inner_match.span()
                absolute_start = start + inner_start
                absolute_end = start + inner_end
                new_filename = (
                    original[:absolute_start] + f"[{new_seg}]" + original[absolute_end:]
                )
                return self._normalize_filename(new_filename)

        # 原有的逻辑作为兜底
        new = original

        # 示例：- 6.5 → - [S01E6.5]
        new2 = re.sub(
            r"-\s*\d{1,3}(?:\.\d)?(?=\s+(?:\[|\(|[A-Za-z]))",
            f"- [{new_seg}] ",
            new,
            count=1,
            flags=re.I,
        )
        if new2 != new:
            return self._normalize_filename(new2)

        new2 = re.sub(
            r"\s+\d{1,3}(?:\.\d)?(?=\s*\()",
            f" [{new_seg}]",
            new,
            count=1,
        )
        if new2 != new:
            return self._normalize_filename(new2)

        new2 = re.sub(r"\s+\d{1,3}(?:\.\d)?(?=\s*\[)", f" [{new_seg}]", new, count=1)
        if new2 != new:
            return self._normalize_filename(new2)

        # "[数字]" → "[SxxEyy]"
        matches = list(re.finditer(r"\[(\d{1,3}(?:\.\d)?)\]", new))
        if matches:
            s, e = matches[-1].span()
            new2 = new[:s] + f"[{new_seg}]" + new[e:]
            return self._normalize_filename(new2)

        # "- 6.5 -" → "- [S01E6.5] -"
        new2 = re.sub(
            r"-(\s*)\d{1,3}(?:\.\d)?(\s*)-", rf"-\1[{new_seg}]\2-", new, count=1
        )
        if new2 != new:
            return self._normalize_filename(new2)

        # Episode / Eyy，避免重复插入
        new2 = re.sub(
            r"(?<!S\d{2})E\d{1,3}(?:\.\d)?", new_seg, new, count=1, flags=re.I
        )
        if new2 != new:
            return self._normalize_filename(new2)

        # 默认添加
        p = Path(original)
        new2 = f"{p.stem} [{new_seg}]{p.suffix}"
        return self._normalize_filename(new2)

    def _normalize_filename(self, name: str) -> str:
        """清理多余空格、点号前空格等问题"""
        name = re.sub(r"\s{2,}", " ", name)  # 连续空格
        name = re.sub(r"\s+\.", ".", name)  # 点号前空格
        return name.strip()

    def _rollback_file_and_subtitles(
        self, file_path: Path, new_name: str, original_records: List[Dict] = None
    ) -> List[Dict]:
        changes: List[Dict] = []
        old_stem = file_path.stem
        new_stem = Path(new_name).stem
        new_file_path = file_path.parent / new_name
        ASSOCIATED_EXTS = set().union(SUBTITLE_EXTS, AUDIO_EXTS, PICTURE_EXTS)
        if file_path != new_file_path and not new_file_path.exists():
            try:
                file_path.rename(new_file_path)
                changes.append(
                    {
                        "type": "rename",
                        "original": file_path.name,
                        "new": new_name,
                        "status": "success",
                    }
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "rename",
                        "original": file_path.name,
                        "new": new_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )
                self.logger.error(f"重命名失败: {e}")
                return changes
        for associated_file in file_path.parent.iterdir():
            if not associated_file.is_file():
                continue
            ext = associated_file.suffix.lower()
            if ext not in ASSOCIATED_EXTS:
                continue
            if not re.match(
                re.escape(old_stem) + r"(\.|$)", associated_file.stem, re.I
            ):
                continue

            remainder = associated_file.name[len(old_stem) :]
            new_assoc_name = f"{new_stem}{remainder}"
            new_assoc_path = associated_file.parent / new_assoc_name
            record_type = "subtitle_rename"
            if ext in SUBTITLE_EXTS:
                record_type = "subtitle_rename"
            elif ext in AUDIO_EXTS:
                record_type = "audio_rename"
            else:
                record_type = "picture_rename"
            if new_assoc_path.exists():
                continue
            try:
                associated_file.rename(new_assoc_path)

                changes.append(
                    {
                        "type": record_type,
                        "original": associated_file.name,
                        "new": new_assoc_name,
                        "status": "success",
                    }
                )
                if original_records:
                    for record in original_records:
                        if (
                            (
                                record.get("type") == "subtitle_rename"
                                or record.get("type") == "audio_rename"
                                or record.get("type") == "picture_rename"
                            )
                            and record.get("status") == "success"
                            and record.get("rollback") is not True
                            and record.get("new") == associated_file.name
                            and record.get("original") == new_assoc_name
                        ):
                            record["rollback"] = True
                            break

            except Exception as e:
                changes.append(
                    {
                        "type": record_type,
                        "original": associated_file.name,
                        "new": new_assoc_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )

        return changes

    def _rename_file_and_subtitles(self, file_path: Path, new_name: str) -> List[Dict]:
        changes: List[Dict] = []
        old_stem = file_path.stem
        new_stem = Path(new_name).stem
        new_file_path = file_path.parent / new_name
        ASSOCIATED_EXTS = set().union(SUBTITLE_EXTS, AUDIO_EXTS, PICTURE_EXTS)
        if file_path != new_file_path and not new_file_path.exists():
            try:
                file_path.rename(new_file_path)
                changes.append(
                    {
                        "type": "rename",
                        "original": file_path.name,
                        "new": new_name,
                        "status": "success",
                        "error": None,
                    }
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "rename",
                        "original": file_path.name,
                        "new": new_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )
                self.logger.error(f"重命名失败: {e}")
                return changes

        for associated_file in file_path.parent.iterdir():
            if not associated_file.is_file():
                continue
            ext = associated_file.suffix.lower()
            if ext not in ASSOCIATED_EXTS:
                continue
            if not re.match(
                re.escape(old_stem) + r"(\.|$)", associated_file.stem, re.I
            ):
                continue
            record_type = "subtitle_rename"
            if ext in SUBTITLE_EXTS:
                record_type = "subtitle_rename"
            elif ext in AUDIO_EXTS:
                record_type = "audio_rename"
            else:
                record_type = "picture_rename"
            remainder = associated_file.name[len(old_stem) :]
            new_assoc_name = f"{new_stem}{remainder}"
            new_assoc_path = associated_file.parent / new_assoc_name
            if new_assoc_path.exists():
                continue
            try:
                associated_file.rename(new_assoc_path)
                changes.append(
                    {
                        "type": record_type,
                        "original": associated_file.name,
                        "new": new_assoc_name,
                        "status": "success",
                        "error": None,
                    }
                )
            except Exception as e:
                changes.append(
                    {
                        "type": record_type,
                        "original": associated_file.name,
                        "new": new_assoc_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )
        changes = self._delete_old_nfo(file_path.parent, old_stem, changes)
        return changes

    def _sync_orphan_subtitles(self, season_dir: Path) -> List[Dict]:
        try:
            records = config_db.get_season_change_records(str(season_dir.absolute()))
        except Exception as e:
            self.logger.warning("从数据库获取变更记录失败: %s", e)
            return []

        latest_map: Dict[str, Tuple[str, str]] = {}
        for r in records:
            if r.get("type") != "rename" or r.get("status") != "success":
                continue
            orig, new, ts = r.get("original"), r.get("new"), r.get("timestamp", "")
            if not (orig and new):
                continue
            if (orig not in latest_map) or (ts > latest_map[orig][1]):
                latest_map[orig] = (new, ts)

        if not latest_map:
            return []
        # --- 统一处理字幕 & NFO -------------------------------------------------
        ASSOCIATED_EXTS = set().union(SUBTITLE_EXTS, AUDIO_EXTS, PICTURE_EXTS)
        changes: List[Dict] = []
        for orig, (latest_new, _) in latest_map.items():  # ← 一个 for 里搞定两件事
            orig_stem = Path(orig).stem
            new_stem = Path(latest_new).stem

            for item in season_dir.iterdir():
                if not item.is_file():
                    continue
                ext = item.suffix.lower()
                if ext in ASSOCIATED_EXTS and re.match(
                    rf"{re.escape(orig_stem)}(\.|$)", item.stem, re.I
                ):
                    remainder = item.name[len(orig_stem) :]
                    new_name = f"{new_stem}{remainder}"
                    new_path = item.with_name(new_name)
                    record_type = "subtitle_rename"
                    if ext in SUBTITLE_EXTS:
                        record_type = "subtitle_rename"
                    elif ext in AUDIO_EXTS:
                        record_type = "audio_rename"
                    else:
                        record_type = "picture_rename"
                    if not new_path.exists():
                        try:

                            item.rename(new_path)
                            changes.append(
                                {
                                    "type": record_type,
                                    "original": item.name,
                                    "new": new_name,
                                    "status": "success",
                                }
                            )
                            self.logger.info("修复字幕: %s → %s", item.name, new_name)
                        except Exception as e:
                            changes.append(
                                {
                                    "type": record_type,
                                    "original": item.name,
                                    "new": new_name,
                                    "status": "failed",
                                    "error": str(e),
                                }
                            )
            # 2) NFO 删除
            changes = self._delete_old_nfo(season_dir, orig_stem, changes)
        return changes

    def _get_new_change_record(
        self, season_dir: Path, media_type: str, changes: List[Dict]
    ):
        processed_changes = []
        for c in changes:
            c["timestamp"] = datetime.now().isoformat()
            c["media_type"] = media_type
            c["path"] = str(
                (season_dir / c.get("new", c.get("original", ""))).absolute()
            )
            c["season_dir"] = str(season_dir.absolute())
            try:
                relative_path = season_dir.relative_to(self.media_path)
                parts = relative_path.parts
                if len(parts) >= 2:
                    c["show_name"] = parts[-2]
                    c["season_name"] = parts[-1]
            except ValueError:
                c["show_name"] = season_dir.parent.name
                c["season_name"] = season_dir.name

            processed_changes.append(c)
        return processed_changes

    def _write_all_change_records(self, season_dir):
        rename_record_path = season_dir / "rename_record.json"
        try:
            new_records = config_db.get_season_change_records(str(season_dir))
        except Exception as e:
            self.logger.error(f"获取变更记录失败: {e}")
        rename_record_path.write_text(
            json.dumps(new_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _season_processed_set(self, season_dir: Path) -> Set[Tuple[str, str]]:
        """从数据库获取已处理的文件集合"""
        try:
            records = config_db.get_season_change_records(str(season_dir.absolute()))
            processed: Set[Tuple[str, str]] = set()

            for record in records:
                if record.get("status") == "success":
                    processed.add((record["path"], record.get("new", "")))

            return processed
        except Exception as e:
            self.logger.error(f"从数据库获取已处理文件失败: {e}")
            return set()

    @staticmethod
    def _count_success_renames(changes: List[Dict]) -> int:
        return sum(
            1
            for c in changes
            if c.get("type") == "rename" and c.get("status") == "success"
        )

    @staticmethod
    def _count_subtitle_success_renames(changes: List[Dict]) -> int:
        return sum(
            1
            for c in changes
            if c.get("type") == "subtitle_rename" and c.get("status") == "success"
        )

    @staticmethod
    def _count_success_by_type(changes: List[Dict]) -> Dict[str, int]:
        stats = {
            "rename": 0,
            "subtitle_rename": 0,
            "audio_rename": 0,
            "picture_rename": 0,
            "nfo_delete": 0,
        }
        for c in changes:
            t, s = c.get("type"), c.get("status")
            if t in stats and s == "success":
                stats[t] += 1
        return stats

    @staticmethod
    def _build_skip_record(file_name: str) -> List[Dict]:
        return [
            {
                "type": "rename",
                "original": file_name,
                "new": file_name,
                "status": STATUS_SKIP,
            }
        ]

    def _dedup_latest(self, records: list[dict]) -> list[dict]:
        latest_map = {}
        for rec in records:
            key = rec.get("path") or rec.get("new")  # 两者理论相同，这里选 path 更稳
            ts = rec.get("timestamp", "")
            if not key:
                continue
            if key not in latest_map or ts > latest_map[key]["timestamp"]:
                latest_map[key] = rec
        return list(latest_map.values())

    def scan_and_rollback(self, sub_path: str):
        self.logger.info(f"Start rollback Season: {sub_path}")
        season_dir = Path(MEDIA_PATH) / sub_path
        rollback_record_path = season_dir / "rollback.json"
        media_type = self._extract_media_type(season_dir)
        if not season_dir.exists():
            result = {"success": False, "message": "Season path not found "}
            code = 200
            return {"result": result, "code": code}
        try:
            original_records = config_db.get_season_change_records(
                str(season_dir.absolute())
            )
        except Exception as e:
            self.logger.error(f"Failed to retrieve change records: {e}")
            result = {"records": [], "total": 0, "error": str(e)}
            code = 500
            return {"result": result, "code": code}
        rollback_results = []
        original_records = self._dedup_latest(original_records)
        nfo_changes = []
        rolled_back_file_cnt = 0
        rolled_back_sub_cnt = 0
        rolled_back_audio_cnt = 0
        rolled_back_picture_cnt = 0
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
                        "timestamp": datetime.now().isoformat(),
                        "path": rec["path"],
                    }
                )
                continue
            try:
                changes = self._rollback_file_and_subtitles(
                    cur_path, original_name, original_records
                )

                if self._count_success_renames(changes):
                    rolled_back_file_cnt += 1
                    rollback_result = {
                        "type": "rollback",
                        "original": rec["new"],
                        "new": original_name,
                        "status": "rolled_back",
                        "timestamp": datetime.now().isoformat(),
                        "path": str((cur_path.parent / original_name).absolute()),
                    }
                    rollback_results.append(rollback_result)
                    rec["rollback"] = True
                    config_db.update_change_record_rollback(
                        rec["path"], rec["original"], True
                    )
                    for change in changes:
                        if (
                            change.get("status") == "success"
                            and change.get("type") != "rename"
                        ):
                            rollback_type = "subtitle_rollback"
                            if change.get("type") == "subtitle_rename":
                                rollback_type = "subtitle_rollback"
                                rolled_back_sub_cnt += 1
                            elif change.get("type") == "audio_rename":
                                rollback_type = "audio_rollback"
                                rolled_back_audio_cnt += 1
                            elif change.get("type") == "picture_rename":
                                rollback_type = "picture_rollback"
                                rolled_back_picture_cnt += 1
                            rollback_result = {
                                "type": rollback_type,
                                "original": change["original"],
                                "new": change["new"],
                                "status": "rolled_back",
                                "timestamp": datetime.now().isoformat(),
                                "path": str(
                                    (cur_path.parent / change["new"]).absolute()
                                ),
                            }
                            rollback_results.append(rollback_result)
                            subtitle_path = str(
                                (cur_path.parent / change["original"]).absolute()
                            )
                            config_db.update_change_record_rollback(
                                subtitle_path, change["new"], True
                            )
                    nfo_changes = self._delete_old_nfo(
                        season_dir, Path(rec["new"]).stem, nfo_changes
                    )
                else:
                    rollback_results.append(
                        {
                            "type": "rollback",
                            "original": rec["new"],
                            "new": original_name,
                            "status": "failed",
                            "error": "重命名失败",
                            "timestamp": datetime.now().isoformat(),
                            "path": rec["path"],
                        }
                    )
            except Exception as exc:
                self.logger.exception("Rollback failed")
                rollback_results.append(
                    {
                        "type": "rollback",
                        "original": rec["new"],
                        "new": original_name,
                        "status": "failed",
                        "error": str(exc),
                        "timestamp": datetime.now().isoformat(),
                        "path": rec["path"],
                    }
                )
        try:
            nfo_delete_records = self._get_new_change_record(
                season_dir, media_type, nfo_changes
            )
            try:
                config_db.add_change_records(nfo_delete_records)
            except Exception as e:
                self.logger.error(f"Failed to save and delete records to database: {e}")
            self._write_all_change_records(season_dir.absolute())
        except Exception as exc:
            self.logger.exception("Failed to update the rename_record.json")
        if rollback_results:
            existing = []
            if rollback_record_path.exists():
                try:
                    existing = json.loads(
                        rollback_record_path.read_text(encoding="utf-8")
                    )
                except Exception:
                    pass
            rollback_result = {
                "status": "completed",
                "processed": rolled_back_file_cnt
                + rolled_back_sub_cnt
                + rolled_back_picture_cnt
                + rolled_back_audio_cnt,
                "renamed": rolled_back_file_cnt,
                "renamed_subtitle": rolled_back_sub_cnt,
                "renamed_audio": rolled_back_audio_cnt,
                "renamed_picture": rolled_back_picture_cnt,
                "deleted_nfo": len(nfo_delete_records),
                "timestamp": datetime.now().isoformat(),
                "target": sub_path,
                "scan_type": "rollback",
            }
            config_db.add_scan_history(rollback_result)
            try:
                all_records = existing + rollback_results
                rollback_record_path.write_text(
                    json.dumps(all_records, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                self.logger.exception("Writing rollback.json failed")

        result = {
            "success": True,
            "rolled_back_file": rolled_back_file_cnt,
            "rolled_back_sub": rolled_back_sub_cnt,
            "results": rollback_results,
        }
        code = 200
        return {"result": result, "code": code}

    def scan_and_rename(self, sub_path: Optional[str] = None) -> Dict:
        self.current_sub_path = sub_path
        self.logger.info(
            f"Starting media scan and rename process. Target: '{sub_path or 'ALL'}'"
        )
        processed_files_list: List[Dict] = []
        total, renamed = 0, 0
        renamed_subtitle = 0
        renamed_audio = 0
        renamed_picture = 0
        deleted_nfo = 0
        video_exts = {
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
        finished_statuses = {STATUS_RENAMED, STATUS_WHITELIST, STATUS_SKIP}
        root_path = (
            self.media_path if sub_path is None else (self.media_path / sub_path)
        )
        if not root_path.exists():
            msg = f"媒体路径不存在: {root_path}"
            self.logger.error(msg)
            return {
                "status": "error",
                "message": msg,
                "processed": 0,
                "renamed": 0,
                "target": str(sub_path or "ALL"),
                "timestamp": datetime.now().isoformat(),
            }

        if self._is_season_dir(root_path):
            media_type = self._extract_media_type(root_path)
            self.logger.info(
                f"Processing season directory: {root_path} (Media type: {media_type})"
            )
            p_list, t_inc, r_inc, s_inc, a_inc, p_inc, n_inc = self._scan_single_season(
                season_dir=root_path,
                parent_show=root_path.parent,
                video_exts=video_exts,
                media_type_name=media_type,
            )
            processed_files_list.extend(p_list)
            total += t_inc
            renamed += r_inc
            renamed_subtitle += s_inc
            renamed_audio += a_inc
            renamed_picture += p_inc
            deleted_nfo += n_inc
        elif self._is_show_dir(root_path):
            self.logger.info(f"Processing show directory: {root_path}")
            for season_dir in root_path.iterdir():
                media_type = self._extract_media_type(root_path)
                self.logger.info(
                    f"Processing season: {season_dir} (Media type: {media_type})"
                )
                if season_dir.is_dir() and self._is_season_dir(season_dir):
                    p_list, t_inc, r_inc, s_inc, a_inc, p_inc, n_inc = (
                        self._scan_single_season(
                            season_dir=season_dir,
                            parent_show=root_path,
                            video_exts=video_exts,
                            media_type_name=media_type,
                        )
                    )
                    processed_files_list.extend(p_list)
                    total += t_inc
                    renamed += r_inc
                    renamed_subtitle += s_inc
                    renamed_audio += a_inc
                    renamed_picture += p_inc
                    deleted_nfo += n_inc
        else:
            self.logger.info(f"Processing base directory: {root_path}")
            for show_dir, season_dir in self._iter_season_dirs(root_path):
                media_type = self._extract_media_type(season_dir)
                p_list, t_inc, r_inc, s_inc, a_inc, p_inc, n_inc = (
                    self._scan_single_season(
                        season_dir=season_dir,
                        parent_show=show_dir,
                        video_exts=video_exts,
                        media_type_name=media_type,
                    )
                )
                processed_files_list.extend(p_list)
                total += t_inc
                renamed += r_inc
                renamed_subtitle += s_inc
                renamed_audio += a_inc
                renamed_picture += p_inc
                deleted_nfo += n_inc
        unrenamed_files = [
            {"path": f["path"]}
            for f in processed_files_list
            if f.get("status") not in finished_statuses
        ]
        self.logger.info(
            f"Scan completed: {total} files processed, {renamed} files renamed."
        )
        if self._pending_change_records:
            try:
                self.logger.info(f"开始保存记录")
                config_db.add_change_records(self._pending_change_records)
                self.logger.info("保存成功")

            except Exception as e:
                self.logger.error("批量保存变更记录失败: %s", e)
            for season_dir in self._seasons_to_update:
                self._write_all_change_records(season_dir.absolute())
            self._pending_change_records = []
            self._seasons_to_update = set()
        return {
            "status": "completed",
            "processed": total,
            "renamed": renamed,
            "renamed_subtitle": renamed_subtitle,
            "renamed_audio": renamed_audio,
            "renamed_picture": renamed_picture,
            "deleted_nfo": deleted_nfo,
            "unrenamed_count": len(unrenamed_files),
            "unrenamed_files": unrenamed_files,
            "timestamp": datetime.now().isoformat(),
            "target": str(sub_path or "ALL"),
        }

    def _queue_change_records(
        self, season_dir: Path, media_type: str, changes: List[Dict]
    ):
        if not changes:
            return

        processed = self._get_new_change_record(season_dir, media_type, changes)
        self._pending_change_records.extend(processed)
        self._seasons_to_update.add(season_dir)

    def _delete_old_nfo(self, season_dir, old_stem, changes):
        nfo_path = season_dir / f"{old_stem}.nfo"
        for candidate in [nfo_path, nfo_path.with_suffix(".NFO")]:
            if candidate.exists():
                try:
                    candidate.unlink()
                    changes.append(
                        {
                            "type": "nfo_delete",
                            "original": candidate.name,
                            "status": "success",
                            "error": None,
                        }
                    )
                except Exception as e:
                    changes.append(
                        {
                            "type": "nfo_delete",
                            "original": candidate.name,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

        return changes

    def _extract_media_type(self, any_path: Path) -> str:
        try:
            return any_path.relative_to(self.media_path).parts[0]
        except ValueError:
            return any_path.parent.name

    def _iter_season_dirs(self, base_dir: Path):
        for entry in base_dir.iterdir():
            if not entry.is_dir():
                continue
            if self._is_season_dir(entry):
                yield entry.parent, entry
            else:
                yield from self._iter_season_dirs(entry)

    def _is_season_dir(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        return any(pat.search(path.name) for pat in SEASON_PATTERNS)

    def _is_show_dir(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        return any(self._is_season_dir(d) for d in path.iterdir() if d.is_dir())

    def _scan_single_season(
        self,
        season_dir: Path,
        parent_show: Path,
        video_exts: Set[str],
        media_type_name: str,
    ) -> Tuple[List[Dict], int, int, int, int]:
        processed_files_list: List[Dict] = []
        total, renamed, renamed_sub, deleted_nfo, renamed_audio, renamed_picture = (
            0,
            0,
            0,
            0,
            0,
            0,
        )
        processed_files = self._season_processed_set(season_dir)
        season_num_hint = self._get_season_from_path(season_dir)
        season_changes: List[Dict] = []

        for f in season_dir.iterdir():
            abs_path = str(f.absolute())
            if (
                not f.is_file()
                or f.suffix.lower() not in video_exts
                or (abs_path, f.name) in processed_files
            ):
                continue
            file_info, changes, renamed_flag = self._process_episode_file(
                f, season_num_hint, abs_path
            )
            processed_files_list.append(file_info)
            season_changes.extend(changes)
            if (
                file_info.get("status") != STATUS_WHITELIST
                and file_info.get("status") != STATUS_SKIP
            ):
                total += 1
            if renamed_flag:
                renamed += 1
        if self.current_sub_path is not None:
            orphan_changes = self._sync_orphan_subtitles(season_dir)
            self.logger.info(
                f"Orphan subtitles processed: {len(orphan_changes)} changes."
            )
            if orphan_changes:
                season_changes.extend(orphan_changes)
        if season_changes:
            self._queue_change_records(season_dir, media_type_name, season_changes)
            for change in season_changes:
                if (
                    change.get("type") in ADDITION_CHANGE
                    and change.get("status") == "success"
                ):
                    total += 1
            counts = self._count_success_by_type(season_changes)
            renamed = counts.get("rename", 0)
            renamed_sub = counts.get("subtitle_rename", 0)
            renamed_audio = counts.get("audio_rename", 0)
            renamed_picture = counts.get("picture_rename", 0)
            deleted_nfo = counts.get("nfo_delete", 0)
        return (
            processed_files_list,
            total,
            renamed,
            renamed_sub,
            renamed_audio,
            renamed_picture,
            deleted_nfo,
        )

    def _process_episode_file(
        self,
        file_path: Path,
        season_num_hint: Optional[int],
        abs_path: str,
    ) -> Tuple[Dict, List[Dict], bool]:
        if WhitelistLoader.is_whitelisted(abs_path):
            return (
                {"path": abs_path, "status": STATUS_WHITELIST},
                [],
                False,
            )
        file_info = {
            "path": abs_path,
            "status": STATUS_UNPROCESSED,
        }
        episode_info = self._extract_episode_info(file_path.name)
        if episode_info is None:
            file_info.update(
                {"status": STATUS_UNMATCHED, "reason": "no_episode_and_season_info"}
            )
            return file_info, [], False

        season_num, ep_num, match_span = episode_info
        effective_season = season_num or season_num_hint
        new_name = self._generate_new_filename(
            file_path.name, effective_season, ep_num, match_span
        )
        if new_name == file_path.name:
            file_info.update({"status": STATUS_SKIP, "reason": "no_rename_needed"})
            changes = self._build_skip_record(file_path.name)
            return file_info, changes, False
        changes = self._rename_file_and_subtitles(file_path, new_name)
        if self._count_success_renames(changes):
            file_info.update(
                {
                    "status": STATUS_RENAMED,
                    "original_name": file_path.name,
                    "new_name": new_name,
                }
            )
            return file_info, changes, True
        else:
            file_info.update(
                {
                    "status": STATUS_FAILED,
                    "errors": [c.get("error") for c in changes if c.get("error")],
                }
            )
            return file_info, changes, False


if __name__ == "__main__":
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else MEDIA_PATH
    print(
        json.dumps(EmbressRenamer(root).scan_and_rename(), ensure_ascii=False, indent=2)
    )
