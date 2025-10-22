import requests
import logging
from typing import List, Dict, Any

class BarkNotifier:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.logger = logging.getLogger(__name__)
        
    def send_notification(self, title: str, content: str) -> bool:
        """
        发送Bark通知
        
        Args:
            title: 通知标题
            content: 通知内容
            
        Returns:
            发送是否成功
        """
        try:
            response = requests.post(
                self.api_url,
                params={
                    "title": title,
                    "body": content
                }
            )
            response.raise_for_status()
            self.logger.info("Bark 通知发送成功")
            return True
        except Exception as e:
            self.logger.error(f"Bark 通知发送失败: {str(e)}")
            return False
    
    def send_download_report(self, success_songs: List[Dict[str, Any]], failed_songs: List[Dict[str, Any]]) -> bool:
        """
        发送下载报告
        
        Args:
            success_songs: 下载成功的歌曲
            failed_songs: 下载失败的歌曲
            
        Returns:
            发送是否成功
        """
        title = "音乐下载报告"
        
        success_count = len(success_songs)
        failed_count = len(failed_songs)
        total_count = success_count + failed_count
        
        content = f"共 {total_count} 首歌曲，成功 {success_count} 首，失败 {failed_count} 首\n\n"
        
        if success_songs:
            content += "成功下载:\n"
            for song in success_songs[:5]:  # 只显示前5首
                artists = song.get("artists", "")
                content += f"- {artists} - {song.get('name')}\n"
            if len(success_songs) > 5:
                content += f"... 还有 {len(success_songs) - 5} 首\n\n"
        
        if failed_songs:
            content += "下载失败:\n"
            for song in failed_songs[:5]:  # 只显示前5首
                artists = song.get("artists", "")
                content += f"- {artists} - {song.get('name')}\n"
            if len(failed_songs) > 5:
                content += f"... 还有 {len(failed_songs) - 5} 首\n"
        
        return self.send_notification(title, content)