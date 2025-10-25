
import logging
from datetime import datetime
import json
import urllib.parse
from random import randrange
from typing import Dict, List, Optional, Tuple, Any
from hashlib import md5
from enum import Enum

from aiohttp import request
import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from datetime import datetime

class QualityLevel(Enum):
    """音质等级枚举"""
    STANDARD = "standard"      # 标准音质
    EXHIGH = "exhigh"          # 极高音质
    LOSSLESS = "lossless"      # 无损音质
    HIRES = "hires"            # Hi-Res音质
    SKY = "sky"                # 沉浸环绕声
    JYEFFECT = "jyeffect"      # 高清环绕声
    JYMASTER = "jymaster"      # 超清母带

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


# 常量定义
class APIConstants:
    """API相关常量"""
    AES_KEY = b"e82ckenh8dichen8"
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/2.10.2.200154'
    REFERER = 'https://music.163.com/'
    
    # API URLs
    SONG_URL_V1 = "https://interface3.music.163.com/eapi/song/enhance/player/url/v1"
    SONG_DETAIL_V3 = "https://interface3.music.163.com/api/v3/song/detail"
    LYRIC_API = "https://interface3.music.163.com/api/song/lyric"
    SEARCH_API = 'https://music.163.com/api/cloudsearch/pc'
    PLAYLIST_DETAIL_API = 'https://music.163.com/api/v6/playlist/detail'
    ALBUM_DETAIL_API = 'https://music.163.com/api/v1/album/'
    QR_UNIKEY_API = 'https://interface3.music.163.com/eapi/login/qrcode/unikey'
    QR_LOGIN_API = 'https://interface3.music.163.com/eapi/login/qrcode/client/login'

    #// 个人歌单
    PERSONAL_PLAYLIST_API='https://music.163.com/api/user/playlist'

    
    # 默认配置
    DEFAULT_CONFIG = {
        "os": "pc",
        "appver": "",
        "osver": "",
        "deviceId": "pyncm!"
    }
    
    DEFAULT_COOKIES = {
        "os": "pc",
        "appver": "",
        "osver": "",
        "deviceId": "pyncm!"
    }


class CryptoUtils:
    """加密工具类"""
    
    @staticmethod
    def hex_digest(data: bytes) -> str:
        """将字节数据转换为十六进制字符串"""
        return "".join([hex(d)[2:].zfill(2) for d in data])
    
    @staticmethod
    def hash_digest(text: str) -> bytes:
        """计算MD5哈希值"""
        return md5(text.encode("utf-8")).digest()
    
    @staticmethod
    def hash_hex_digest(text: str) -> str:
        """计算MD5哈希值并转换为十六进制字符串"""
        return CryptoUtils.hex_digest(CryptoUtils.hash_digest(text))
    
    @staticmethod
    def encrypt_params(url: str, payload: Dict[str, Any]) -> str:
        """加密请求参数"""
        url_path = urllib.parse.urlparse(url).path.replace("/eapi/", "/api/")
        digest = CryptoUtils.hash_hex_digest(f"nobody{url_path}use{json.dumps(payload)}md5forencrypt")
        params = f"{url_path}-36cd479b6b5-{json.dumps(payload)}-36cd479b6b5-{digest}"
        
        # AES加密
        padder = padding.PKCS7(algorithms.AES(APIConstants.AES_KEY).block_size).padder()
        padded_data = padder.update(params.encode()) + padder.finalize()
        cipher = Cipher(algorithms.AES(APIConstants.AES_KEY), modes.ECB())
        encryptor = cipher.encryptor()
        enc = encryptor.update(padded_data) + encryptor.finalize()
        
        return CryptoUtils.hex_digest(enc)


