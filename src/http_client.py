"""HTTP 层：全局共享 Session（带重试/退避）+ 简单的 eapi POST 封装。"""

from typing import Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from constants import APIConstants

# 全局共享 Session：网易云的反作弊会通过 Set-Cookie 下发设备 cookie（如 NMTID），
# song/url 接口要求请求带上这些 cookie，否则返回 -462「网络环境存在风险」。
# 用同一个 Session 让前序请求（账号校验、取歌单等）拿到的 cookie 自动延续到后续请求。
SESSION = requests.Session()

# 限流/容错：单次任务会对 30 首歌各打 4 个接口（url/detail/album/lyric），属于突发请求。
# 给 Session 挂上重试适配器，遇到 429/5xx 自动按退避重试，并遵守服务端的 Retry-After 头，
# 降低被限流（429）或重新触发风控的概率。
_RETRY = Retry(
    total=3,
    backoff_factor=1.5,                       # 退避间隔：1.5s, 3s, 6s
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]),
    respect_retry_after_header=True,
    raise_on_status=False,
)
_ADAPTER = HTTPAdapter(max_retries=_RETRY)
SESSION.mount("https://", _ADAPTER)
SESSION.mount("http://", _ADAPTER)


class APIException(Exception):
    """API异常类"""
    pass


class HTTPClient:
    """HTTP客户端类"""

    @staticmethod
    def post_request(url: str, params: str, cookies: Dict[str, str]) -> str:
        """发送POST请求并返回文本响应"""
        return HTTPClient.post_request_full(url, params, cookies).text

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
            response = SESSION.post(url, headers=headers, cookies=request_cookies,
                                    data={"params": params}, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")
