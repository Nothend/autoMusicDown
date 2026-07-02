
import base64
import hashlib
import logging
import json
from random import randrange
from typing import Dict, List, Optional, Any

import requests

from constants import APIConstants
from crypto import CryptoUtils
from http_client import SESSION, HTTPClient, APIException
from utils import timestamp_to_date


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
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # 分页拉取：用户会日积月累地新建"以日期命名"的歌单，单页 20 条会漏掉排在后面的
        # 今日歌单，这里翻页取全（每页 100 条，最多 2000 条兜底，避免异常情况下无限翻页）。
        PAGE_SIZE = 100
        MAX_PLAYLISTS = 2000
        try:
            processed_playlists: List[Dict[str, Any]] = []
            offset = 0
            while offset < MAX_PLAYLISTS:
                data = {'uid': uid, 'offset': offset, 'limit': PAGE_SIZE}
                response = SESSION.post(
                    url=APIConstants.PERSONAL_PLAYLIST_API,
                    data=data, headers=headers, cookies=cookies, timeout=30,
                )
                response.raise_for_status()  # 抛出HTTP错误状态码

                result = response.json()
                if result.get('code') != 200:
                    raise APIException(f"获取用户歌单失败: {result.get('message', '未知错误')}")

                playlists: List[Dict[str, Any]] = result.get('playlist', []) or []
                for playlist in playlists:
                    # 转换时间戳（使用工具函数）并封装处理后的歌单信息
                    processed_playlists.append({
                        'id': playlist.get('id'),
                        'name': playlist.get('name'),
                        'track_count': playlist.get('trackCount'),
                        'update_time': timestamp_to_date(playlist.get('updateTime', '')),
                        'track_update_time': timestamp_to_date(playlist.get('trackUpdateTime', '')),
                    })

                # 网易云用 more 标记是否还有下一页；再以"本页不足一页"兜底终止
                if not result.get('more') or len(playlists) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

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
            
            response = SESSION.post(APIConstants.PLAYLIST_DETAIL_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌单详情失败: {result.get('message', '未知错误')}")
            
            playlist = result.get('playlist', {})
            # 网易云API的album.publishTime为13位毫秒级时间戳
            create_timestamp = playlist.get('createTime')
            # 转换为年月日格式（调用工具函数）
            create_time = timestamp_to_date(create_timestamp)
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
                
                song_resp = SESSION.post(APIConstants.SONG_DETAIL_V3, data=song_data, 
                                        headers=headers, cookies=cookies, timeout=30)
                song_resp.raise_for_status()
                
                song_result = song_resp.json()
                for song in song_result.get('songs', []):
                    info['tracks'].append({
                        'id': song['id'],
                        'name': song['name'],
                        'artists': [artist['name'] for artist in song['ar']],
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
            
            response = SESSION.get(url, headers=headers, cookies=cookies, timeout=30)
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
                    'artists': [artist['name'] for artist in song['ar']],
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
        magic = list('3go8&$8*3*3h0k(2)2')
        song_id = list(id_str)
        
        for i in range(len(song_id)):
            song_id[i] = chr(ord(song_id[i]) ^ ord(magic[i % len(magic)]))
        
        m = ''.join(song_id)
        md5_bytes = hashlib.md5(m.encode('utf-8')).digest()
        result = base64.b64encode(md5_bytes).decode('utf-8')
        result = result.replace('/', '_').replace('+', '-')
        
        return result
    

    def is_cookie_valid(self) -> Dict[str, bool]:
        """检查Cookie是否有效并判断是否为VIP
        返回格式: {
            'valid': bool,    # Cookie是否有效
            'is_vip': bool    # 是否为VIP（vipType != 0 视为VIP）
        }
        """
        try:
            # 若未传入cookies，直接返回无效且非VIP
            if not self.cookies:
                return {'valid': False, 'is_vip': False}
            
            # 调用用户账号信息接口验证登录状态
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            # 发送请求（该接口无需复杂参数，仅需登录态Cookie）
            response = SESSION.post(
                APIConstants.USER_ACCOUNT_API,
                headers=headers,
                cookies=self.cookies,
                timeout=30
            )
            response.raise_for_status()  # 抛出HTTP错误（如403、500等）
            
            result = response.json()
            
            # 验证响应：code=200且包含用户信息（profile字段）则视为有效
            if result.get('code') == 200 and result.get('profile') is not None:
                # 从account中获取vipType，默认为0（非VIP）
                vip_type = result.get('account', {}).get('vipType', 0)
                # 非0视为VIP
                is_vip = vip_type != 0
                return {'valid': True, 'is_vip': is_vip}
            else:
                # 无效Cookie，默认非VIP
                if result.get('code') != 200:
                    self.logger.warning(f"Cookie无效：响应码非200（实际：{result.get('code')}）")
                else:
                    self.logger.warning(f"Cookie无效：profile为None（{result.get('profile')}）")
                return {'valid': False, 'is_vip': False}

        except requests.RequestException as e:
            self.logger.error(f"Cookie验证请求失败: {e}")
            return {'valid': False, 'is_vip': False}
        except json.JSONDecodeError as e:
            self.logger.error(f"解析验证响应失败: {e}")
            return {'valid': False, 'is_vip': False}
        except Exception as e:
            self.logger.error(f"Cookie验证发生未知错误: {e}")
            return {'valid': False, 'is_vip': False}

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
    
    def get_song_detail(self, song_id: int, cookies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """获取歌曲详细信息

        Args:
            song_id: 歌曲ID
            cookies: 用户cookies（缺省时用实例自身的 cookies，与其他接口保持一致）

        Returns:
            包含歌曲详细信息的字典

        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'c': json.dumps([{"id": song_id, "v": 0}])}
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            response = SESSION.post(APIConstants.SONG_DETAIL_V3, data=data,
                                    headers=headers, cookies=cookies or self.cookies, timeout=30)
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
            
            response = SESSION.post(APIConstants.LYRIC_API, data=data, 
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



