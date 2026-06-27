"""通用工具函数：被多个模块共享的纯函数（无外部依赖、无状态）。"""

import logging
from datetime import datetime
from typing import Dict, Union

logger = logging.getLogger(__name__)


# 时间范围上限：2100-12-31 23:59:59（毫秒级）
_MAX_TS_MS = 4102444799000

# 音质等级 -> 简短中文名（用于日志/通知展示）
QUALITY_DISPLAY_NAMES = {
    "standard": "标准",
    "exhigh": "极高",
    "lossless": "无损",
    "hires": "Hi-Res",
    "sky": "沉浸环绕声",
    "jyeffect": "高清环绕声",
    "jymaster": "超清母带",
}


def timestamp_to_date(timestamp: Union[int, str, None]) -> str:
    """将 10 位（秒级）或 11-13 位（毫秒级）时间戳转为 YYYY-MM-DD。

    无效输入（空值、非数字、超范围）一律返回空字符串。
    """
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return ""

    ts_len = len(str(abs(ts)))
    if ts_len == 10:
        ts_ms = ts * 1000          # 秒级 -> 毫秒级
    elif 11 <= ts_len <= 13:
        ts_ms = ts                 # 已是毫秒级
    else:
        return ""

    if not (0 <= ts_ms <= _MAX_TS_MS):
        return ""

    try:
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""


def format_file_size(size_bytes: int) -> str:
    """将字节数格式化为带单位的字符串，如 37.74MB。"""
    if not size_bytes:
        return "0B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    unit_index = 0
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.2f}{units[unit_index]}"


def quality_display_name(quality: str) -> str:
    """音质等级 -> 简短中文名，未知则原样返回。"""
    return QUALITY_DISPLAY_NAMES.get(quality, "未知品质")


def parse_cookie(cookie_str: str) -> Dict[str, str]:
    """把 cookie 字符串解析成 dict（支持分号或换行分隔，按第一个 = 切分）。"""
    if not cookie_str or not cookie_str.strip():
        logger.warning("Cookie 字符串为空，返回空字典")
        return {}

    cookie_str = cookie_str.strip()
    if ';' in cookie_str:
        pairs = cookie_str.split(';')
    elif '\n' in cookie_str:
        pairs = cookie_str.split('\n')
    else:
        pairs = [cookie_str]

    cookies: Dict[str, str] = {}
    for pair in pairs:
        pair = pair.strip()
        if not pair or '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        key, value = key.strip(), value.strip()
        if key and value:
            cookies[key] = value
    return cookies
