import yaml
import logging
from typing import Dict, Any, Optional

class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.load_config()
        
        
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
            logging.info(f"配置文件加载成功: {self.config_path}")
        except FileNotFoundError:
            logging.error(f"配置文件未找到: {self.config_path}")
            raise
        except Exception as e:
            logging.error(f"配置文件加载失败: {str(e)}")
            raise
    
    def is_enabled(self, type: str) -> bool:
        """
        检查指定类型的配置是否启用（支持参数大小写混用）
        :param type: 配置类型，支持'NAVIDROME'或'MYSQL'（大小写不限）
        :return: 配置是否有效启用，符合条件返回True，否则返回False
        """
        # 将参数转换为全大写，统一判断标准
        type_upper = type.upper()
        
        # 处理NAVIDROME类型检查
        if type_upper == 'NAVIDROME':
            # 检查是否存在NAVIDROME节点（配置中是大写节点）
            nav_node = self.config.get('NAVIDROME')
            if not nav_node:
                return False
            # 检查USE_NAVIDROME是否存在且为True
            return nav_node.get('USE_NAVIDROME', False) is True
        
        # 处理MYSQL类型检查（配置中是小写mysql节点）
        elif type_upper == 'MYSQL':
            # 检查是否存在mysql节点
            mysql_node = self.config.get('mysql')
            if not mysql_node:
                return False
            # 检查USE_MYSQL是否存在且为True
            return mysql_node.get('USE_MYSQL', False) is True
        
        # 其他类型返回False
        else:
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取一级配置项（兼容原有逻辑）"""
        return self.config.get(key, default)
    
    def get_nested(self, path: str, default: Optional[Any] = None) -> Any:
        """
        获取层级配置项（支持类似 'NAVIDROME.NAVIDROME_HOST' 的路径）
        :param path: 层级路径，用 '.' 分隔（如 'mysql.host'）
        :param default: 路径不存在时的默认返回值
        :return: 配置项的值，或默认值
        """
        keys = path.split('.')  # 分割路径为键列表（如 ['NAVIDROME', 'NAVIDROME_HOST']）
        current = self.config   # 从根配置开始逐层查找
        
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]  # 进入下一层级
            else:
                return default  # 任何一层不存在，返回默认值
        
        return current  # 找到最终值
    
    
    def __getitem__(self, key: str) -> Any:
        """通过索引获取配置项"""
        return self.config[key]
    
    def __contains__(self, key: str) -> bool:
        """检查配置项是否存在"""
        return key in self.config