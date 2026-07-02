"""音乐库去重检查：统一接口 + 两个后端实现 + 工厂，集中在一个文件。

把"这首歌库里有没有"收敛成一个 LibraryChecker 接口，Navidrome(Subsonic API)
与 music-tag-web(MySQL) 各是一种实现；main 只面向接口，新增后端无需改动调用方。
两个后端零共享代码、依赖不同，但同属"库去重"职责，集中于此便于一处维护。
"""

import re
import hashlib
import secrets
import logging
from typing import List, Optional

import pymysql
from pymysql.cursors import DictCursor

from config import Config
from http_client import SESSION

logger = logging.getLogger(__name__)


class LibraryChecker:
    """库检查器接口。"""

    def exists(self, title: str, artists: List[str], album: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        """释放资源（如数据库连接）。默认无操作。"""
        pass


class NavidromeChecker(LibraryChecker):
    """基于 Navidrome(Subsonic API) 的库去重检查。

    只回答"这首歌是否已在库中"（非 MP3 才算存在；MP3 视为缺失，以便下载无损版本）。
    """

    def __init__(self, config: Config):
        self.logger = logging.getLogger(__name__)
        self.username = config.get_nested("NAVIDROME.NAVIDROME_USER") or ""
        self.password = config.get_nested("NAVIDROME.NAVIDROME_PASS") or ""
        # 建址只做一次，避免每次查询都重复清洗
        self.base_url = self._build_base_url(config.get_nested("NAVIDROME.NAVIDROME_HOST"))

    @staticmethod
    def _build_base_url(host: Optional[str]) -> str:
        """规范化主机地址：保留配置里的协议（不要把 https 实例降级为 http），
        未显式带协议时默认 http；无效则返回空串。"""
        if not host:
            return ""
        host = host.strip().rstrip('/')
        # 去掉协议后若无主机部分，视为无效
        if not re.sub(r'^https?://', '', host, flags=re.IGNORECASE):
            return ""
        return host if re.match(r'^https?://', host, re.IGNORECASE) else f"http://{host}"

    def _auth_params(self) -> dict:
        """Subsonic token 认证参数（避免明文密码出现在 URL/日志中）。"""
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{self.password}{salt}".encode("utf-8")).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "NeteaseDownloader",
            "f": "json",
        }

    @staticmethod
    def _get_file_type(item: dict) -> str:
        """提取文件类型，优先 suffix，其次按 mime_type 映射，最终 unknown。"""
        suffix = (item.get('suffix') or '').strip().lstrip('.').lower()
        if suffix:
            return suffix
        mime_map = {
            'audio/flac': 'flac',
            'audio/mpeg': 'mp3',
            'audio/wav': 'wav',
            'audio/aac': 'aac',
            'audio/ogg': 'ogg',
            'audio/x-m4a': 'm4a',
        }
        return mime_map.get((item.get('mime_type') or '').lower(), 'unknown')

    @staticmethod
    def _artist_matches(input_artists: List[str], nav_artist_lower: str) -> bool:
        """歌手匹配（双向子串）：输入任一歌手命中候选歌手串，或候选拆分后的某段
        命中输入歌手，即算匹配。无输入歌手时只要候选有歌手即视为匹配。"""
        if not input_artists:
            return bool(nav_artist_lower.strip())
        nav_split = [a.strip() for a in re.split(r'[\/,;]', nav_artist_lower) if a.strip()]
        for in_artist in input_artists:
            if in_artist in nav_artist_lower or any(seg in in_artist for seg in nav_split):
                return True
        return False

    def exists(self, title: str, artists: List[str], album: str = "") -> bool:
        """歌曲名完全相等 + 歌手匹配；命中若为 MP3 则跳过继续找，找到非 MP3 即 True。"""
        if not self.base_url:
            self.logger.debug("Navidrome 主机地址未配置或无效，跳过检查")
            return False
        if not self.username or not self.password:
            self.logger.error("Navidrome 用户名或密码未配置")
            return False

        artists_str = ' & '.join(artists) if artists else '未知艺术家'
        try:
            params = self._auth_params()
            params.update({"query": title.strip(), "type": "song", "songCount": 20})
            url = f"{self.base_url}/rest/search2"

            # 复用全局带重试/退避的 Session
            resp = SESSION.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            subsonic_resp = data.get("subsonic-response", {})
            if subsonic_resp.get("status") != "ok":
                self.logger.debug(f"Navidrome 响应状态非 ok: {subsonic_resp.get('status')}")
                return False

            candidates = subsonic_resp.get("searchResult2", {}).get("song", [])
            if not isinstance(candidates, list):
                candidates = [candidates]
            self.logger.debug(f"Navidrome 候选 {len(candidates)} 条: {title} - {artists_str}")

            title_target = title.strip().lower()
            input_artists = [a.strip().lower() for a in (artists or []) if a.strip()]

            for item in candidates:
                if str(item.get('title', "")).strip().lower() != title_target:
                    continue
                if not self._artist_matches(input_artists, str(item.get('artist', "")).strip().lower()):
                    continue
                # MP3 视为不存在，继续找其他格式（库标准为无损）
                if self._get_file_type(item) == "mp3":
                    self.logger.debug(f"匹配到但为 MP3，视为不存在: {title} - {artists_str}")
                    continue
                self.logger.debug(f"找到匹配（非 MP3）: {title} - {artists_str}")
                return True

            self.logger.debug(f"未找到非 MP3 匹配: {title} - {artists_str}")
            return False

        except Exception as e:
            self.logger.error(f"Navidrome 检查异常: {e}")
            return False


