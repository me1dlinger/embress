"""
/**
 * 系统提示词加载器：所有提示词以独立文本文件维护，不内嵌于代码
 * @author: Meidlinger
 */
"""

import logging
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_cache: dict = {}


def load_prompt(name: str, default: str = "") -> str:
    """读取 prompts 目录下的提示词文件；缺失时回退 default 并记录警告"""
    if name in _cache:
        return _cache[name]
    path = PROMPTS_DIR / name
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logging.getLogger("PromptLoader").warning("读取提示词文件失败 %s: %s", path, exc)
        text = default
    _cache[name] = text
    return text