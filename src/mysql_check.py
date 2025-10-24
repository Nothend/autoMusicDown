import pymysql
from pymysql.cursors import DictCursor
from typing import List, Dict, Optional
import re
import logging
from config import Config  # 导入你的Config类


class MySQLConfig:
    """MySQL配置类，从Config实例获取配置"""
    def __init__(self, config: Config):
        self.config = config  # 接收Config实例
        self.logger = logging.getLogger(__name__)  # 初始化日志
        self._validate_config()  # 验证必要配置

    def _validate_config(self) -> None:
        """验证MySQL配置是否存在必要项"""
        mysql_config = self.config.get("mysql", {})
        required_keys = ["host", "port", "user", "password", "database"]
        missing_keys = [key for key in required_keys if key not in mysql_config]
        if missing_keys:
            self.logger.error(f"MySQL配置缺少必要项: {missing_keys}")
            raise ValueError(f"MySQL配置不完整，缺少: {missing_keys}")

    @property
    def host(self) -> str:
        """获取数据库主机地址"""
        return self.config.get("mysql", {}).get("host", "")

    @property
    def port(self) -> int:
        """获取数据库端口"""
        return self.config.get("mysql", {}).get("port", 3306)

    @property
    def user(self) -> str:
        """获取数据库用户名"""
        return self.config.get("mysql", {}).get("user", "root")

    @property
    def password(self) -> str:
        """获取数据库密码"""
        return self.config.get("mysql", {}).get("password", "")

    @property
    def database(self) -> str:
        """获取数据库名称"""
        return self.config.get("mysql", {}).get("database", "music_tag")


