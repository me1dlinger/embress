"""
/**
 * AI 重命名：OpenAI 兼容接口 + 目录绑定 + 预设提示词
 * @author: Meidlinger
 */
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from crypto_utils import decrypt
from database import config_db
from logging_utils import get_logger

LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
MEDIA_PATH = os.getenv("MEDIA_PATH", "./data/media")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "60"))
AI_MAX_FILES = int(os.getenv("AI_MAX_FILES", "80"))

# 默认系统提示词，可通过 AI_PROMPT 覆盖
DEFAULT_SYSTEM_PROMPT = """你是 Emby / Jellyfin / Plex 媒体库的文件整理专家。
你的任务：根据剧集名称、季数、一组待处理的视频文件名，以及该剧集已有的重命名示例，为每个文件生成符合 Emby 命名规范的新文件名。

命名规范：
1. 电视剧单集格式为 `剧名 - SxxEyy - 分集标题.扩展名`（分集标题可省略）。
2. 若历史示例使用了不同风格（例如 `剧名 - [SxxEyy] - 其他`），请严格沿用历史示例的风格。
3. 必须保留原文件的扩展名（如 .mkv、.mp4），以及集数标记之后的画质/来源标签（如 `[WebRip 1080p HEVC]`、`[BDRip]`）和字幕组标识。
4. 不要凭空编造无法确定的集数；只有能从文件名或历史中可靠推断时才给出结果。
5. 只替换/补齐集数标识，尽量少改动原文件名的其他部分。
6. 如果某个文件无法可靠识别，则不要返回它。

