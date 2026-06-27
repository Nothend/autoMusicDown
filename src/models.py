"""共享数据模型：音质/格式枚举与下载相关数据类。"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class AudioFormat(Enum):
    """音频格式枚举"""
    MP3 = "mp3"
    FLAC = "flac"
    M4A = "m4a"
    UNKNOWN = "unknown"


class QualityLevel(Enum):
    """音质等级枚举"""
    STANDARD = "standard"  # 标准
    EXHIGH = "exhigh"      # 极高
    LOSSLESS = "lossless"  # 无损
    HIRES = "hires"        # Hi-Res
    SKY = "sky"            # 沉浸环绕声
    JYEFFECT = "jyeffect"  # 高清环绕声
    JYMASTER = "jymaster"  # 超清母带


@dataclass
class MusicInfo:
    """音乐信息数据类"""
    id: int
    name: str
    publishTime: str
    artists: List[str]  # 列表类型，存储多个艺术家
    album: str
    pic_url: str
    duration: int
    track_number: int
    download_url: str
    file_type: str
    file_size: int
    quality: str
    lyric: str = ""
    tlyric: str = ""


@dataclass
class DownloadResult:
    """下载结果数据类"""
    success: bool
    file_path: Optional[str] = None
    file_size: int = 0
    error_message: str = ""
    music_info: Optional[MusicInfo] = None
    data: Optional[Dict] = None