class MySQLChecker:
    """音乐检查器，支持MySQL判断方式（依赖Config实例）"""
    def __init__(self, config: Config):
        self.config = config  # 保存Config实例
        self.logger = logging.getLogger(__name__)  # 初始化日志
        self.mysql_config: Optional[MySQLConfig] = None
        self.mysql_connection: Optional[pymysql.connections.Connection] = None  # 连接由外部控制生命周期

        # 初始化MySQL配置
        try:
            self.mysql_config = MySQLConfig(config)
            self.logger.info("MySQL配置初始化成功")
        except Exception as e:
            self.logger.error(f"MySQL配置初始化失败: {str(e)}")
            raise  # 初始化失败直接抛出，避免后续调用异常

    def open_connection(self) -> None:
        """手动打开数据库连接（外部控制）"""
        if self.mysql_connection and not self.mysql_connection._closed:
            self.logger.debug("数据库连接已存在，无需重复打开")
            return

        try:
            self._get_mysql_connection()  # 触发连接创建
            self.logger.info("数据库连接已手动打开")
        except Exception as e:
            self.logger.error(f"手动打开连接失败: {str(e)}")
            raise

    def close_connection(self) -> None:
        """手动关闭数据库连接（外部控制）"""
        if self.mysql_connection and not self.mysql_connection._closed:
            self.mysql_connection.close()
            self.logger.info("数据库连接已手动关闭")
        else:
            self.logger.debug("无活跃连接，无需关闭")

    def _split_artists(self, artists_str: str) -> List[str]:
        """分割歌手字符串（支持多种分隔符）"""
        if not artists_str:
            self.logger.warning("歌手字符串为空，无法分割")
            return []
        
        # 统一分隔符：处理全角逗号、/及前后空格
        normalized = re.sub(r'[，,]/?\s*', ',', artists_str)
        normalized = re.sub(r'\s*/\s*', ',', normalized)
        # 分割、清洗并去重
        artists = [artist.strip() for artist in normalized.split(',') if artist.strip()]
        unique_artists = list(set(artists))
        self.logger.debug(f"歌手字符串分割结果: {unique_artists}")
        return unique_artists

    def _get_mysql_connection(self) -> pymysql.connections.Connection:
        """建立并返回MySQL连接（内部使用，不直接暴露）"""
        if not self.mysql_config:
            raise ValueError("MySQL配置未初始化，无法建立连接")

        if not self.mysql_connection or self.mysql_connection._closed:
            try:
                self.mysql_connection = pymysql.connect(
                    host=self.mysql_config.host,
                    port=self.mysql_config.port,
                    user=self.mysql_config.user,
                    password=self.mysql_config.password,
                    database=self.mysql_config.database,
                    cursorclass=DictCursor,
                    charset="utf8mb4"
                )
                self.logger.info(f"成功连接到MySQL数据库: {self.mysql_config.host}:{self.mysql_config.port}")
            except pymysql.MySQLError as e:
                self.logger.error(f"MySQL连接失败: {str(e)}")
                raise ConnectionError(f"MySQL连接失败: {str(e)}")
        return self.mysql_connection

    def check_song(self, song_name: str, artists_str: str) -> bool:
        """
        检查歌曲是否存在（依赖外部已打开的连接）
        
        Args:
            song_name: 歌曲名称
            artists_str: 歌手字符串（支持多种分隔符）
            
        Returns:
            - 存在非MP3格式: True
            - 不存在/存在但为MP3: False
        """
        # 检查连接状态
        if not self.mysql_connection or self.mysql_connection._closed:
            self.logger.error("无活跃数据库连接，请先调用open_connection()")
            raise ConnectionError("数据库连接未打开或已关闭")
        
        if not song_name or not artists_str:
            self.logger.warning("歌曲名或歌手字符串为空，无法检查")
            return False
        
        # 分割歌手字符串
        artists = self._split_artists(artists_str)
        if not artists:
            self.logger.warning("分割后无有效歌手，无法检查")
            return False
        
        try:
            with self.mysql_connection.cursor() as cursor:  # 复用已打开的连接
                # 构建歌手IN条件（任意匹配）
                artist_placeholders = ", ".join(["%s"] * len(artists))
                sql = f"""
                    SELECT t.suffix 
                    FROM music_track t
                    INNER JOIN music_artist a ON t.artist_id = a.id
                    WHERE t.name = %s 
                      AND a.name IN ({artist_placeholders})
                    LIMIT 1
                """
                self.logger.debug(f"执行SQL: {sql}，参数: {[song_name] + artists}")
                
                cursor.execute(sql, [song_name] + artists)
                result = cursor.fetchone()
                
                if not result:
                    self.logger.debug(f"歌曲不存在: {song_name} - {artists_str}")
                    return False
                
                suffix = result["suffix"].lower()
                result_flag = suffix != "mp3"
                self.logger.debug(
                    f"歌曲检查结果: {song_name} - {artists_str}，格式: {suffix}，返回: {result_flag}"
                )
                return result_flag
                
        except pymysql.MySQLError as e:
            self.logger.error(f"MySQL查询失败: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"歌曲检查过程出错: {str(e)}")
            return False


# 批量检查示例（核心改进点）
if __name__ == "__main__":
    # 初始化日志
    #logging.basicConfig(level=logging.DEBUG,format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    try:
        # 加载配置
        config = Config("config.yaml")
        
        # 初始化检查器
        checker = MySQLChecker(config)
        
        # 批量检查场景：手动控制连接生命周期
        test_cases = [
            ("海阔天空", "Beyond"),
            ("北京欢迎你", "刘欢, 那英"),
            ("千里之外", "周杰伦， 费玉清 / 群星"),
            # 可添加更多歌曲...
        ]
        
        # 1. 打开连接（一次打开，多次使用）
        checker.open_connection()
        
        # 2. 批量检查（复用连接）
        print("批量检查结果：")
        for song, artists in test_cases:
            result = checker.check_song(song, artists)
            print(f"{song} - {artists}：{'存在且非MP3' if result else '不存在或为MP3'}")
        
        # 3. 全部检查完成后关闭连接
        checker.close_connection()
            
    except Exception as e:
        logging.error(f"执行失败: {str(e)}")