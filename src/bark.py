import requests
import logging
from typing import List, Dict, Any

class BarkNotifier:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.logger = logging.getLogger(__name__)
        
    def send_notification(self, title: str, content: str) -> bool:
        """发送Bark通知"""
        try:
            response = requests.post(
                self.api_url,
                params={"title": title, "body": content}
            )
            response.raise_for_status()
            self.logger.info("Bark 通知发送成功")
            return True
        except Exception as e:
            self.logger.error(f"Bark 通知发送失败: {str(e)}")
            return False
    
    def send_download_report(self, success_songs: List[Dict[str, Any]], failed_songs: List[Dict[str, Any]]) -> bool:
        """发送精简的下载报告（仅包含数量统计）"""
        total = len(success_songs) + len(failed_songs)
        content = f"共 {total} 首，成功 {len(success_songs)} 首，失败 {len(failed_songs)} 首"
        return self.send_notification("音乐自动下载报告", content)