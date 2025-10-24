from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging
import os
from pathlib import Path
import re
import hashlib
from typing import Dict, List, Any, Optional, Tuple
import asyncio
import aiohttp
import aiofiles
from io import BytesIO
import requests
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, APIC
from mutagen.mp4 import MP4

from netease import NeteaseMusic, APIException

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
    artists: str
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
    data: Optional[Dict] = None  # 新增：用于存储JSON格式响应数据


class DownloadException(Exception):
    """下载异常类"""
    pass

class SongDownloader:
    def __init__(self, cookies: Dict[str, str]):
        self.logger = logging.getLogger(__name__)
        self.download_dir = self._get_download_dir()
        self._init_download_dir()
        self.parsedCookies=cookies
        # 初始化组件
        self.NeteaseApi = NeteaseMusic(self.parsedCookies)
        
        # 支持的文件格式
        self.supported_formats = {
            'mp3': AudioFormat.MP3,
            'flac': AudioFormat.FLAC,
            'm4a': AudioFormat.M4A
        }
        
        # 缓存已计算的文件哈希，提高效率
        self.file_hash_cache = {}

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

    def get_download_path(self, filename: str) -> Path:
        """获取文件的完整下载路径"""
        return self.download_dir / filename
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的安全文件名
        """
        # 移除或替换非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        filename = re.sub(illegal_chars, '_', filename)
        
        # 移除前后空格和点
        filename = filename.strip(' .')
        
        # 限制长度
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename or "unknown"
    
    def _timestamp_str_to_date(self, timestamp_int: int) -> str:
        """
        将整数时间戳（13位或11位）转换为YYYY-MM-DD格式
        
        Args:
            timestamp: 整数时间戳（如1305388800000或13053888000）
            
        Returns:
            格式化后的日期字符串，转换失败返回空字符串
        """
        try:
            # 1. 处理11位时间戳（补全为13位毫秒级）
            if 10**10 <= timestamp_int < 10**11:  # 11位数字范围（10000000000 ~ 99999999999）
                timestamp_int *= 100  # 转换为13位（如13053888000 → 1305388800000）
            
            # 2. 验证13位时间戳（毫秒级）
            if not (10**12 <= timestamp_int < 10**13):  # 13位数字范围（1000000000000 ~ 9999999999999）
                return ""
            
            # 3. 转换为年月日（毫秒级时间戳需÷1000）
            return datetime.fromtimestamp(timestamp_int / 1000).strftime("%Y-%m-%d")
        
        except (ValueError, TypeError, OSError):
            # 处理异常情况（如数值溢出、非整数类型等）
            return ""

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
            
            # 获取歌词
            lyric_result = self.NeteaseApi.get_lyric(music_id, self.parsedCookies)
            lyric = lyric_result.get('lrc', {}).get('lyric', '') if lyric_result else ''
            tlyric = lyric_result.get('tlyric', {}).get('lyric', '') if lyric_result else ''
            
            # 构建艺术家字符串
            artists = '/'.join(artist['name'] for artist in song_detail.get('ar', []))
            # 提取发行时间（处理13位/11位时间戳）
            # 网易云API的album.publishTime为13位毫秒级时间戳
            publish_timestamp = song_detail.get('publishTime', '2025')
            # 转换为年月日格式（调用工具函数）
            publish_time = self._timestamp_str_to_date(publish_timestamp)
            # 创建MusicInfo对象
            music_info = MusicInfo(
                id=music_id,
                name=song_detail.get('name', '未知歌曲'),
                publishTime=publish_time,
                artists=artists or '未知艺术家',
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
  
    
    def download_song(self, music_id: int, quality: str = "standard", re_format: str = "file") -> DownloadResult:
        """下载音乐API（保留返回格式逻辑，使用DownloadResult）"""
        try:
            # 参数验证（音乐ID）
            if not isinstance(music_id, int) or music_id <= 0:
                return DownloadResult(
                    success=False,
                    error_message="无效的音乐ID，必须是正整数"
                )
            
            # 验证音质参数
            valid_qualities = ['standard', 'exhigh', 'lossless', 'hires', 'sky', 'jyeffect', 'jymaster']
            if quality not in valid_qualities:
                return DownloadResult(
                    success=False,
                    error_message=f"无效的音质参数，支持: {', '.join(valid_qualities)}"
                )
            
            # 验证返回格式
            if re_format not in ['file', 'json']:
                return DownloadResult(
                    success=False,
                    error_message="返回格式只支持 'file' 或 'json'"
                )
            
            # 检查是否已下载
            if self.is_song_already_downloaded_by_id(music_id, quality):
                self.logger.info(f"音乐ID {music_id} 已下载，跳过下载")
                # 获取已下载文件信息并返回
                music_info = self.get_music_info(music_id, quality)
                filename = f"{music_info.artists} - {music_info.name}"
                safe_filename = self._sanitize_filename(filename)
                file_ext = self._determine_file_extension(music_info.download_url)
                file_path = self.download_dir / f"{safe_filename}{file_ext}"
                
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size if file_path.exists() else 0,
                    music_info=music_info
                )
            
            # 获取音乐基本信息
            song_info = self.NeteaseApi.get_song_detail(music_id)
            if not song_info or 'songs' not in song_info or not song_info['songs']:
                return DownloadResult(
                    success=False,
                    error_message="未找到音乐信息"
                )
            
            # 获取音乐下载链接
            url_info = self.NeteaseApi.get_song_url(music_id, quality, self.parsedCookies)
            if not url_info or 'data' not in url_info or not url_info['data'] or not url_info['data'][0].get('url'):
                return DownloadResult(
                    success=False,
                    error_message="无法获取音乐下载链接，可能是版权限制或音质不支持"
                )
            
            # 构建音乐信息
            song_data = song_info['songs'][0]
            url_data = url_info['data'][0]
            
            music_info = {
                'id': music_id,
                'name': song_data['name'],
                'artist_string': '/'.join(artist['name'] for artist in song_data['ar']),
                'album': song_data['al']['name'],
                'pic_url': song_data['al']['picUrl'],
                'file_type': url_data['type'],
                'file_size': url_data['size'],
                'duration': song_data.get('dt', 0),
                'download_url': url_data['url'],
                'publishTime': song_data.get('publishTime', 0)
            }
            
            # 生成安全文件名
            safe_name = f"{music_info['artist_string']} - {music_info['name']}"
            safe_name = ''.join(c for c in safe_name if c not in r'<>:"/\|?*')
            filename = f"{safe_name}.{music_info['file_type']}"
            file_path = self.download_dir / filename
            
            # 检查文件是否已存在
            if file_path.exists():
                self.logger.info(f"文件已存在: {filename}")
            else:
                # 调用下载文件方法（核心下载逻辑）
                download_result = self.download_music_file(music_id, quality)
                if not download_result.success:
                    return DownloadResult(
                        success=False,
                        error_message=f"下载失败: {download_result.error_message}",
                        music_info=music_info
                    )
                file_path = Path(download_result.file_path)
                self.logger.info(f"下载完成: {filename}")
            
            # 根据返回格式返回结果（保留核心逻辑）
            if re_format == 'json':
                # 构建JSON响应数据
                response_data = {
                    'music_id': music_id,
                    'name': music_info['name'],
                    'artist': music_info['artist_string'],
                    'album': music_info['album'],
                    'quality': quality,
                    'quality_name': self.NeteaseApi._get_quality_display_name(quality),
                    'file_type': music_info['file_type'],
                    'file_size': music_info['file_size'],
                    'file_size_formatted': self.NeteaseApi._format_file_size(music_info['file_size']),
                    'file_path': str(file_path.absolute()),
                    'filename': filename,
                    'duration': music_info['duration'],
                    'publishTime': music_info['publishTime']
                }
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info,
                    data=response_data  # 将JSON数据存入data字段
                )
            else:  # re_format == 'file'
                if not file_path.exists():
                    return DownloadResult(
                        success=False,
                        error_message="文件不存在"
                    )
                # 返回文件相关信息（实际文件发送由调用方处理）
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info
                )
            
        except Exception as e:
            # 简化异常日志，去掉traceback（如果不需要详细堆栈）
            self.logger.error(f"下载音乐异常: {str(e)}")
            return DownloadResult(
                success=False,
                error_message=f"下载异常: {str(e)}"
            )

    
    def download_songs(self, songs: List[Dict[str, Any]], quality: str) -> List[Dict[str, Any]]:
        """
        下载多首歌曲（顺序下载）
        
        Args:
            songs: 歌曲列表
            
        Returns:
            下载成功的歌曲列表
        """
        self.logger.info(f"开始下载 {len(songs)} 首歌曲，下载目录: {self.download_dir}")
        success_songs = []
        
        for song in songs:
            sid = song.get("id")
            if sid:
                result = self.download_song(sid, quality)
                if result.success:
                    success_songs.append(song)
        
        self.logger.info(f"下载完成，成功 {len(success_songs)}/{len(songs)} 首")
        return success_songs
    
    def is_song_already_downloaded(self, song: Dict[str, Any], quality: str) -> bool:
        """
        判断歌曲是否已下载
        
        Args:
            song: 歌曲信息字典
            quality: 音质等级
            
        Returns:
            是否已下载
        """
        try:
            # 提取歌曲基本信息
            song_id = song.get("id")
            if not song_id:
                return False
                
            # 通过ID检查
            return self.is_song_already_downloaded_by_id(song_id, quality)
            
        except Exception as e:
            self.logger.error(f"检查歌曲是否已下载时出错: {str(e)}")
            return False
    
    def is_song_already_downloaded_by_id(self, song_id: int, quality: str) -> bool:
        """
        通过歌曲ID判断是否已下载
        
        Args:
            song_id: 歌曲ID
            quality: 音质等级
            
        Returns:
            是否已下载
        """
        try:
            # 获取音乐信息
            music_info = self.get_music_info(song_id, quality)
            
            # 生成可能的文件名
            base_filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(base_filename)
            
            # 可能的文件扩展名
            possible_extensions = ['.mp3', '.flac', '.m4a']
            
            # 检查所有可能的文件
            for ext in possible_extensions:
                file_path = self.download_dir / f"{safe_filename}{ext}"
                if file_path.exists():
                    # 文件名匹配，进一步检查文件大小或哈希
                    if self._verify_file_integrity(file_path, music_info):
                        self.logger.info(f"已找到匹配的歌曲文件: {file_path.name}")
                        return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"通过ID检查歌曲是否已下载时出错: {str(e)}")
            return False
    
    def _verify_file_integrity(self, file_path: Path, music_info: MusicInfo) -> bool:
        """
        验证文件完整性，先检查文件大小，差异较小时再检查哈希
        
        Args:
            file_path: 文件路径
            music_info: 音乐信息
            
        Returns:
            文件是否匹配
        """
        try:
            # 检查文件大小（允许1%的误差）
            file_size = file_path.stat().st_size
            expected_size = music_info.file_size
            
            if expected_size > 0:
                size_diff_ratio = abs(file_size - expected_size) / expected_size
                if size_diff_ratio < 0.01:  # 大小差异小于1%
                    return True
                # 如果大小差异较大，尝试哈希验证（针对可能的不同音质版本）
                return self._compare_file_hash(file_path, music_info)
            
            # 如果没有预期大小，直接使用哈希验证
            return self._compare_file_hash(file_path, music_info)
            
        except Exception as e:
            self.logger.warning(f"验证文件完整性时出错: {str(e)}")
            return False
    
    def _compare_file_hash(self, file_path: Path, music_info: MusicInfo) -> bool:
        """
        比较文件哈希值，使用缓存提高效率
        
        Args:
            file_path: 文件路径
            music_info: 音乐信息
            
        Returns:
            哈希是否匹配
        """
        try:
            # 检查缓存
            if file_path in self.file_hash_cache:
                file_hash = self.file_hash_cache[file_path]
            else:
                # 计算文件哈希（只计算前1MB和后1MB，提高效率）
                file_hash = self._calculate_file_hash(file_path)
                self.file_hash_cache[file_path] = file_hash
            
            # 计算期望哈希（基于音乐信息）
            expected_hash = self._calculate_expected_hash(music_info)
            
            return file_hash == expected_hash
            
        except Exception as e:
            self.logger.warning(f"比较文件哈希时出错: {str(e)}")
            return False
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """
        计算文件哈希，只读取部分内容以提高效率
        
        Args:
            file_path: 文件路径
            
        Returns:
            哈希值字符串
        """
        hash_obj = hashlib.md5()
        file_size = file_path.stat().st_size
        
        with open(file_path, 'rb') as f:
            # 读取前1MB
            hash_obj.update(f.read(1024 * 1024))
            
            # 如果文件大于2MB，再读取最后1MB
            if file_size > 2 * 1024 * 1024:
                f.seek(-1024 * 1024, os.SEEK_END)
                hash_obj.update(f.read(1024 * 1024))
        
        return hash_obj.hexdigest()
    
    def _calculate_expected_hash(self, music_info: MusicInfo) -> str:
        """
        基于音乐信息计算期望的哈希值
        
        Args:
            music_info: 音乐信息
            
        Returns:
            期望的哈希值字符串
        """
        hash_obj = hashlib.md5()
        # 使用关键信息计算哈希
        hash_str = f"{music_info.id}_{music_info.name}_{music_info.artists}_{music_info.album}_{music_info.duration}"
        hash_obj.update(hash_str.encode('utf-8'))
        return hash_obj.hexdigest()
    
    def download_music_file(self, music_id: int, quality: str = "standard") -> DownloadResult:
        """下载音乐文件到本地
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            下载结果对象
        """
        try:
            # 获取音乐信息
            music_info = self.get_music_info(music_id, quality)
            
            # 生成文件名
            filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(filename)
            
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
            self._write_music_tags(file_path, music_info)
            
            # 添加到哈希缓存
            self.file_hash_cache[file_path] = self._calculate_file_hash(file_path)
            
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
    
    async def download_music_file_async(self, music_id: int, quality: str = "standard") -> DownloadResult:
        """异步下载音乐文件到本地
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            下载结果对象
        """
        try:
            # 获取音乐信息（同步操作）
            music_info = self.get_music_info(music_id, quality)
            
            # 生成文件名
            filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(filename)
            
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
            
            # 异步下载文件
            async with aiohttp.ClientSession() as session:
                async with session.get(music_info.download_url) as response:
                    response.raise_for_status()
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
            
            # 写入音乐标签
            self._write_music_tags(file_path, music_info)
            
            # 添加到哈希缓存
            self.file_hash_cache[file_path] = self._calculate_file_hash(file_path)
            
            return DownloadResult(
                success=True,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                music_info=music_info
            )
            
        except DownloadException:
            raise
        except aiohttp.ClientError as e:
            return DownloadResult(
                success=False,
                error_message=f"异步下载请求失败: {e}"
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                error_message=f"异步下载过程中发生错误: {e}"
            )
    
    def download_music_to_memory(self, music_id: int, quality: str = "standard") -> Tuple[bool, BytesIO, MusicInfo]:
        """下载音乐到内存
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            (是否成功, 音乐数据流, 音乐信息)
            
        Raises:
            DownloadException: 下载失败时抛出
        """
        try:
            # 获取音乐信息
            music_info = self.get_music_info(music_id, quality)
            
            # 下载到内存
            response = requests.get(music_info.download_url, timeout=30)
            response.raise_for_status()
            
            # 创建BytesIO对象
            audio_data = BytesIO(response.content)
            
            return True, audio_data, music_info
            
        except DownloadException:
            raise
        except requests.RequestException as e:
            raise DownloadException(f"下载到内存失败: {e}")
        except Exception as e:
            raise DownloadException(f"内存下载过程中发生错误: {e}")
    
    async def download_batch_async(self, music_ids: List[int], quality: str = "standard") -> List[DownloadResult]:
        """批量异步下载音乐
        
        Args:
            music_ids: 音乐ID列表
            quality: 音质等级
            
        Returns:
            下载结果列表
        """
        max_concurrent = 5  # 设置最大并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def download_with_semaphore(music_id: int) -> DownloadResult:
            async with semaphore:
                return await self.download_music_file_async(music_id, quality)
        
        tasks = [download_with_semaphore(music_id) for music_id in music_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(DownloadResult(
                    success=False,
                    error_message=f"下载音乐ID {music_ids[i]} 时发生异常: {result}"
                ))
            else:
                processed_results.append(result)
        
        return processed_results
    
    def _write_music_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入音乐标签信息
        
        Args:
            file_path: 音乐文件路径
            music_info: 音乐信息
        """
        try:
            file_ext = file_path.suffix.lower()
            
            if file_ext == '.mp3':
                self._write_mp3_tags(file_path, music_info)
            elif file_ext == '.flac':
                self._write_flac_tags(file_path, music_info)
            elif file_ext == '.m4a':
                self._write_m4a_tags(file_path, music_info)
                
        except Exception as e:
            print(f"写入音乐标签失败: {e}")
    
    def _write_mp3_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入MP3标签"""
        try:
            audio = MP3(str(file_path), ID3=ID3)
            
            # 添加ID3标签
            audio.tags.add(TIT2(encoding=3, text=music_info.name))
            audio.tags.add(TPE1(encoding=3, text=music_info.artists))
            audio.tags.add(TALB(encoding=3, text=music_info.album))
            
            if music_info.track_number > 0:
                audio.tags.add(TRCK(encoding=3, text=str(music_info.track_number)))
            
            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=pic_response.content
                    ))
                except:
                    pass  # 封面下载失败不影响主流程
            
            audio.save()
        except Exception as e:
            print(f"写入MP3标签失败: {e}")
    
    def _write_flac_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入FLAC标签"""
        try:
            audio = FLAC(str(file_path))
            
            audio['TITLE'] = music_info.name
            audio['ARTIST'] = music_info.artists
            audio['ALBUM'] = music_info.album

            if music_info.track_number > 0:
                audio['TRACKNUMBER'] = str(music_info.track_number)
            
            # 新增：发行时间（需要从音乐信息中获取publishTime）
            if hasattr(music_info, 'publishTime') and music_info.publishTime:
                full_date = music_info.publishTime
                
                # 单独写入年份（提高兼容性）
                if '-' in full_date:
                    audio['YEAR'] = full_date.split('-')[0]  # 提取YYYY部分
                else:
                    audio['YEAR'] = full_date  # 若本身就是年份格式
                # 写入完整日期（标准DATE字段）
                audio['DATE'] = full_date.split('-')[0]  # 提取YYYY部分
            # 新增：歌词标签（使用自定义字段存储歌词和翻译歌词）
            if music_info.lyric:
                audio['LYRICS'] = music_info.lyric.strip()  # 原歌词
            if music_info.tlyric:
                audio['TRANSLATEDLYRICS'] = music_info.tlyric.strip()  # 翻译歌词

            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    
                    from mutagen.flac import Picture
                    picture = Picture()
                    picture.type = 3  # Cover (front)
                    picture.mime = 'image/jpeg'
                    picture.desc = 'Cover'
                    picture.data = pic_response.content
                    audio.add_picture(picture)
                except:
                    pass  # 封面下载失败不影响主流程
            
            audio.save()
        except Exception as e:
            print(f"写入FLAC标签失败: {e}")
    
    def _write_m4a_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入M4A标签"""
        try:
            audio = MP4(str(file_path))
            
            audio['\xa9nam'] = music_info.name
            audio['\xa9ART'] = music_info.artists
            audio['\xa9alb'] = music_info.album
            
            if music_info.track_number > 0:
                audio['trkn'] = [(music_info.track_number, 0)]
            
            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    audio['covr'] = [pic_response.content]
                except:
                    pass  # 封面下载失败不影响主流程
            
            audio.save()
        except Exception as e:
            print(f"写入M4A标签失败: {e}")

    def get_download_progress(self, music_id: int, quality: str = "standard") -> Dict[str, Any]:
        """获取下载进度信息
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            包含进度信息的字典
        """
        try:
            music_info = self.get_music_info(music_id, quality)
            
            filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(filename)
            file_ext = self._determine_file_extension(music_info.download_url)
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            
            if file_path.exists():
                current_size = file_path.stat().st_size
                progress = (current_size / music_info.file_size * 100) if music_info.file_size > 0 else 0
                
                return {
                    'music_id': music_id,
                    'filename': safe_filename + file_ext,
                    'total_size': music_info.file_size,
                    'current_size': current_size,
                    'progress': min(progress, 100),
                    'completed': current_size >= music_info.file_size
                }
            else:
                return {
                    'music_id': music_id,
                    'filename': safe_filename + file_ext,
                    'total_size': music_info.file_size,
                    'current_size': 0,
                    'progress': 0,
                    'completed': False
                }
                
        except Exception as e:
            return {
                'music_id': music_id,
                'error': str(e),
                'progress': 0,
                'completed': False
            }