class HTTPClient:
    """HTTP客户端类"""
    
    @staticmethod
    def post_request(url: str, params: str, cookies: Dict[str, str]) -> str:
        """发送POST请求并返回文本响应"""
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
        }
        
        request_cookies = APIConstants.DEFAULT_COOKIES.copy()
        request_cookies.update(cookies)
        
        try:
            response = requests.post(url, headers=headers, cookies=request_cookies, 
                                   data={"params": params}, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")
    
    @staticmethod
    def post_request_full(url: str, params: str, cookies: Dict[str, str]) -> requests.Response:
        """发送POST请求并返回完整响应对象"""
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
        }
        
        request_cookies = APIConstants.DEFAULT_COOKIES.copy()
        request_cookies.update(cookies)
        
        try:
            response = requests.post(url, headers=headers, cookies=request_cookies, 
                                   data={"params": params}, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")
        
class APIException(Exception):
    """API异常类"""
    pass


class NeteaseMusic:
    def __init__(self, cookies: Dict[str, str]):
        self.http_client = HTTPClient()
        self.crypto_utils = CryptoUtils()
        self.cookies = cookies
        self.logger = logging.getLogger(__name__)
        
    def get_user_playlist(self, uid: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取用户的歌单列表详情
        
        Args:
            uid: 用户ID
            cookies: 用户登录态cookies
            
        Returns:
            包含处理后的歌单列表的字典，结构如下：
            {
                "total": int,  # 歌单总数
                "playlists": [
                    {
                        "id": int,  # 歌单ID
                        "name": str,  # 歌单名称
                        "track_count": int,  # 歌曲数量
                        "update_time": str,  # 歌单更新时间（YYYY-MMMM-DDDD）
                        "track_update_time": str  # 歌曲更新时间（YYYY-MMMM-DDDD）
                    },
                    ...
                ]
            }
            
        Raises:
            APIException: API调用失败或响应解析错误时抛出
        """
        try:
            # 构建请求参数
            data = {
                'uid': uid,
                'offset': 0,
                'limit': 20
            }
            
            # 构建请求头
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # 发送POST请求
            response = requests.post(
                url=APIConstants.PERSONAL_PLAYLIST_API,
                data=data,
                headers=headers,
                cookies=cookies,
                timeout=30
            )
            response.raise_for_status()  # 抛出HTTP错误状态码
            
            # 解析响应JSON
            result = response.json()
            
            # 检查API返回状态
            if result.get('code') != 200:
                raise APIException(f"获取用户歌单失败: {result.get('message', '未知错误')}")
            
            # 提取歌单列表（确保为列表类型）
            playlists: List[Dict[str, Any]] = result.get('playlist', [])
            processed_playlists = []
            
            # 遍历处理每个歌单
            for playlist in playlists:
                # 转换时间戳（使用类内时间转换方法）
                update_time = self._timestamp_str_to_date(playlist.get('updateTime', ''))
                track_update_time = self._timestamp_str_to_date(playlist.get('trackUpdateTime', ''))
                
                # 封装处理后的歌单信息
                processed_playlist = {
                    'id': playlist.get('id'),
                    'name': playlist.get('name'),
                    'track_count': playlist.get('trackCount'),
                    'update_time': update_time,
                    'track_update_time': track_update_time
                }
                processed_playlists.append(processed_playlist)
            
            # 构建返回结果
            return {
                'total': len(processed_playlists),
                'playlists': processed_playlists
            }
            
        except requests.RequestException as e:
            raise APIException(f"获取用户歌单请求失败: {str(e)}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析用户歌单响应失败: {str(e)}")
        except Exception as e:
            raise APIException(f"处理用户歌单时发生未知错误: {str(e)}")
        
    def get_playlist_detail(self, playlist_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌单详情
        
        Args:
            playlist_id: 歌单ID
            cookies: 用户cookies
            
        Returns:
            歌单详情信息
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'id': playlist_id}
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.PLAYLIST_DETAIL_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌单详情失败: {result.get('message', '未知错误')}")
            
            playlist = result.get('playlist', {})
            # 网易云API的album.publishTime为13位毫秒级时间戳
            create_timestamp = playlist.get('createTime')
            # 转换为年月日格式（调用工具函数）
            create_time = self._timestamp_str_to_date(create_timestamp)
            info = {
                'id': playlist.get('id'),
                'name': playlist.get('name'),
                'createTime' : create_time,
                'coverImgUrl': playlist.get('coverImgUrl'),
                'creator': playlist.get('creator', {}).get('nickname', ''),
                'trackCount': playlist.get('trackCount'),
                'description': playlist.get('description', ''),
                'tracks': []
            }
            
            # 获取所有trackIds并分批获取详细信息
            track_ids = [str(t['id']) for t in playlist.get('trackIds', [])]
            for i in range(0, len(track_ids), 100):
                batch_ids = track_ids[i:i+100]
                song_data = {'c': json.dumps([{'id': int(sid), 'v': 0} for sid in batch_ids])}
                
                song_resp = requests.post(APIConstants.SONG_DETAIL_V3, data=song_data, 
                                        headers=headers, cookies=cookies, timeout=30)
                song_resp.raise_for_status()
                
                song_result = song_resp.json()
                for song in song_result.get('songs', []):
                    info['tracks'].append({
                        'id': song['id'],
                        'name': song['name'],
                        'artists': '/'.join(artist['name'] for artist in song['ar']),
                        'album': song['al']['name'],
                        'picUrl': song['al']['picUrl']
                    })
            
            return info
        except requests.RequestException as e:
            raise APIException(f"获取歌单详情请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析歌单详情响应失败: {e}")
    
    def get_album_detail(self, album_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取专辑详情
        
        Args:
            album_id: 专辑ID
            cookies: 用户cookies
            
        Returns:
            专辑详情信息
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            url = f'{APIConstants.ALBUM_DETAIL_API}{album_id}'
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取专辑详情失败: {result.get('message', '未知错误')}")
            
            album = result.get('album', {})
            info = {
                'id': album.get('id'),
                'name': album.get('name'),
                'coverImgUrl': self.get_pic_url(album.get('pic')),
                'artist': album.get('artist', {}).get('name', ''),
                'publishTime': album.get('publishTime'),
                'description': album.get('description', ''),
                'songs': []
            }
            
            for song in result.get('songs', []):
                info['songs'].append({
                    'id': song['id'],
                    'name': song['name'],
                    'artists': '/'.join(artist['name'] for artist in song['ar']),
                    'album': song['al']['name'],
                    'picUrl': self.get_pic_url(song['al'].get('pic'))
                })
            
            return info
        except requests.RequestException as e:
            raise APIException(f"获取专辑详情请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析专辑详情响应失败: {e}")
    

    def find_todays_playlist(self, uid: int, tdl: str) -> Dict[str, Any] | None:
        """
        查找今天日期命名的播放列表
        
        Args:
            uid: 用户ID
            
        Returns:
            找到的播放列表，或None
        """
        self.logger.info(f"查找名称为 {tdl} 的播放列表")
        
        playlists = self.get_user_playlist(uid, self.cookies)
        
        for playlist in playlists.get("playlists", []):
            if playlist.get("name") == tdl:
                self.logger.info(f"找到今日播放列表: {playlist.get('id')}")
                return playlist
        
        self.logger.warning(f"未找到名称为 {tdl} 的播放列表")
        return None
    
    def netease_encrypt_id(self, id_str: str) -> str:
        """网易云加密图片ID算法
        
        Args:
            id_str: 图片ID字符串
            
        Returns:
            加密后的字符串
        """
        import base64
        import hashlib
        
        magic = list('3go8&$8*3*3h0k(2)2')
        song_id = list(id_str)
        
        for i in range(len(song_id)):
            song_id[i] = chr(ord(song_id[i]) ^ ord(magic[i % len(magic)]))
        
        m = ''.join(song_id)
        md5_bytes = hashlib.md5(m.encode('utf-8')).digest()
        result = base64.b64encode(md5_bytes).decode('utf-8')
        result = result.replace('/', '_').replace('+', '-')
        
        return result
    

    def get_pic_url(self, pic_id: Optional[int], size: int = 300) -> str:
        """获取网易云加密歌曲/专辑封面直链
        
        Args:
            pic_id: 封面ID
            size: 图片尺寸
            
        Returns:
            图片URL
        """
        if pic_id is None:
            return ''
        
        enc_id = self.netease_encrypt_id(str(pic_id))
        return f'https://p3.music.126.net/{enc_id}/{pic_id}.jpg?param={size}y{size}'

    
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
                timestamp *= 100  # 转换为13位（如13053888000 → 1305388800000）
            
            # 2. 验证13位时间戳（毫秒级）
            if not (10**12 <= timestamp_int < 10**13):  # 13位数字范围（1000000000000 ~ 9999999999999）
                return ""
            
            # 3. 转换为年月日（毫秒级时间戳需÷1000）
            return datetime.fromtimestamp(timestamp_int / 1000).strftime("%Y-%m-%d")
        
        except (ValueError, TypeError, OSError):
            # 处理异常情况（如数值溢出、非整数类型等）
            return ""

    def get_song_url(self, song_id: int, quality: str, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌曲播放URL
        
        Args:
            song_id: 歌曲ID
            quality: 音质等级 (standard, exhigh, lossless, hires, sky, jyeffect, jymaster)
            cookies: 用户cookies
            
        Returns:
            包含歌曲URL信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'ids': [song_id],
                'level': quality,
                'encodeType': 'flac',
                'header': json.dumps(config),
            }
            
            if quality == 'sky':
                payload['immerseType'] = 'c51'
            
            params = self.crypto_utils.encrypt_params(APIConstants.SONG_URL_V1, payload)
            response_text = self.http_client.post_request(APIConstants.SONG_URL_V1, params, cookies)
            
            result = json.loads(response_text)
            if result.get('code') != 200:
                raise APIException(f"获取歌曲URL失败: {result.get('message', '未知错误')}")
            
            return result
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析响应数据失败: {e}")
    
    def get_song_detail(self, song_id: int) -> Dict[str, Any]:
        """获取歌曲详细信息
        
        Args:
            song_id: 歌曲ID
            
        Returns:
            包含歌曲详细信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'c': json.dumps([{"id": song_id, "v": 0}])}
            response = requests.post(APIConstants.SONG_DETAIL_V3, data=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌曲详情失败: {result.get('message', '未知错误')}")
            
            return result
        except requests.RequestException as e:
            raise APIException(f"获取歌曲详情请求失败: {e}")
        except json.JSONDecodeError as e:
            raise APIException(f"解析歌曲详情响应失败: {e}")
    
    def get_lyric(self, song_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌词信息
        
        Args:
            song_id: 歌曲ID
            cookies: 用户cookies
            
        Returns:
            包含歌词信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {
                'id': song_id, 
                'cp': 'false', 
                'tv': '0', 
                'lv': '0', 
                'rv': '0', 
                'kv': '0', 
                'yv': '0', 
                'ytv': '0', 
                'yrv': '0'
            }
            
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.LYRIC_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌词失败: {result.get('message', '未知错误')}")
            
            return result
        except requests.RequestException as e:
            raise APIException(f"获取歌词请求失败: {e}")
        except json.JSONDecodeError as e:
            raise APIException(f"解析歌词响应失败: {e}")
        
    def _get_quality_display_name(self, quality: str) -> str:
        """获取音质显示名称"""
        quality_names = {
            'standard': "标准音质",
            'exhigh': "极高音质", 
            'lossless': "无损音质",
            'hires': "Hi-Res音质",
            'sky': "沉浸环绕声",
            'jyeffect': "高清环绕声",
            'jymaster': "超清母带"
        }
        return quality_names.get(quality, f"未知音质({quality})")
    
    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes == 0:
            return "0B"
        
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(size_bytes)
        unit_index = 0
        
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        
        return f"{size:.2f}{units[unit_index]}"
    
    def _get_quality_display_name(self, quality: str) -> str:
        """获取音质显示名称"""
        quality_names = {
            'standard': "标准音质",
            'exhigh': "极高音质", 
            'lossless': "无损音质",
            'hires': "Hi-Res音质",
            'sky': "沉浸环绕声",
            'jyeffect': "高清环绕声",
            'jymaster': "超清母带"
        }
        return quality_names.get(quality, f"未知音质({quality})")
    
    def _validate_request_params(self, required_params: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], int]]:
        """验证请求参数"""
        for param_name, param_value in required_params.items():
            if not param_value:
                return APIResponse.error(f"参数 '{param_name}' 不能为空", 400)
        return None
    
    # 向后兼容的函数接口
def url_v1(song_id: int, level: str, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌曲URL（向后兼容）"""
    api = NeteaseMusic()
    return api.get_song_url(song_id, level, cookies)


def name_v1(song_id: int) -> Dict[str, Any]:
    """获取歌曲详情（向后兼容）"""
    api = NeteaseMusic()
    return api.get_song_detail(song_id)


def lyric_v1(song_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌词（向后兼容）"""
    api = NeteaseMusic()
    return api.get_lyric(song_id, cookies)

def search_music(keywords: str, cookies: Dict[str, str], limit: int = 10) -> List[Dict[str, Any]]:
    """搜索音乐（向后兼容）"""
    api = NeteaseMusic()
    return api.search_music(keywords, cookies, limit)


def playlist_detail(playlist_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌单详情（向后兼容）"""
    api = NeteaseMusic()
    return api.get_playlist_detail(playlist_id, cookies)

def user_playlist(uid: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取用户（向后兼容）"""
    api = NeteaseMusic()
    return api.get_user_playlist(uid, cookies)


def album_detail(album_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取专辑详情（向后兼容）"""
    api = NeteaseMusic()
    return api.get_album_detail(album_id, cookies)


def get_pic_url(pic_id: Optional[int], size: int = 300) -> str:
    """获取图片URL（向后兼容）"""
    api = NeteaseMusic()
    return api.get_pic_url(pic_id, size)



