import os
from pathlib import Path
import yaml
import logging
from typing import Dict, Any, Optional

class Config:
    # 功能开关表：对外名称 -> (YAML 节点名, 启用标志键)
    _FEATURE_TOGGLES = {
        'NAVIDROME': ('NAVIDROME', 'USE_NAVIDROME'),
        'MUSIC-TAG-WEB': ('music-tag-web', 'USE_MYSQL'),
    }

    def __init__(self, config_path: str | None = None):
        if config_path:
            self.config_path = Path(config_path)
        elif os.getenv("CONFIG_PATH"):
            self.config_path = Path(os.getenv("CONFIG_PATH"))
        else:
            # __file__ 在 src/config.py，这里取上一级作为项目根
            self.config_path = Path(__file__).resolve().parent.parent / "config.yaml"

        # 备用：如果上面的路径不存在，再尝试 cwd 下同名文件
        if not self.config_path.exists():
            alt = Path.cwd() / self.config_path.name
            if alt.exists():
                self.config_path = alt

        logging.info(f"使用配置文件: {self.config_path} (cwd={Path.cwd()})")
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
        检查指定类型的功能是否启用（参数大小写不限）
        :param type: 功能名，见 _FEATURE_TOGGLES（如 'NAVIDROME'、'MUSIC-TAG-WEB'）
        :return: 对应节点存在且启用标志为 True 时返回 True，否则 False
        """
        node_name, flag_key = self._FEATURE_TOGGLES.get(type.upper(), (None, None))
        if not node_name:
            return False
        node = self.config.get(node_name)
        return bool(node) and node.get(flag_key, False) is True
    
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