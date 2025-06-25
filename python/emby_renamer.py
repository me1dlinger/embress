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
from typing import Dict, List, Tuple, Optional

LOGS_DIR = r'/app/python/logs'
MEDIA_DIR = os.getenv('MEDIA_PATH', r'/app/media')


class EmbyRenamer:
    def __init__(self, media_path: str):
        self.media_path = Path(media_path)
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger('EmbyRenamer')
        logger.setLevel(logging.INFO)

        log_dir = Path(LOGS_DIR)
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / f'emby_renamer_{datetime.datetime.now().strftime("%Y%m%d")}.log',
            encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(file_handler.formatter)

        if not logger.handlers:
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        return logger
    def _extract_episode_info(self, filename: str) -> Optional[Tuple[Optional[int], int]]:
        """返回 (season, episode)，若缺季则 season 为 None"""
        season_episode_patterns = [
            r'[Ss](\d{1,2})[Ee](\d{1,3})',
            r'第(\d{1,2})季.*?第(\d{1,3})集',
            r'Season\s*(\d{1,2}).*?Episode\s*(\d{1,3})',
            r'\[(\d{1,2})\]\[(\d{1,3})\]',
            r'-\s*(\d{1,2})\s*-\s*(\d{1,3})',
            r'\.(\d{1,2})\.(\d{1,3})\.',
        ]
        for p in season_episode_patterns:
            if (m := re.search(p, filename, re.I)):
                return int(m.group(1)), int(m.group(2))

        # 仅集数：最后一个 [数字] 优先
        episode_only_patterns = [
            r'\[(\d{1,3})\]',
            r'第(\d{1,3})集',
            r'Episode\s*(\d{1,3})',
            r'-\s*(\d{1,3})\s*-',
            r'E(\d{1,3})',
            r'-\s*(\d{1,3})(?=\s|\.|\[|$)',
            r'\s+(\d{1,3})(?=\s*\[)',
        ]
        for p in episode_only_patterns:
            if p == r'\[(\d{1,3})\]':
                ms = list(re.finditer(p, filename))
                if ms:
                    return None, int(ms[-1].group(1))
            elif (m := re.search(p, filename, re.I)):
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
        """
        把识别出的季/集片段就地替换为 [SXXEYY]，其余字符不动
        """
        season_fmt = season if season is not None else 1
        new_seg = f"S{season_fmt:02d}E{episode:02d}"
        new = original

        # 0) 已经含有 [SXXEYY] → 不动
        if re.search(rf'\[{new_seg}\]', new, re.I):
            return new

        # 1-A) ★ 若存在完整的 SxxEyy 片段（未加括号）→ 包裹方括号
        full_pat = rf'S{season_fmt:02d}E{episode:02d}'
        new2 = re.sub(full_pat, f'[{new_seg}]', new, count=1, flags=re.I)
        if new2 != new:
            return new2

        # 以下顺序保持原逻辑
        # 1-B) "- 01 [" 形式
        new2 = re.sub(r'-\s*\d{1,3}(?=\s*\[)', f'- [{new_seg}]', new, count=1)
        if new2 != new:
            return new2

        # 2) " 空格01[" 形式
        new2 = re.sub(r'\s+\d{1,3}(?=\s*\[)', f' [{new_seg}]', new, count=1)
        if new2 != new:
            return new2

        # 3) 最后一个 "[数字]" 形式
        matches = list(re.finditer(r'\[(\d{1,3})\]', new))
        if matches:
            s, e = matches[-1].span()
            return new[:s] + f'[{new_seg}]' + new[e:]

        # 4) "- 01 -" 形式
        new2 = re.sub(r'-(\s*)\d{1,3}(\s*)-', rf'-\1[{new_seg}]\2-', new, count=1)
        if new2 != new:
            return new2

        # 5) Episode / Eyy 形式（已避免重复）
        new2 = re.sub(r'(?<!S\d{2})E\d{1,3}', new_seg, new, count=1, flags=re.I)
        if new2 != new:
            return new2

        # 6) 加到扩展名前
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
            c['media_type'] = media_type  # 添加媒体类型信息
            
        existing.extend(changes)
        record.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    def scan_and_rename(self) -> Dict:
        total, renamed = 0, 0
        if not self.media_path.exists():
            msg = f"媒体路径不存在: {self.media_path}"
            self.logger.error(msg)
            return {'status': 'error', 'message': msg, 'processed': 0, 'renamed': 0}

        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.ts', '.m2ts'}

        # 扫描主目录下的所有子目录（媒体类型目录）
        for media_type_dir in self.media_path.iterdir():
            if not media_type_dir.is_dir():
                continue
                
            # 扫描媒体类型目录下的所有节目目录
            for show in media_type_dir.iterdir():
                if not show.is_dir():
                    continue
                    
                # 扫描节目目录下的所有季目录
                for season_dir in show.iterdir():
                    if not season_dir.is_dir():
                        continue
                        
                    # 从季目录路径中提取季信息
                    season_num_path = self._get_season_from_path(season_dir)
                    season_changes: List[Dict] = []
                    
                    # 处理季目录下的视频文件
                    for f in season_dir.iterdir():
                        if not f.is_file() or f.suffix.lower() not in video_exts:
                            continue
                            
                        total += 1
                        info = self._extract_episode_info(f.name)
                        if info is None:
                            continue
                            
                        season, ep = info
                        season = season if season is not None else season_num_path
                        new_name = self._generate_new_filename(f.name, season, ep)
                        
                        if new_name != f.name:
                            season_changes.extend(self._rename_file_and_subtitles(f, new_name))
                            renamed += 1

                    # 保存本季的变更记录
                    if season_changes:
                        self._save_change_record(season_dir, media_type_dir.name, season_changes)

        self.logger.info(f"扫描完成: 处理 {total} 个文件，重命名 {renamed} 个文件")
        return {'status': 'completed', 'processed': total,
                'renamed': renamed, 'timestamp': datetime.datetime.now().isoformat()}


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else MEDIA_DIR
    print(json.dumps(EmbyRenamer(root).scan_and_rename(),
                     ensure_ascii=False, indent=2))
