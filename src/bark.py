import requests
import logging
import re
from typing import List, Dict, Any


class BarkNotifier:
    def __init__(self, api_url: str):
        self.api_url = api_url.strip() if api_url else ""
        self.logger = logging.getLogger(__name__)
        self.enabled = self._check_api_validity()  # 标记通知功能是否可用

    def _check_api_validity(self) -> bool:
        """检查API URL是否合法，返回功能是否启用"""
        # 1. 检查URL是否为空
        if not self.api_url:
            self.logger.info("Bark API URL未设置，通知功能已禁用")
            return False

        # 2. 检查URL格式是否合法（简单校验：http/https开头，包含有效域名结构）
        url_pattern = re.compile(
            r'^https?://'  # 必须以http或https开头
            r'([a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+'  # 包含至少一个域名段（如api.day.app）
            r'(/.*)?$'  # 可选的路径部分
        )

        if not url_pattern.match(self.api_url):
            self.logger.error(
                f"Bark API URL格式不合法: {self.api_url} "
                f"（需符合http(s)://域名/路径格式，例如https://api.day.app/your_key）"
            )
            return False

        # 3. 简单连通性测试（可选，避免无效URL）
        try:
            # 仅发送HEAD请求验证是否可达（不消耗过多资源）
            requests.head(self.api_url, timeout=5)
            self.logger.info("Bark通知功能已启用")
            return True
        except requests.exceptions.RequestException as e:
            self.logger.warning(
                f"Bark API URL连通性测试失败（可能暂时不可达）: {str(e)} "
                f"（通知功能将尝试启用，发送时若失败会记录错误）"
            )
            return True  # 连通性问题不强制禁用，保留发送机会

    def send_notification(self, title: str, content: str) -> bool:
        """发送Bark通知（若功能未启用则直接返回False）"""
        if not self.enabled:
            self.logger.debug("Bark通知功能未启用，跳过发送")
            return False

        try:
            response = requests.post(
                self.api_url,
                params={"title": title, "body": content},
                timeout=10  # 设置超时时间，避免阻塞
            )
            response.raise_for_status()  # 触发HTTP错误（如404、500）
            self.logger.info("Bark通知发送成功")
            return True
        except Exception as e:
            self.logger.error(f"Bark通知发送失败: {str(e)}")
            return False

    def send_download_report(self, success_songs: List[Dict[str, Any]], failed_songs: List[Dict[str, Any]]) -> bool:
        """发送精简的下载报告（仅包含数量统计）"""
        if not self.enabled:
            self.logger.debug("Bark通知功能未启用，跳过下载报告发送")
            return False

        total = len(success_songs) + len(failed_songs)
        content = f"共 {total} 首，成功 {len(success_songs)} 首，失败 {len(failed_songs)} 首"
        return self.send_notification("音乐自动下载报告", content)