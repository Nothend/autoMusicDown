"""Cookie管理器模块（无文件操作版）

提供网易云音乐Cookie管理功能，包括：
- Cookie格式验证和解析
- Cookie有效性检查
- 适用于请求的Cookie处理
"""

import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from config import Config
@dataclass
class CookieInfo:
    """Cookie信息数据类"""
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: Optional[int] = None
    secure: bool = False
    http_only: bool = False


class CookieException(Exception):
    """Cookie相关异常类"""
    pass


class CookieManager:
    """Cookie管理器主类（无文件操作，基于内存处理）"""
    
    def __init__(self, config: Config):
        self.logger = logging.getLogger(__name__)


        """初始化Cookie管理器（无文件依赖）"""
        self.cookie_string: str = "" # 存储原始Cookie字符串
        self.parsed_cookies: Dict[str, str] = []  # 解析后的Cookie字典
        self.set_cookie_string(config.get("cookie"))
        
        
        # 网易云音乐相关的重要Cookie字段
        self.important_cookies = {
            'MUSIC_U',      # 用户标识
            'MUSIC_A',      # 用户认证
            '__csrf',       # CSRF令牌
            'NMTID',        # 设备标识
            'WEVNSM',       # 会话管理
            'WNMCID',       # 客户端标识
        }
    
    def set_cookie_string(self, cookie_str: str) -> None:
        """
        设置Cookie原始字符串并解析
        
        Args:
            cookie_string: 从配置获取的Cookie字符串
        """
        self.cookie_string = cookie_str.strip()
        # 立即解析并缓存
        self.parsed_cookies = self.parse_cookie_string(self.cookie_string)
        self.logger.debug(f"已设置并解析Cookie，包含 {len(self.parsed_cookies)} 个字段")
    
    def parse_cookie_string(self, cookie_str: str) -> Dict[str, str]:
        """
        解析Cookie字符串为字典
        
        Args:
            cookie_string: Cookie字符串
            
        Returns:
            解析后的Cookie字典
        """
        if not cookie_str or not cookie_str.strip():
            self.logger.warning("Cookie字符串为空，返回空字典")
            return {}
        
        cookies = {}
        
        try:
            # 处理多种Cookie格式（分号或换行分隔）
            cookie_str = cookie_str.strip()
            cookie_pairs = []
            
            if ';' in cookie_str:
                cookie_pairs = cookie_str.split(';')
            elif '\n' in cookie_str:
                cookie_pairs = cookie_str.split('\n')
            else:
                cookie_pairs = [cookie_str]
            
            for pair in cookie_pairs:
                pair = pair.strip()
                if not pair or '=' not in pair:
                    continue
                
                # 分割键值对（只分割第一个等号）
                key, value = pair.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key and value:
                    cookies[key] = value
            
            self.logger.debug(f"解析Cookie成功，共 {len(cookies)} 个有效字段")
            return cookies
            
        except Exception as e:
            self.logger.error(f"解析Cookie字符串失败: {str(e)}")
            return {}
    
    def validate_cookie_format(self, cookie_string: Optional[str] = None) -> bool:
        """
        验证Cookie格式是否有效
        
        Args:
            cookie_string: 可选，指定要验证的Cookie字符串；默认使用已设置的字符串
            
        Returns:
            是否格式有效
        """
        target_str = cookie_string.strip() if cookie_string else self._cookie_string
        if not target_str:
            self.logger.warning("Cookie字符串为空，格式无效")
            return False
        
        try:
            # 尝试解析验证
            cookies = self.parse_cookie_string(target_str)
            if not cookies:
                return False
            
            # 检查Cookie键名合法性（不含非法字符）
            invalid_chars = {' ', '\t', '\n', '\r', ';', ','}
            for name in cookies.keys():
                if not name or any(char in name for char in invalid_chars):
                    self.logger.warning(f"Cookie键名包含非法字符: {name}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Cookie格式验证失败: {str(e)}")
            return False
    
    def is_cookie_valid(self) -> bool:
        """
        检查Cookie是否有效（包含必要字段）
        
        Returns:
            Cookie是否有效
        """
        if not self._parsed_cookies:
            self.logger.warning("Cookie未解析或为空，无效")
            return False
        
        # 检查重要Cookie字段是否存在
        missing = self.important_cookies - set(self._parsed_cookies.keys())
        if missing:
            self.logger.warning(f"缺少重要Cookie字段: {missing}")
            return False
        
        # 基础验证MUSIC_U有效性
        music_u = self._parsed_cookies.get('MUSIC_U', '')
        if not music_u or len(music_u) < 10:
            self.logger.warning("MUSIC_U字段无效（过短或为空）")
            return False
        
        self.logger.debug("Cookie验证通过（包含所有必要字段）")
        return True
    
    
    def get_cookie_info(self) -> Dict[str, Any]:
        """
        获取Cookie详细信息
        
        Returns:
            包含Cookie状态的字典
        """
        return {
            'cookie_length': len(self._cookie_string),
            'parsed_count': len(self._parsed_cookies),
            'is_valid': self.is_cookie_valid(),
            'important_present': list(self.important_cookies & set(self._parsed_cookies.keys())),
            'important_missing': list(self.important_cookies - set(self._parsed_cookies.keys())),
            'last_updated': datetime.now().isoformat()
        }
    
    def format_cookie_string(self, cookies: Dict[str, str]) -> str:
        """
        将Cookie字典格式化为标准字符串（分号分隔）
        
        Args:
            cookies: Cookie字典
            
        Returns:
            格式化后的Cookie字符串
        """
        if not cookies:
            return ""
        return '; '.join(f"{k}={v}" for k, v in cookies.items() if k and v)
    
    def __str__(self) -> str:
        """字符串表示"""
        info = self.get_cookie_info()
        return f"CookieManager(valid={info['is_valid']}, parsed={info['parsed_count']} fields)"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        return self.__str__()


if __name__ == "__main__":
    # 测试代码
    #logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    #manager = CookieManager()
    
    print("Cookie管理器模块")
    print("支持的功能:")
    print("- Cookie文件读写")
    print("- Cookie格式验证")
    print("- Cookie有效性检查")
    print("- Cookie备份和恢复")
    print("- Cookie信息查看")
    
    # 显示当前Cookie信息
    #info = manager.get_cookie_info()
    #print(f"\n当前Cookie状态: {manager}")
    #print(f"详细信息: {info}")