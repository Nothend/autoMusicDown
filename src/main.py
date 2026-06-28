from datetime import datetime
import logging
import os
import time
from typing import List

from config import Config
from netease import NeteaseMusic
from downloader import SongDownloader
from bark import BarkNotifier
from logger import setup_logger
from library import make_library_checker
from utils import parse_cookie, quality_display_name


class MusicSyncApp:
    def __init__(self, config: Config):
        self.config = config
        # 解析配置中的 cookie 字符串为 dict
        self.parsed_cookies = parse_cookie(config.get("cookie"))

        self.NeteaseApi = NeteaseMusic(self.parsed_cookies)
        # 下载器复用同一个 NeteaseMusic 实例，避免重复构造、保持请求来源一致
        self.downloader = SongDownloader(self.parsed_cookies, self.NeteaseApi)
        self.bark = BarkNotifier(config.get("BARK_API", ""))

        self.quality_level = config.get("QUALITY_LEVEL", "lossless")
        # 每首歌处理之间的间隔（秒），默认 0.5s，可在 config.yaml 用 REQUEST_DELAY 调整
        self.request_delay = float(config.get("REQUEST_DELAY", 0.5))
        # 库检查后端在 run_task 里按需创建（避免 cookie 无效时白开数据库连接）
        self.library_checker = None

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"下载目录已设置为: {self.downloader.download_dir}")
        self.logger.info(f"下载音乐品质已设置为: {quality_display_name(self.quality_level)}")

    def _exists_in_library(self, title: str, artists: List[str], album: str) -> bool:
        """歌曲是否已在音乐库中（未启用任何后端则恒为 False）"""
        if self.library_checker is None:
            return False
        return self.library_checker.exists(title, artists, album)

    def _resolve_music_info(self, song_id: int, title: str):
        """获取歌曲下载信息；返回 MusicInfo，或 None 表示跳过。

        get_music_info 内部已处理 MP3 短路（返回 None 并记录原因），这里只需
        额外兜住网络/解析异常。
        """
        try:
            music_info = self.downloader.get_music_info(song_id, self.quality_level)
        except Exception as e:
            self.logger.warning(f"无法获取歌曲《{title}》(ID {song_id}) 的下载信息，跳过：{e}")
            return None
        return music_info

    def run_task(self) -> None:
        """执行同步任务"""
        self.logger.info("开始执行音乐同步任务")
        
        try:
            # 任务执行前再次检查Cookie有效性
            # 现在返回的是包含 'valid' 和 'is_vip' 的字典
            cookie_result = self.NeteaseApi.is_cookie_valid()
            
            # 同时返回有效性和VIP状态
            if not cookie_result['valid']:
                self.logger.error("Cookie无效，任务终止")
                self.bark.send_notification("云音乐同步失败", "Cookie无效，请检查配置")
                return
            if not cookie_result['is_vip']:
                self.logger.warning("非VIP账号，部分高品质音乐可能无法下载")
                self.bark.send_notification("云音乐同步警告", "非VIP账号，取消下载")
                return
            
            # 1. 查找今日播放列表
            uid = self.config.get("uid")
            # 检测是否为调试模式（根据launch.json中的环境变量）
            is_debug = os.environ.get("DEBUG_MODE") == "True"


            if is_debug:
                # 调试时使用固定日期
                today = '20251025'
            else:
                # 运行时使用当前日期
                today = datetime.now().strftime("%Y%m%d")
            
            today_playlist = self.NeteaseApi.find_todays_playlist(uid,today)
            
            if not today_playlist:
                self.logger.info("没有找到今日播放列表，任务结束")
                return
            
            # 2. 获取播放列表详情
            playlist_id = today_playlist.get("id")
            playlist_detail = self.NeteaseApi.get_playlist_detail(playlist_id, self.NeteaseApi.cookies)
            songs = playlist_detail.get("tracks", [])
            total_songs = len(songs)  # 统计1：歌单总歌曲数
            if not songs:
                self.logger.info("播放列表中没有歌曲，任务结束")
                self.bark.send_notification("云音乐同步", "播放列表中没有歌曲")
                return
            
            self.logger.info(f"找到 {len(songs)} 首歌曲需要处理")
            
            # 3. 筛选需要下载的歌曲
            songs_to_download = []
            library_exists_count = 0  # 统计2：库中已存在的歌曲数（Navidrome/MySQL）
            local_exists_count = 0    # 统计3：本地已下载的歌曲数
            
            # 按配置创建库去重后端（Navidrome / music-tag-web / 无）
            self.library_checker = make_library_checker(self.config)

            try:
                for song in songs:
                    title = song.get("name")
                    artists = song.get("artists", [])
                    album = song.get("album", "")
                    song_id = song.get("id")

                    # 1) 先查库（Navidrome / music-tag-web），命中则跳过
                    if self._exists_in_library(title, artists, album):
                        library_exists_count += 1
                        continue

                    # 2) 再查本地是否已下载：仅凭歌名+艺术家，零网络请求，
                    #    放在拉取下载信息之前，避免对已有歌曲白打 url/detail/album/lyric 四个接口
                    if self.downloader.is_song_already_downloaded(title, artists):
                        local_exists_count += 1
                        continue

                    # 3) 获取下载信息（内部已短路 MP3：先取 URL，命中 MP3 直接跳过后续请求）
                    music_info = self._resolve_music_info(song_id, title)
                    if music_info is None:
                        continue

                    songs_to_download.append(music_info)

                    # 轻微节流，避免一轮任务对接口造成突发请求
                    if self.request_delay > 0:
                        time.sleep(self.request_delay)
            finally:
                # 确保后端资源释放（如 MySQL 连接），即便中途异常
                if self.library_checker is not None:
                    self.library_checker.close()

            # 统计4：应下载的歌曲数
            should_download = len(songs_to_download)
            # 发送【筛选阶段】统计通知
            self.bark.send_download_report(
                total_songs=total_songs,
                library_exists=library_exists_count,
                local_exists=local_exists_count,
                should_download=should_download
            )
            # 日志输出筛选统计
            self.logger.info(
                f"筛选完成：\n"
                f"歌单总数：{total_songs}首 | 库中已存在：{library_exists_count}首\n"
                f"本地已存在：{local_exists_count}首 | 应下载：{should_download}首"
            )
            if not songs_to_download:
                self.logger.info("没有需要下载的歌曲，任务结束")
                self.bark.send_notification("云音乐下载", "没有需要下载的歌曲")
                return
            
            # 4. 下载歌曲
            success_songs = self.downloader.download_songs(songs_to_download,self.quality_level)
            success_count = len(success_songs)
            failed_count = should_download - success_count  # 应下载 - 成功 = 失败
            
            # 发送【下载阶段】结果通知
            self.bark.send_download_result(
                success=success_count,
                failed=failed_count,
                total=should_download
            )
            
            # 日志输出下载结果
            self.logger.info(
                f"下载完成：\n"
                f"应下载：{should_download}首 | 成功：{success_count}首 | 失败：{failed_count}首"
            )
            
            self.logger.info("音乐同步任务执行完毕")
            
        except Exception as e:
            self.logger.error(f"任务执行出错: {str(e)}", exc_info=True)
            self.bark.send_notification("云音乐下载失败", f"执行任务时出错: {str(e)}")


def main():
    try:
        config = Config()
        # 初始化日志
        level = config.get("LEVEL", "INFO")
        # 用 getattr 替代 logging.getLevelName，获取日志级别常量
        log_level = getattr(logging, level, logging.INFO)  # 若级别无效，默认使用 INFO
        setup_logger(log_level)
        
        logger = logging.getLogger(__name__)
        logger.info("音乐同步程序启动")
        
        # 创建应用实例并启动
        app = MusicSyncApp(config)
        
        # 立即执行一次任务
        logger.info("执行同步任务")
        app.run_task()

        # 任务执行完成后，添加优雅退出处理
        logger.info("同步任务执行完毕，程序准备退出")
        # 关闭日志系统，确保所有日志都已写入
        logging.shutdown()
        # 显式退出，返回成功状态码
        exit(0)
        
    except Exception as e:
        print(f"程序启动失败: {str(e)}")
        logging.error(f"程序启动失败: {str(e)}", exc_info=True)
        # 异常情况下也确保日志关闭
        logging.shutdown()
        # 返回错误状态码
        exit(1)


if __name__ == "__main__":
    main()