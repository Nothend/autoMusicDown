import logging
import os
from pathlib import Path
import re
from typing import Dict, List

import requests

from netease import NeteaseMusic, APIException
from utils import timestamp_to_date
from models import AudioFormat, MusicInfo, DownloadResult
from tagger import write_tags


class DownloadException(Exception):
    """下载异常类"""
    pass

class SongDownloader:
    def __init__(self, cookies: Dict[str, str], netease_api: "NeteaseMusic" = None):
        self.logger = logging.getLogger(__name__)
        self.download_dir = self._get_download_dir()
        self._init_download_dir()
        self.parsedCookies=cookies
        # 复用外部传入的 NeteaseMusic 实例；未传入时再自行创建
        self.NeteaseApi = netease_api or NeteaseMusic(self.parsedCookies)
        
        # 支持的文件格式
        self.supported_formats = {
            'mp3': AudioFormat.MP3,
            'flac': AudioFormat.FLAC,
            'm4a': AudioFormat.M4A
        }

    def _get_download_dir(self) -> Path:
        # 检查是否为Docker环境（通过/.dockerenv文件判断）
        if os.path.exists("/.dockerenv"):
            return Path("/app/downloads")
        else:
            # 本地环境使用项目目录下的downloads文件夹
            return Path(__file__).parent.parent / "downloads"  # 相对路径
        
    def _init_download_dir(self) -> None:
        """初始化下载目录，确保存在（兼容本地和Docker环境）"""
        try:
            # 递归创建目录（父目录不存在也会创建），已存在则不报错
            self.download_dir.mkdir(exist_ok=True, parents=True)
            
            # 获取绝对路径，便于调试确认
            abs_path = self.download_dir.resolve()
            self.logger.info(f"下载目录初始化成功，绝对路径：{abs_path}")

            # 环境识别（本地/ Docker）
            if os.path.exists("/.dockerenv"):
                # Docker环境：提示主机映射关系
                self.logger.info(f"当前为Docker环境，主机映射路径：./downloads → 容器内路径：{abs_path}")
            else:
                # 本地环境：直接提示路径
                self.logger.info(f"当前为本地环境，下载目录路径：{abs_path}")

        except PermissionError:
            self.logger.error(
                f"无权限创建下载目录 {self.download_dir}！"
                f"请检查项目根目录（{self.download_dir.parent}）的写入权限"
            )
            raise
        except Exception as e:
            self.logger.error(f"初始化下载目录失败：{str(e)}")
            raise

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的安全文件名
        """
        # 移除或替换非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        filename = re.sub(illegal_chars, ' & ', filename)
        
        # 移除前后空格和点
        filename = filename.strip(' .')
        
        # 限制长度
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename or "unknown"

    def _determine_file_extension(self, url: str, content_type: str = "") -> str:
        """根据URL和Content-Type确定文件扩展名
        
        Args:
            url: 下载URL
            content_type: HTTP Content-Type头
            
        Returns:
            文件扩展名
        """
        # 首先尝试从URL获取
        if '.flac' in url.lower():
            return '.flac'
        elif '.mp3' in url.lower():
            return '.mp3'
        elif '.m4a' in url.lower():
            return '.m4a'
        
        # 从Content-Type获取
        content_type = content_type.lower()
        if 'flac' in content_type:
            return '.flac'
        elif 'mpeg' in content_type or 'mp3' in content_type:
            return '.mp3'
        elif 'mp4' in content_type or 'm4a' in content_type:
            return '.m4a'
        
        return '.mp3'  # 默认
    
    def get_music_info(self, music_id: int, quality: str = "standard") -> MusicInfo:
        """获取音乐详细信息
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            音乐信息对象
            
        Raises:
            DownloadException: 获取信息失败时抛出
        """
        try:
            
            # 获取音乐URL信息
            url_result = self.NeteaseApi.get_song_url(music_id, quality, self.parsedCookies)
            if not url_result.get('data') or not url_result['data']:
                raise DownloadException(f"无法获取音乐ID {music_id} 的播放链接")
            
            song_data = url_result['data'][0]
            download_url = song_data.get('url', '')
            if not download_url:
                raise DownloadException(f"音乐ID {music_id} 无可用的下载链接")
            
            # 获取音乐详情
            detail_result = self.NeteaseApi.get_song_detail(music_id)
            if not detail_result.get('songs') or not detail_result['songs']:
                raise DownloadException(f"无法获取音乐ID {music_id} 的详细信息")
            
            song_detail = detail_result['songs'][0]

            # 获取专辑详情以提取更准确的发行时间
            alum_id=song_detail['al']['id'] if song_detail and 'al' in song_detail and song_detail['al'] else None
            alum_info = self.NeteaseApi.get_album_detail(alum_id,self.parsedCookies) if alum_id else None
            alum_publisTime=''
            if alum_info and 'publishTime' in alum_info:
                alum_publisTime = alum_info.get('publishTime', song_detail['al'].get('publishTime',0))
            
            
            # 获取歌词
            lyric_result = self.NeteaseApi.get_lyric(music_id, self.parsedCookies)
            lyric = lyric_result.get('lrc', {}).get('lyric', '') if lyric_result else ''
            tlyric = lyric_result.get('tlyric', {}).get('lyric', '') if lyric_result else ''
            
            # 构建艺术家字符串
            artists = [artist['name'] for artist in song_detail.get('ar', [])]  # 生成列表
            # 提取发行时间（处理13位/11位时间戳）
            # 网易云API的album.publishTime为13位毫秒级时间戳
            publish_timestamp = alum_publisTime
            # 转换为年月日格式（调用工具函数）
            publish_time = timestamp_to_date(publish_timestamp)
            # 创建MusicInfo对象
            music_info = MusicInfo(
                id=music_id,
                name=song_detail.get('name', '未知歌曲'),
                publishTime=publish_time,
                artists=artists if artists else ['未知艺术家'],  # 列表默认值
                album=song_detail.get('al', {}).get('name', '未知专辑'),
                pic_url=song_detail.get('al', {}).get('picUrl', ''),
                duration=song_detail.get('dt', 0) // 1000,  # 转换为秒
                track_number=song_detail.get('no', 0),
                download_url=download_url,
                file_type=song_data.get('type', 'mp3').lower(),
                file_size=song_data.get('size', 0),
                quality=quality,
                lyric=lyric,
                tlyric=tlyric
            )
            
            return music_info
            
        except APIException as e:
            raise DownloadException(f"API调用失败: {e}")
        except Exception as e:
            raise DownloadException(f"获取音乐信息时发生错误: {e}")
  
    
    def download_song(self, music_info: MusicInfo, quality: str = "standard") -> DownloadResult:
        """下载单首歌曲，返回 DownloadResult"""
        try:
            # 验证音质参数
            valid_qualities = ['standard', 'exhigh', 'lossless', 'hires', 'sky', 'jyeffect', 'jymaster']
            if quality not in valid_qualities:
                return DownloadResult(
                    success=False,
                    error_message=f"无效的音质参数，支持: {', '.join(valid_qualities)}"
                )

            # 生成目标文件名（艺术家用 & 拼接）
            artists_joined = '&'.join(music_info.artists)
            base_filename = f"{artists_joined} - {music_info.name}"
            safe_filename = self._sanitize_filename(base_filename)
            file_ext = self._determine_file_extension(music_info.download_url)
            file_path = self.download_dir / f"{safe_filename}{file_ext}"

            # 已存在则跳过下载，否则执行核心下载逻辑
            if file_path.exists():
                self.logger.info(f"文件已存在: {safe_filename}{file_ext}")
            else:
                download_result = self.download_music_file(music_info, quality)
                if not download_result.success:
                    return DownloadResult(
                        success=False,
                        error_message=f"下载失败: {download_result.error_message}",
                        music_info=music_info
                    )
                file_path = Path(download_result.file_path)
                self.logger.info(f"下载完成: {safe_filename}{file_ext}")

            if not file_path.exists():
                return DownloadResult(
                    success=False,
                    error_message="文件不存在",
                    music_info=music_info
                )
            return DownloadResult(
                success=True,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                music_info=music_info
            )

        except Exception as e:
            self.logger.error(f"下载音乐异常: {str(e)}")
            return DownloadResult(
                success=False,
                error_message=f"下载异常: {str(e)}"
            )

    
    def download_songs(self, songs: List[MusicInfo], quality: str) -> List[MusicInfo]:
        """
        下载多首歌曲（顺序下载）
        
        Args:
            songs: 歌曲列表
            
        Returns:
            下载成功的歌曲列表
        """
        self.logger.info(f"开始下载 {len(songs)} 首歌曲，下载目录: {self.download_dir}")
        success_songs = []
        
        for song_info in songs:
            if song_info:
                result = self.download_song(song_info, quality)
                if result.success:
                    success_songs.append(song_info)
                else:
                    self.logger.warning(f"下载歌曲失败: {song_info.name} - {result.error_message}")
        
        self.logger.info(f"下载完成，成功 {len(success_songs)}/{len(songs)} 首")
        return success_songs
    
    
    def is_song_already_downloaded(self, music_info:MusicInfo) -> bool:
        """
        通过歌曲ID判断是否已下载
        
        Args:
            song_id: 歌曲ID
            quality: 音质等级
            
        Returns:
            是否已下载
        """
        try:
            # 生成可能的文件名
            artists_joined = '&'.join(music_info.artists)  # 列表元素用 & 拼接为字符串
            base_filename = f"{artists_joined} - {music_info.name}"
            safe_filename = self._sanitize_filename(base_filename)

            file_ext = self._determine_file_extension(music_info.download_url)
            # 检查所有可能的文件
            
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            # 目前哈希值判断有点问题，仅用文件名判断
            if file_path.exists():
                # 文件名匹配，进一步检查文件大小或哈希
                #if self._verify_file_integrity(file_path, music_info):
                #    self.logger.info(f"已找到匹配的歌曲文件: {file_path.name}")
                #    return True
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"通过ID检查歌曲是否已下载时出错: {str(e)}")
            return False
    
    
    
    def download_music_file(self, music_info: MusicInfo, quality: str = "standard") -> DownloadResult:
        """下载音乐文件到本地
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            下载结果对象
        """
        try:
            # 生成可能的文件名
            artists_joined = '&'.join(music_info.artists)  # 列表元素用 & 拼接为字符串
            base_filename = f"{artists_joined} - {music_info.name}"
            safe_filename = self._sanitize_filename(base_filename)
            
            # 确定文件扩展名
            file_ext = self._determine_file_extension(music_info.download_url)
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            
            # 检查文件是否已存在
            if file_path.exists():
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info
                )
            
            # 下载文件
            response = requests.get(music_info.download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            # 写入文件
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # 写入音乐标签
            write_tags(file_path, music_info)
            
            return DownloadResult(
                success=True,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                music_info=music_info
            )
            
        except DownloadException:
            raise
        except requests.RequestException as e:
            return DownloadResult(
                success=False,
                error_message=f"下载请求失败: {e}"
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                error_message=f"下载过程中发生错误: {e}"
            )
