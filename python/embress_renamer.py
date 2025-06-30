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
import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set, Union
from database import config_db
import time
from logging.handlers import RotatingFileHandler


LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


STATUS_RENAMED = "renamed"
STATUS_FAILED = "failed"
STATUS_SKIP = "skip"
STATUS_UNMATCHED = "unmatched"
STATUS_WHITELIST = "whitelisted"
STATUS_UNPROCESSED = "unprocessed"

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

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("EmbressRenamer")

        if not logger.handlers:  # 只初始化一次
            logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
            logger.propagate = False  # 阻止向 root 传播导致重复

            # 文件 handler
            LOGS_PATH.mkdir(parents=True, exist_ok=True)
            log_file = LOGS_PATH / f"emby_renamer_{datetime.datetime.now():%Y%m%d}.log"
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8"
            )
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            # 控制台 handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        return logger

    def _extract_episode_info(
        self, filename: str
    ) -> Optional[Tuple[Optional[int], int]]:
        p_cfg = RegexLoader.patterns()
        # (季,集)
        for pat in p_cfg.get("season_episode", []):
            if m := re.search(pat, filename, re.I):
                return int(m.group(1)), int(m.group(2))

        # 仅集数
        for pat in p_cfg.get("episode_only", []):
            if pat == r"\[(\d{1,3})\]":
                ms = list(re.finditer(pat, filename))
                if ms:
                    return None, int(ms[-1].group(1))
            elif m := re.search(pat, filename, re.I):
                return None, int(m.group(1))
        return None

    def _get_season_from_path(self, file_path: Path) -> Optional[int]:
        for part in file_path.parts:
            if m := re.search(r"[Ss]eason\s*(\d{1,2})", part, re.I):
                return int(m.group(1))
        return None

    def _generate_new_filename(
        self, original: str, season: Optional[int], episode: int
    ) -> str:
        season_fmt = season if season is not None else 1
        new_seg = f"S{season_fmt:02d}E{episode:02d}"
        new = original

        # 0) 已含 [SxxEyy] → 不动
        if re.search(rf"\[{new_seg}\]", new, re.I):
            return new

        # 1-A) 裸露的 SxxEyy → 加方括号（末尾加空格，稍后清理）
        full_pat = rf"S{season_fmt:02d}E{episode:02d}"
        new2 = re.sub(full_pat, f" [{new_seg}] ", new, count=1, flags=re.I)
        if new2 != new:
            return self._normalize_filename(new2)

        # 1-B) “- 01 …” / “- 01 (”
        new2 = re.sub(
            r"-\s*\d{1,3}(?=\s+(?:\[|\(|[A-Za-z]))",
            f"- [{new_seg}] ",
            new,
            count=1,
            flags=re.I,
        )
        if new2 != new:
            return self._normalize_filename(new2)

        # 1-C) “ 10 (” 型
        new2 = re.sub(
            r"\s+\d{1,3}(?=\s*\()",
            f" [{new_seg}]",
            new,
            count=1,
        )
        if new2 != new:
            return self._normalize_filename(new2)

        # 2) “ 01[” 型
        new2 = re.sub(r"\s+\d{1,3}(?=\s*\[)", f" [{new_seg}]", new, count=1)
        if new2 != new:
            return self._normalize_filename(new2)

        # 3) 最后一个 “[数字]”
        matches = list(re.finditer(r"\[(\d{1,3})\]", new))
        if matches:
            s, e = matches[-1].span()
            new2 = new[:s] + f"[{new_seg}]" + new[e:]
            return self._normalize_filename(new2)

        # 4) “- 01 -”
        new2 = re.sub(r"-(\s*)\d{1,3}(\s*)-", rf"-\1[{new_seg}]\2-", new, count=1)
        if new2 != new:
            return self._normalize_filename(new2)

        # 5) Episode / Eyy（注意避免 SxxEyy 被命中两次）
        new2 = re.sub(r"(?<!S\d{2})E\d{1,3}", new_seg, new, count=1, flags=re.I)
        if new2 != new:
            return self._normalize_filename(new2)

        # 6) 默认：加在扩展名前
        p = Path(original)
        new2 = f"{p.stem} [{new_seg}]{p.suffix}"
        return self._normalize_filename(new2)

    def _normalize_filename(self, name: str) -> str:
        """清理多余空格、点号前空格等问题"""
        name = re.sub(r"\s{2,}", " ", name)  # 连续空格
        name = re.sub(r"\s+\.", ".", name)  # 点号前空格
        return name.strip()

    def _rename_file_and_subtitles(self, file_path: Path, new_name: str) -> List[Dict]:
        """重命名主文件，并同步处理字幕和 nfo"""
        changes: List[Dict] = []
        old_stem = file_path.stem
        new_stem = Path(new_name).stem
        new_file_path = file_path.parent / new_name
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

        subtitle_exts = {".ass", ".srt", ".vtt", ".sub"}
        for sub in file_path.parent.iterdir():
            if not sub.is_file() or sub.suffix.lower() not in subtitle_exts:
                continue
            if not re.match(re.escape(old_stem) + r"(\.|$)", sub.stem, re.I):
                continue

            remainder = sub.name[len(old_stem) :]
            new_sub_name = f"{new_stem}{remainder}"
            new_sub_path = sub.parent / new_sub_name
            if new_sub_path.exists():
                continue

            try:
                sub.rename(new_sub_path)
                changes.append(
                    {
                        "type": "subtitle_rename",
                        "original": sub.name,
                        "new": new_sub_name,
                        "status": "success",
                    }
                )
            except Exception as e:
                changes.append(
                    {
                        "type": "subtitle_rename",
                        "original": sub.name,
                        "new": new_sub_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )

        nfo_path = file_path.parent / f"{old_stem}.nfo"
        for candidate in [nfo_path, nfo_path.with_suffix(".NFO")]:
            if candidate.exists():
                try:
                    candidate.unlink()
                    changes.append(
                        {
                            "type": "nfo_delete",
                            "original": candidate.name,
                            "status": "success",
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

    def _save_change_record(
        self, season_dir: Path, media_type: str, changes: List[Dict]
    ):
        """合并写入 rename_record.json，兼容旧记录无 path 的情况"""
        record_file = season_dir / "rename_record.json"
        existing: List[Dict] = []

        if record_file.exists():
            try:
                existing = json.loads(record_file.read_text("utf-8"))
            except Exception:
                self.logger.warning(f"读取历史记录失败: {record_file}")

        existing_updated = False
        for item in existing:
            if "path" not in item:
                item["path"] = str(
                    (season_dir / item.get("new", item.get("original", ""))).absolute()
                )
                existing_updated = True

        if existing_updated:
            try:
                record_file.write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass
        for c in changes:
            c["timestamp"] = datetime.datetime.now().isoformat()
            c["media_type"] = media_type
            c["path"] = str(
                (season_dir / c.get("new", c.get("original", ""))).absolute()
            )

        merged: Dict[Tuple[str, str], Dict] = {
            (item["path"], item.get("original", "")): item for item in existing
        }
        for c in changes:
            key = (c["path"], c.get("original", ""))
            if (
                key in merged
                and c["status"] == "skip"
                and merged[key]["status"] != "skip"
            ):
                continue
            merged[key] = c

        record_file.write_text(
            json.dumps(list(merged.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _season_processed_set(self, season_dir: Path) -> Set[Tuple[str, str]]:
        rec_file = season_dir / "rename_record.json"
        if not rec_file.exists():
            return set()

        try:
            data = json.loads(rec_file.read_text("utf-8"))
        except Exception:
            return set()

        processed: Set[Tuple[str, str]] = set()
        updated = False

        for item in data:
            if "path" not in item:
                derived = str(
                    (season_dir / item.get("new", item.get("original", ""))).absolute()
                )
                item["path"] = derived
                updated = True
            processed.add((item["path"], item.get("new", "")))
        if updated:
            try:
                rec_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

        return processed

    @staticmethod
    def _count_success_renames(changes: List[Dict]) -> int:
        return sum(
            1
            for c in changes
            if c.get("type") == "rename" and c.get("status") == "success"
        )

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

    def scan_and_rename(self, sub_path: Optional[str] = None) -> Dict:
        processed_files_list: List[Dict] = []
        total, renamed = 0, 0
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
                "timestamp": datetime.datetime.now().isoformat(),
            }
        if self._is_season_dir(root_path):
            media_type = self._extract_media_type(root_path)
            p_list, t_inc, r_inc = self._scan_single_season(
                season_dir=root_path,
                parent_show=root_path.parent,
                video_exts=video_exts,
                media_type_name=media_type,
            )
            processed_files_list.extend(p_list)
            total += t_inc
            renamed += r_inc
        elif self._is_show_dir(root_path):
            for season_dir in root_path.iterdir():
                media_type = self._extract_media_type(root_path)
                if season_dir.is_dir() and self._is_season_dir(season_dir):
                    p_list, t_inc, r_inc = self._scan_single_season(
                        season_dir=season_dir,
                        parent_show=root_path,
                        video_exts=video_exts,
                        media_type_name=media_type,
                    )
                    processed_files_list.extend(p_list)
                    total += t_inc
                    renamed += r_inc
        else:
            for show_dir, season_dir in self._iter_season_dirs(root_path):
                media_type = self._extract_media_type(season_dir)
                p_list, t_inc, r_inc = self._scan_single_season(
                    season_dir=season_dir,
                    parent_show=show_dir,
                    video_exts=video_exts,
                    media_type_name=media_type,
                )
                processed_files_list.extend(p_list)
                total += t_inc
                renamed += r_inc
        unrenamed_files = [
            {"path": f["path"]}
            for f in processed_files_list
            if f.get("status") not in finished_statuses
        ]
        return {
            "status": "completed",
            "processed": total,
            "renamed": renamed,
            "unrenamed_count": len(unrenamed_files),
            "unrenamed_files": unrenamed_files,
            "timestamp": datetime.datetime.now().isoformat(),
            "target": str(sub_path or "ALL"),
        }

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
    ) -> Tuple[List[Dict], int, int]:
        processed_files_list: List[Dict] = []
        total, renamed = 0, 0

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
            total += 1
            if renamed_flag:
                renamed += 1
        if season_changes:
            self._save_change_record(season_dir, media_type_name, season_changes)
        return processed_files_list, total, renamed

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

        season_num, ep_num = episode_info
        effective_season = season_num or season_num_hint
        new_name = self._generate_new_filename(file_path.name, effective_season, ep_num)
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
