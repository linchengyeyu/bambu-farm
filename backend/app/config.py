import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 默认打印机配置 (如果数据库为空，将使用此配置创建第一个打印机)
    DEFAULT_PRINTER_IP: str = "192.168.31.175"
    DEFAULT_ACCESS_CODE: str = "30131176"
    DEFAULT_SERIAL_NO: str = "0300AA5A1603936"
    
    # 微信/钉钉/飞书 Webhook 通知地址
    WEBHOOK_URL: str = ""
    
    # 应用配置
    UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
    DATA_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    STATIC_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    DB_PATH: str = os.path.join(DATA_DIR, "bbm.db")
    
    # 换盘冷却时间 (秒)
    SWAP_COOLDOWN: int = 60

    class Config:
        env_file = ".env"

settings = Settings()

# 确保目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.STATIC_DIR, exist_ok=True)
