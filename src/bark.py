import requests
import logging
from typing import List, Dict, Any


class BarkNotifier:
    def __init__(self, api_url: str):
        self.api_url = api_url.strip() if api_url else ""
        self.logger = logging.getLogger(__name__)
        # 仅根据URL是否为空判断是否启用（不为空则尝试发送）
        self.enabled = bool(self.api_url)
        if self.enabled:
            self.logger.info("Bark通知功能已启用（发送时将尝试连接）")
        else:
            self.logger.info("Bark API URL未设置，通知功能已禁用")

    def send_notification(self, title: str, content: str) -> bool:
        """发送Bark通知（若功能未启用则直接返回False，发送失败记录日志）"""
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