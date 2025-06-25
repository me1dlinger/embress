"""
/**
 * @author: Meidlinger
 * @date: 2025-06-24
 */
"""

import os
import re
import json
import logging
import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional,Set

LOGS_DIR = r'/app/python/log'
MEDIA_DIR =  os.getenv('MEDIA_PATH', '/app/media')
REGEX_PATH =  os.getenv('REGEX_PATH', 'regex_patterns.json')

class RegexLoader:
    """负责把正则表达式从 JSON 文件中读取进来（热加载）"""
    _cache_mtime: float = 0.0
    _patterns: Dict[str, List[str]] = {}

    @classmethod
    def patterns(cls) -> Dict[str, List[str]]:
        fp = Path(REGEX_PATH)
        # 文件不存在则写入默认模板
        if not fp.exists():
            fp.write_text(json.dumps({
                "season_episode": [],
                "episode_only": []
            }, indent=2, ensure_ascii=False), encoding='utf-8')

        mtime = fp.stat().st_mtime
        if mtime != cls._cache_mtime:
            cls._patterns = json.loads(fp.read_text(encoding='utf-8'))
            cls._cache_mtime = mtime
        return cls._patterns

class EmbyRenamer:
    def __init__(self, media_path: str):
        self.media_path = Path(media_path)
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger('EmbyRenamer')
        logger.setLevel(logging.INFO)
        log_dir = Path(LOGS_DIR)
        log_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(
            log_dir / f'emby_renamer_{datetime.datetime.now():%Y%m%d}.log',
            encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        if not logger.handlers:
            logger.addHandler(fh)
            logger.addHandler(logging.StreamHandler())
        return logger

    def _extract_episode_info(self, filename: str) -> Optional[Tuple[Optional[int], int]]:
        p_cfg = RegexLoader.patterns()
        # (季,集)
        for pat in p_cfg.get("season_episode", []):
            if (m := re.search(pat, filename, re.I)):
                return int(m.group(1)), int(m.group(2))

        # 仅集数
        for pat in p_cfg.get("episode_only", []):
            if pat == r'\[(\d{1,3})\]':
                ms = list(re.finditer(pat, filename))
                if ms:
                    return None, int(ms[-1].group(1))
            elif (m := re.search(pat, filename, re.I)):
                return None, int(m.group(1))
        return None

    def _get_season_from_path(self, file_path: Path) -> Optional[int]:
        for part in file_path.parts:
            if (m := re.search(r'[Ss]eason\s*(\d{1,2})', part, re.I)):
                return int(m.group(1))
        return None

    def _generate_new_filename(self, original: str,
                               season: Optional[int],
                               episode: int) -> str:
        season_fmt = season if season is not None else 1
        new_seg = f"S{season_fmt:02d}E{episode:02d}"
        new = original

        # 0) 已含 [SXXEYY] → 不动
        if re.search(rf'\[{new_seg}\]', new, re.I):
            return new

        # 1-A) 裸露的 SxxEyy → 加方括号
        full_pat = rf'S{season_fmt:02d}E{episode:02d}'
        new2 = re.sub(full_pat, f' [{new_seg}] ', new, count=1, flags=re.I)
        if new2 != new:
            return re.sub(r'\s{2,}', ' ', new2)

        # 1-B) 处理 “- 01 …” / “- 01 OVA …” / “- 01 (” 等形式
        new2 = re.sub(
            r'-\s*\d{1,3}(?=\s+(?:\[|\(|[A-Za-z]))',
            f'- [{new_seg}] ',
            new,
            count=1,
            flags=re.I
        )
        if new2 != new:
            return re.sub(r'\s{2,}', ' ', new2)

        # 2) " 01[" 形式
        new2 = re.sub(r'\s+\d{1,3}(?=\s*\[)', f' [{new_seg}]', new, count=1)
        if new2 != new:
            return new2

        # 3) 最后一个 “[数字]”
        matches = list(re.finditer(r'\[(\d{1,3})\]', new))
        if matches:
            s, e = matches[-1].span()
            return new[:s] + f'[{new_seg}]' + new[e:]

        # 4) “- 01 -”
        new2 = re.sub(r'-(\s*)\d{1,3}(\s*)-', rf'-\1[{new_seg}]\2-', new, count=1)
        if new2 != new:
            return new2

        # 5) Episode / Eyy
        new2 = re.sub(r'(?<!S\d{2})E\d{1,3}', new_seg, new, count=1, flags=re.I)
        if new2 != new:
            return new2

        # 6) 默认：加在扩展名前
        p = Path(original)
        return f"{p.stem} [{new_seg}]{p.suffix}"

    def _rename_file_and_subtitles(self, file_path: Path, new_name: str) -> List[Dict]:
        changes: List[Dict] = []
        new_file = file_path.parent / new_name
        if file_path != new_file and not new_file.exists():
            try:
                file_path.rename(new_file)
                changes.append({'type': 'rename',
                                'original': file_path.name,
                                'new': new_name,
                                'status': 'success'})
                self.logger.info(f"重命名: {file_path.name} -> {new_name}")
            except Exception as e:
                changes.append({'type': 'rename',
                                'original': file_path.name,
                                'new': new_name,
                                'status': 'failed',
                                'error': str(e)})
                self.logger.error(f"重命名失败: {e}")
                return changes

        subtitle_exts = ['.ass', '.srt', '.vtt', '.sub']
        lang_suffixes = ['', '.chs', '.cht', '.eng', '.jpn']
        for ext in subtitle_exts:
            for lang in lang_suffixes:
                old = file_path.parent / f"{file_path.stem}{lang}{ext}"
                if old.exists():
                    new_sub = file_path.parent / f"{Path(new_name).stem}{lang}{ext}"
                    if not new_sub.exists():
                        try:
                            old.rename(new_sub)
                            changes.append({'type': 'subtitle_rename',
                                            'original': old.name,
                                            'new': new_sub.name,
                                            'status': 'success'})
                        except Exception as e:
                            changes.append({'type': 'subtitle_rename',
                                            'original': old.name,
                                            'new': new_sub.name,
                                            'status': 'failed',
                                            'error': str(e)})
        return changes

    def _save_change_record(self, season_dir: Path, media_type: str, changes: List[Dict]):
        """保存变更记录，添加媒体类型信息"""
        if not changes:
            return
            
        record = season_dir / 'rename_record.json'
        try:
            existing = json.loads(record.read_text(encoding='utf-8')) if record.exists() else []
        except Exception:
            existing = []
            
        for c in changes:
            c['timestamp'] = datetime.datetime.now().isoformat()
            c['media_type'] = media_type
            
        existing.extend(changes)
        record.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')

    def _season_processed_set(self, season_dir: Path) -> Set[str]:
        """已处理文件名集合（读取 rename_record.json）"""
        record = season_dir / 'rename_record.json'
        if record.exists():
            try:
                data = json.loads(record.read_text('utf-8'))
                return {item.get("new") for item in data if "new" in item}
            except Exception:
                pass
        return set()
    @staticmethod
    def _count_success_renames(changes: List[Dict]) -> int:
        """统计真正成功的主文件改名次数"""
        return sum(
            1 for c in changes
            if c.get("type") == "rename" and c.get("status") == "success"
        )
    @staticmethod
    def _build_skip_record(file_name: str) -> List[Dict]:
        """构造一条 'skip' 记录，保持字段兼容"""
        return [{
            "type": "rename",
            "original": file_name,
            "new": file_name,
            "status": "skip"
        }]
    def scan_and_rename(self, sub_path: Optional[str] = None) -> Dict:
        total, renamed = 0, 0
        root_path = self.media_path if sub_path is None else (self.media_path / sub_path)
        if not root_path.exists():
            msg = f"媒体路径不存在: {root_path}"
            self.logger.error(msg)
            return {'status': 'error', 'message': msg, 'processed': 0, 'renamed': 0,
                    'target': str(sub_path or 'ALL')}
        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.ts', '.m2ts'}
        if sub_path and "season" in root_path.name.lower():
            # 直接处理季目录下的文件
            processed_files = self._season_processed_set(root_path)
            media_type = root_path.parent.parent.name  # Anime
            season_num = self._get_season_from_path(root_path)  # 1
            
            for file in root_path.iterdir():
                if file.is_file() and file.suffix.lower() in video_exts:
                    if file.name in processed_files: 
                        continue
                        
                    total += 1
                    season_info = self._extract_episode_info(file.name)
                    if season_info is None: 
                        continue
                        
                    file_season, ep = season_info
                    effective_season = file_season or season_num
                    new_name = self._generate_new_filename(file.name,
                                                           effective_season, ep)
                    if new_name != file.name:
                        # 真的要改名
                        changes = self._rename_file_and_subtitles(file, new_name)
                    else:
                        # 无需改名，写 skip
                        changes = self._build_skip_record(file.name)

                    self._save_change_record(root_path, media_type, changes)
                    renamed += self._count_success_renames(changes)
        # 四层目录：媒体类型 → 节目 → 季 → 文件
        else:
            for media_type_dir in self.media_path.iterdir():
                if not media_type_dir.is_dir():
                    continue
                show_dirs = media_type_dir.iterdir()
                for show_dir in show_dirs:
                    if not show_dir.is_dir():
                        continue
                    for season_dir in show_dir.iterdir():
                        if not season_dir.is_dir():
                            continue
                        processed_files = self._season_processed_set(season_dir)
                        season_num_path = self._get_season_from_path(season_dir)
                        season_changes: List[Dict] = []

                        for f in season_dir.iterdir():
                            if (not f.is_file() or f.suffix.lower() not in video_exts
                                    or f.name in processed_files):
                                continue
                            total += 1
                            info = self._extract_episode_info(f.name)
                            if info is None:
                                continue

                            season, ep = info
                            season = season or season_num_path
                            new_name = self._generate_new_filename(f.name, season, ep)

                            if new_name != f.name:
                                changes = self._rename_file_and_subtitles(f, new_name)
                            else:
                                changes = self._build_skip_record(f.name)

                            season_changes.extend(changes)
                            renamed += self._count_success_renames(changes)
                        if season_changes:
                            self._save_change_record(season_dir, media_type_dir.name, season_changes)
        self.logger.info(f"扫描完成: 处理 {total} 个文件，重命名 {renamed} 个文件")
        return {'status':'completed','processed':total,'renamed':renamed,
                'timestamp':datetime.datetime.now().isoformat(),
                'target': str(sub_path or 'ALL')}


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else MEDIA_DIR
    print(json.dumps(EmbyRenamer(root).scan_and_rename(),
                     ensure_ascii=False, indent=2))
