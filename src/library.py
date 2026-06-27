"""音乐库去重检查的统一抽象。

把"这首歌库里有没有"的判断收敛成一个 LibraryChecker 接口，
Navidrome 与 music-tag-web(MySQL) 各是一种实现；main 只面向接口，
新增后端时无需改动调用方。
"""

import logging
from typing import List, Optional

from config import Config
from navidrome import NavidromeClient
from mysql_check import MySQLChecker

logger = logging.getLogger(__name__)


class LibraryChecker:
    """库检查器接口。"""

    def exists(self, title: str, artists: List[str], album: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        """释放资源（如数据库连接）。默认无操作。"""
        pass


class NavidromeChecker(LibraryChecker):
    """基于 Navidrome(Subsonic API) 的库检查。"""

    def __init__(self, config: Config):
        self.client = NavidromeClient(
            config.get_nested("NAVIDROME.NAVIDROME_HOST"),
            config.get_nested("NAVIDROME.NAVIDROME_USER"),
            config.get_nested("NAVIDROME.NAVIDROME_PASS"),
        )

    def exists(self, title: str, artists: List[str], album: str) -> bool:
        return self.client.navidrome_song_exists(title, artists, album).get("exists", False)


class MusicTagWebChecker(LibraryChecker):
    """基于 music-tag-web 的 MySQL 库检查（连接生命周期收在内部）。"""

    def __init__(self, config: Config):
        self.checker = MySQLChecker(config)
        self.checker.open_connection()

    def exists(self, title: str, artists: List[str], album: str) -> bool:
        return self.checker.check_song(title, artists)

    def close(self) -> None:
        self.checker.close_connection()


def make_library_checker(config: Config) -> Optional[LibraryChecker]:
    """根据配置启用情况返回对应的库检查器；都未启用返回 None。"""
    if config.is_enabled("NAVIDROME"):
        logger.info("启用 Navidrome 库检查，筛选不在库中的歌曲")
        return NavidromeChecker(config)
    if config.is_enabled("MUSIC-TAG-WEB"):
        logger.info("启用 music-tag-web(MySQL) 库检查，筛选不在库中的歌曲")
        return MusicTagWebChecker(config)
    logger.info("未启用任何库检查，仅检查本地是否已下载")
    return None
