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

    def send_download_report(
        self, 
        total_songs: int, 
        library_exists: int, 
        local_exists: int, 
        should_download: int
    ) -> bool:
        """发送详细下载统计报告（包含歌单总数、库中存在数、本地存在数、应下载数）"""
        if not self.enabled:
            self.logger.debug("Bark通知功能未启用，跳过下载报告发送")
            return False

        # 格式化通知内容，分行展示统计信息
        content = (
            f"歌单共{total_songs}首\n"
            f"库中已存在{library_exists}首\n"
            f"本地已存在{local_exists}首\n"
            f"应下载{should_download}首"
        )
        return self.send_notification("音乐自动下载统计", content)
    
    def send_download_result(self, success: int, failed: int, total: int) -> bool:
        """发送下载阶段的结果报告（成功/失败数量）"""
        if not self.enabled:
            self.logger.debug("Bark通知功能未启用，跳过下载结果报告")
            return False
        content = f"应下载{total}首\n成功{success}首\n失败{failed}首"
        return self.send_notification("音乐下载结果", content)