from datetime import datetime
import logging
import os
from typing import Dict, List, Any, Optional, Tuple

from config import Config
from netease import NeteaseMusic
from netease import (
        NeteaseMusic
    )
from navidrome import NavidromeClient
from downloader import SongDownloader
from bark import BarkNotifier
from logger import setup_logger
# 导入Cookie管理器
from cookie_manager import CookieManager
from mysql_check import MySQLChecker


class APIResponse:
    """API响应工具类"""
    
    @staticmethod
    def success(data: Any = None, message: str = 'success', status_code: int = 200) -> Tuple[Dict[str, Any], int]:
        """成功响应"""
        response = {
            'status': status_code,
            'success': True,
            'message': message
        }
        if data is not None:
            response['data'] = data
        return response, status_code
    
    @staticmethod
    def error(message: str, status_code: int = 400, error_code: str = None) -> Tuple[Dict[str, Any], int]:
        """错误响应"""
        response = {
            'status': status_code,
            'success': False,
            'message': message
        }
        if error_code:
            response['error_code'] = error_code
        return response, status_code




class MusicSyncApp:
    def __init__(self, config: Config):
        self.config = config
        # 初始化Cookie管理器
        self.cookie_manager = CookieManager(config)
        # 初始化组件

        self.NeteaseApi = NeteaseMusic(self.cookie_manager.parsed_cookies)
        # 从配置获取下载目录并初始化下载器
        self.downloader = SongDownloader(self.cookie_manager.parsed_cookies)  # 传入下载目录
        self.bark = BarkNotifier(config.get("BARK_API", ""))
        
        self.quality_level = config.get("QUALITY_LEVEL", "lossless")


        # 初始化Navidrome客户端（如果启用）
        self.use_navidrome = config.is_enabled("NAVIDROME")
        self.use_mysql = config.is_enabled("MYSQL")
        
         # 设置日志
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"下载目录已设置为: /app/downloads")
        self.logger.info(f"下载音乐品质已设置为: { {"standard": "标准", "exhigh": "极高", "lossless": "无损", "hires": "Hi-Res", "sky": "沉浸环绕声", "jyeffect": "高清环绕声", "jymaster": "超清母带"}.get (self.quality_level, "未知品质")}")
    
    def run_task(self) -> None:
        """执行同步任务"""
        self.logger.info("开始执行音乐同步任务")
        
        try:
            # 任务执行前再次检查Cookie有效性
            # if not self.cookie_manager.is_cookie_valid():
            #     self.logger.error("Cookie无效，无法执行任务")
            #     self.bark.send_notification("音乐同步失败", "Cookie无效，请检查配置")
            #     return
            
            # 1. 查找今日播放列表
            uid = self.config.get("uid")
            # 检测是否为调试模式（根据launch.json中的环境变量）
            is_debug = os.environ.get("DEBUG_MODE") == "True"


            if is_debug:
                # 调试时使用固定日期
                today = '20251024'
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
            
            if not songs:
                self.logger.info("播放列表中没有歌曲，任务结束")
                return
            
            self.logger.info(f"找到 {len(songs)} 首歌曲需要处理")
            
            # 3. 筛选需要下载的歌曲
            songs_to_download = []
            
            if self.use_navidrome:
                self.logger.info("启用Navidrome检查，筛选不在库中的歌曲")
                self.navidrome=NavidromeClient(self.config.get_nested("NAVIDROME.NAVIDROME_HOST"),self.config.get_nested("NAVIDROME.NAVIDROME_USER"),self.config.get_nested("NAVIDROME.NAVIDROME_PASS"))
                for song in songs:
                    title = song.get("name")
                    artists = song.get("artists", "")
                    album = song.get("album", "")
                    
                    exists = self.navidrome.navidrome_song_exists(title, artists, album)
                    if not exists.get("exists", False):
                        # 检查本地是否已下载
                        if not self.downloader.is_song_already_downloaded(song, self.quality_level):
                            songs_to_download.append(song)
            elif self.use_mysql:
                self.logger.info("启用MySQLe检查，筛选不在库中的歌曲")
                self.mysql_checker=MySQLChecker(self.config)
                self.mysql_checker.open_connection()
                for song in songs:
                    title = song.get("name")
                    artists = song.get("artists", "")
                    album = song.get("album", "")
                    
                    exists = self.mysql_checker.check_song(title, artists)
                    if not exists:
                        # 检查本地是否已下载
                        if not self.downloader.is_song_already_downloaded(song, self.quality_level):
                            songs_to_download.append(song)
                self.mysql_checker.close_connection()
            else:
                self.logger.info("未启用任何检查，仅检查本地是否已下载")
                for song in songs:
                    if not self.downloader.is_song_already_downloaded(song, self.quality_level):
                        songs_to_download.append(song)
            
            if not songs_to_download:
                self.logger.info("没有需要下载的歌曲，任务结束")
                self.bark.send_notification("云音乐下载", "没有需要下载的歌曲")
                return
            
            # 4. 下载歌曲
            success_songs = self.downloader.download_songs(songs_to_download,self.quality_level)
            failed_songs = [s for s in songs_to_download if s not in success_songs]
            
            # 5. 发送报告
            self.bark.send_download_report(success_songs, failed_songs)
            
            self.logger.info("音乐下载任务执行完成")
            
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