严格只输出 JSON，不要输出任何解释或 Markdown 代码块：
{"renames":[{"original":"原文件名","new":"新文件名"}],"confidence":0.0}"""


def normalize_binding_path(raw: str) -> str:
    """把绑定路径规范化为相对媒体根的 POSIX 路径，防止越权与不一致"""
    if raw is None:
        return ""
    text = str(raw).strip().replace("\\", "/").strip("/")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("绑定路径不合法")
    return "/".join(parts)


class AIClient:
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = (base_url or AI_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else AI_API_KEY
        self.model = model or AI_MODEL
        self.logger = get_logger(
            name="AIRenamer",
            log_dir=LOGS_PATH,
            base_name="ai_renamer",
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            to_console=True,
        )

    def chat(self, messages: List[Dict], model: Optional[str] = None) -> str:
        payload = json.dumps(
            {
                "model": model or self.model,
                "messages": messages,
                "temperature": 0.2,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=AI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> Optional[dict]:
    """从模型回复中稳健地提取 JSON 对象"""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def build_messages(
    show_name: str,
    media_type: str,
    season_name: str,
    filenames: List[str],
    history: List[Dict],
    custom_prompt: str = None,
) -> List[Dict]:
    system = (custom_prompt or os.getenv("AI_PROMPT") or DEFAULT_SYSTEM_PROMPT).strip()
    payload = {
        "media_type": media_type,
        "show_name": show_name,
        "season": season_name,
        "files": filenames,
        "history_examples": history,
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "请为以下待处理文件生成新文件名：\n"
            + json.dumps(payload, ensure_ascii=False),
        },
    ]


def sanitize_new_name(original: str, proposed: str) -> Optional[str]:
    """校验 AI 产出的文件名，非法则返回 None"""
    if not proposed:
        return None
    name = str(proposed).strip().strip('"').strip()
    if not name or name in (".", ".."):
        return None
    if any(sep in name for sep in ("/", "\\", "\n", "\r", "\0")):
        return None
    if Path(name).name != name:
        return None
    original_suffix = Path(original).suffix
    if Path(name).suffix.lower() != original_suffix.lower():
        return None
    if name == original:
        return None
    return name


class AIRenamer:
    def __init__(self, media_path: str = None):
        self.media_root = Path(media_path or MEDIA_PATH)

    @staticmethod
    def _env_config() -> Optional[Dict]:
        if not AI_BASE_URL:
            return None
        if AI_API_KEY or "localhost" in AI_BASE_URL or "127.0.0.1" in AI_BASE_URL:
            return {
                "name": "环境变量",
                "base_url": AI_BASE_URL,
                "api_key": AI_API_KEY,
                "model": AI_MODEL,
            }
        return None

    def _resolve(self, binding: Optional[Dict]) -> Optional[Dict]:
        """实际使用的供应商：绑定指定 > 默认供应商 > 环境变量"""
        provider = None
        if binding and binding.get("provider_id"):
            provider = config_db.get_ai_provider(binding["provider_id"])
        if not provider:
            provider = config_db.get_default_ai_provider()
        if provider:
            try:
                api_key = decrypt(provider.get("api_key") or "")
            except ValueError:
                api_key = ""
            return {
                "name": provider.get("name"),
                "base_url": provider.get("base_url"),
                "api_key": api_key,
                "model": (binding or {}).get("model")
                or provider.get("model")
                or AI_MODEL,
            }
        return self._env_config()

    @staticmethod
    def is_configured() -> bool:
        try:
            if config_db.get_ai_providers():
                return True
        except Exception:
            pass
        return AIRenamer._env_config() is not None

    def test(self, base_url: str, api_key: str = "", model: str = None):
        """连通性测试，返回 (ok, message)"""
        if not base_url:
            return False, "缺少 Base URL"
        probe_model = model or AI_MODEL
        try:
            client = AIClient(
                base_url=base_url, api_key=api_key or "", model=probe_model
            )
            reply = client.chat(
                [
                    {"role": "system", "content": "你是连通性探针，只回复 pong。"},
                    {"role": "user", "content": "ping"},
                ],
                model=probe_model,
            )
            snippet = (reply or "").strip().replace("\n", " ")[:40]
            return True, f"连接成功 · 模型 {probe_model} 响应：{snippet or '(空)'}"
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:200]
            except Exception:
                pass
            return False, f"HTTP {exc.code}：{detail or exc.reason}"
        except urllib.error.URLError as exc:
            return False, f"网络错误：{exc.reason}"
        except Exception as exc:
            return False, f"失败：{exc}"

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.media_root.resolve()).as_posix()
        except ValueError:
            return ""

    def get_binding(self, season_dir: Path) -> Optional[Dict]:
        """返回匹配该季度目录的 AI 绑定（最长前缀优先）"""
        rel = self._relative(season_dir)
        if not rel:
            return None
        best = None
        for binding in config_db.get_ai_bindings():
            if not binding.get("enabled"):
                continue
            bpath = binding.get("path") or ""
            if rel == bpath or rel.startswith(bpath + "/"):
                if best is None or len(bpath) > len(best.get("path") or ""):
                    best = binding
        return best

    def _history(self, media_type: str, show_name: str) -> List[Dict]:
        try:
            records = config_db.get_change_records_by_show(media_type, show_name, limit=40)
        except Exception:
            return []
        history = []
        for rec in records:
            if (
                rec.get("type") == "rename"
                and rec.get("status") == "success"
                and rec.get("original")
                and rec.get("new")
            ):
                history.append({"original": rec["original"], "new": rec["new"]})
        return history[:20]

    def propose(
        self,
        season_dir: Path,
        show_name: str,
        media_type: str,
        season_name: str,
        filenames: List[str],
    ) -> Dict[str, str]:
        """请求 AI 给出 {原文件名: 新文件名}；失败或无结果时返回空字典。"""
        if not filenames:
            return {}
        binding = self.get_binding(season_dir) or {}
        config = self._resolve(binding)
        if not config or not config.get("base_url"):
            return {}
        model = config["model"]
        filenames = filenames[:AI_MAX_FILES]
        try:
            client = AIClient(
                base_url=config["base_url"],
                api_key=config.get("api_key") or "",
                model=model,
            )
            messages = build_messages(
                show_name=show_name,
                media_type=media_type,
                season_name=season_name,
                filenames=filenames,
                history=self._history(media_type, show_name),
                custom_prompt=binding.get("prompt"),
            )
            raw = client.chat(messages, model=model)
            data = extract_json(raw) or {}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, ValueError) as exc:
            get_logger("AIRenamer", LOGS_PATH, "ai_renamer").error(
                "AI 重命名请求失败: %s", exc
            )
            return {}
        except Exception as exc:  # 兜底，绝不影响正则主流程
            get_logger("AIRenamer", LOGS_PATH, "ai_renamer").exception(
                "AI 重命名异常: %s", exc
            )
            return {}

        result: Dict[str, str] = {}
        for item in data.get("renames", []) if isinstance(data, dict) else []:
            original = item.get("original")
            new_name = sanitize_new_name(original or "", item.get("new"))
            if original in filenames and new_name:
                result[original] = new_name
        return result


ai_renamer = AIRenamer()