class MusicTagWebChecker(LibraryChecker):
    """基于 music-tag-web 的 MySQL 库去重检查（连接在构造时打开，close 时释放）。"""

    REQUIRED_KEYS = ["host", "port", "user", "password", "database"]

    def __init__(self, config: Config):
        self.logger = logging.getLogger(__name__)

        node = config.get("music-tag-web", {}) or {}
        missing_keys = [k for k in self.REQUIRED_KEYS if k not in node]
        if missing_keys:
            self.logger.error(f"MySQL配置缺少必要项: {missing_keys}")
            raise ValueError(f"MySQL配置不完整，缺少: {missing_keys}")
        self.host = node["host"]
        self.port = node["port"]
        self.user = node["user"]
        self.password = node["password"]
        self.database = node["database"]

        self.connection: Optional[pymysql.connections.Connection] = None
        self._open()

    def _open(self) -> None:
        """建立 MySQL 连接（已连接则跳过）。"""
        if self.connection and self.connection.open:
            return
        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                cursorclass=DictCursor,
                charset="utf8mb4",
            )
            self.logger.info(f"成功连接到MySQL数据库: {self.host}:{self.port}")
        except pymysql.MySQLError as e:
            self.logger.error(f"MySQL连接失败: {str(e)}")
            raise ConnectionError(f"MySQL连接失败: {str(e)}")

    def close(self) -> None:
        if self.connection and self.connection.open:
            self.connection.close()
            self.logger.info("数据库连接已关闭")

    def exists(self, title: str, artists: List[str], album: str = "") -> bool:
        """库中存在该歌曲的非 MP3 记录返回 True；不存在/仅有 MP3 返回 False。"""
        if self.connection is None:
            self.logger.error("数据库连接未初始化")
            raise ConnectionError("数据库连接未初始化")
        # 长任务（30 首 + 逐首节流）可能触发 MySQL wait_timeout 把连接断开；
        # ping(reconnect=True) 在断开时自动重连，避免一次断连后剩余歌曲全部跳过库检查。
        # 实在连不上则本次降级为"不在库中"（与下方查询失败返回 False 的策略一致），
        # 只会导致该歌被重下，不至于中断整轮同步。
        try:
            self.connection.ping(reconnect=True)
        except pymysql.MySQLError as e:
            self.logger.error(f"MySQL 连接不可用，跳过本次库检查: {e}")
            return False
        if not title or not artists:
            self.logger.warning("歌曲名或艺术家列表为空，无法检查")
            return False

        cleaned_artists = [a.strip() for a in artists if a.strip()]
        if not cleaned_artists:
            self.logger.warning("清洗后无有效艺术家，无法检查")
            return False

        try:
            with self.connection.cursor() as cursor:
                placeholders = ", ".join(["%s"] * len(cleaned_artists))
                # 直接在 SQL 中排除 MP3：避免存在多格式时 LIMIT 1 命中 MP3 行而漏判无损文件
                sql = f"""
                    SELECT 1
                    FROM music_track t
                    INNER JOIN music_artist a ON t.artist_id = a.id
                    WHERE t.name = %s
                    AND a.name IN ({placeholders})
                    AND LOWER(t.suffix) <> 'mp3'
                    LIMIT 1
                """
                artists_str = " & ".join(cleaned_artists)
                self.logger.debug(f"执行SQL，参数: {[title] + cleaned_artists}")
                cursor.execute(sql, [title] + cleaned_artists)
                found = cursor.fetchone() is not None
                self.logger.debug(f"歌曲检查结果: {title} - {artists_str}，存在非MP3: {found}")
                return found
        except pymysql.MySQLError as e:
            self.logger.error(f"MySQL查询失败: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"歌曲检查过程出错: {str(e)}")
            return False


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
