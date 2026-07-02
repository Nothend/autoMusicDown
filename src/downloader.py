import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional

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

    def _target_stem(self, name: str, artists: List[str]) -> str:
        """生成不含扩展名的目标文件名（艺术家用 & 拼接并清理非法字符）。"""
        artists_joined = '&'.join(artists)
        return self._sanitize_filename(f"{artists_joined} - {name}")

    def _target_path(self, music_info: MusicInfo) -> Path:
        """根据音乐信息生成完整目标文件路径（含扩展名）。"""
        stem = self._target_stem(music_info.name, music_info.artists)
        file_ext = self._determine_file_extension(music_info.download_url)
        return self.download_dir / f"{stem}{file_ext}"

    def get_music_info(self, music_id: int, quality: str = "standard") -> Optional[MusicInfo]:
        """获取音乐详细信息

        Args:
            music_id: 音乐ID
            quality: 音质等级

        Returns:
            音乐信息对象；若该歌曲只有 MP3 格式（库标准为无损，主动跳过）则返回 None

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

            # 先判定格式：MP3 直接短路返回，省去后续 detail/album/lyric 三次请求
            file_type = song_data.get('type', 'mp3').lower()
            if file_type == 'mp3':
                self.logger.info(f"音乐ID {music_id} 获取到 MP3 格式，跳过该歌曲（省去后续请求）")
                return None

            # 获取音乐详情
            detail_result = self.NeteaseApi.get_song_detail(music_id, self.parsedCookies)
            if not detail_result.get('songs') or not detail_result['songs']:
                raise DownloadException(f"无法获取音乐ID {music_id} 的详细信息")

            song_detail = detail_result['songs'][0]

            # 发行时间：优先用歌曲详情自带的 publishTime（歌曲级或其 al 专辑级），
            # 仅当两者都缺失时才回退到专辑接口——省去每首歌一次网络请求。
            album = song_detail.get('al') or {}
            publish_ts = song_detail.get('publishTime') or album.get('publishTime') or 0
            if not publish_ts and album.get('id'):
                try:
                    album_info = self.NeteaseApi.get_album_detail(album['id'], self.parsedCookies)
                    publish_ts = album_info.get('publishTime') or 0
                except APIException as e:
                    self.logger.debug(f"专辑详情获取失败，跳过发行时间回退：{e}")

            # 获取歌词
            lyric_result = self.NeteaseApi.get_lyric(music_id, self.parsedCookies)
            lyric = lyric_result.get('lrc', {}).get('lyric', '') if lyric_result else ''
            tlyric = lyric_result.get('tlyric', {}).get('lyric', '') if lyric_result else ''
            
            # 构建艺术家字符串
            artists = [artist['name'] for artist in song_detail.get('ar', [])]  # 生成列表
            # 转换发行时间为 YYYY-MM-DD（工具函数已兼容 10/13 位时间戳与空值）
            publish_time = timestamp_to_date(publish_ts)
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
                file_type=file_type,
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
        """下载单首歌曲，返回 DownloadResult（音质合法性已在应用启动时统一校验）"""
        try:
            # 生成目标文件路径（艺术家用 & 拼接）
            file_path = self._target_path(music_info)

            # 已存在则跳过下载，否则执行核心下载逻辑
            if file_path.exists():
                self.logger.info(f"文件已存在: {file_path.name}")
            else:
                download_result = self.download_music_file(music_info, quality)
                if not download_result.success:
                    return DownloadResult(
                        success=False,
                        error_message=f"下载失败: {download_result.error_message}",
                        music_info=music_info
                    )
                file_path = Path(download_result.file_path)
                self.logger.info(f"下载完成: {file_path.name}")

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
    
    
    def is_song_already_downloaded(self, name: str, artists: List[str]) -> bool:
        """
        仅凭歌名+艺术家判断本地是否已下载（零网络请求，可在拉取下载信息前先行筛除）。

        不依赖下载链接，因此对所有已支持的扩展名都做一次存在性检查，
        命中任意一种即视为已下载。

        Args:
            name: 歌曲名
            artists: 艺术家列表

        Returns:
            是否已下载
        """
        try:
            stem = self._target_stem(name, artists)
            # 仅用文件名判断（哈希校验暂未启用）
            return any(
                (self.download_dir / f"{stem}.{ext}").exists()
                for ext in self.supported_formats
            )
        except Exception as e:
            self.logger.error(f"检查歌曲是否已下载时出错: {str(e)}")
            return False
    
    
    
    def download_music_file(self, music_info: MusicInfo, quality: str = "standard") -> DownloadResult:
        """下载音乐文件到本地（原子写入 + 完整性校验）。

        先落临时 .part 文件，按接口给出的大小校验完整后，再原子改名为最终文件。
        这样下载中途失败/进程被杀只会残留 .part，绝不会污染最终文件名，从而避免
        "截断文件被后续运行当成已下载而永久跳过"的问题。调用方已确认目标文件不存在。
        """
        file_path = self._target_path(music_info)
        tmp_path = file_path.with_name(file_path.name + '.part')
        try:
            response = requests.get(music_info.download_url, stream=True, timeout=30)
            response.raise_for_status()

            downloaded = 0
            with open(tmp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            # 完整性校验：与接口给出的原始音频大小比对（大小已知时），不符视为失败并重试下轮
            expected = music_info.file_size or 0
            if expected > 0 and downloaded != expected:
                raise DownloadException(
                    f"下载不完整：期望 {expected} 字节，实际 {downloaded} 字节"
                )

            # 原子改名到最终路径，再写标签（须在大小校验之后；标签写失败也只是缺元信息，文件仍完整可用）
            os.replace(tmp_path, file_path)
            write_tags(file_path, music_info)

            return DownloadResult(
                success=True,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                music_info=music_info
            )

        except requests.RequestException as e:
            return DownloadResult(success=False, error_message=f"下载请求失败: {e}")
        except DownloadException as e:
            return DownloadResult(success=False, error_message=str(e))
        except Exception as e:
            return DownloadResult(success=False, error_message=f"下载过程中发生错误: {e}")
        finally:
            # 清理可能残留的临时文件（成功路径已 os.replace 掉；不存在则忽略）
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
