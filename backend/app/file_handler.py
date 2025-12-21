import os
import zipfile
import shutil
import hashlib
import logging
import ssl
import socket
from ftplib import FTP_TLS
from app.config import settings

logger = logging.getLogger(__name__)

# 自定义隐式 FTPS 类
class ImplicitFTP_TLS(FTP_TLS):
    """
    Python ftplib.FTP_TLS 默认只支持显式 FTPS (AUTH TLS)。
    拓竹打印机在 990 端口使用隐式 FTPS (连接建立即 SSL 握手)。
    我们需要继承并重写 connect 方法来支持隐式模式。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    def connect(self, host='', port=0, timeout=-999):
        if host != '':
            self.host = host
        if port > 0:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
            
        # 1. 建立普通 TCP 连接
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        
        # 2. 关键点：立即进行 SSL 握手 (隐式模式核心)
        # 忽略证书验证
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(
            self.sock, 
            server_hostname=self.host
        )
        
        # 3. 初始化文件对象 (用于后续 readline 等操作)
        self.file = self.sock.makefile('r', encoding=self.encoding)
        
        # 4. 读取服务器欢迎信息 (标准 FTP 流程)
        self.welcome = self.getresp()
        return self.welcome

class FileHandler:
    @staticmethod
    def calculate_md5(file_path: str) -> str:
        """计算文件 MD5"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def extract_metadata(file_path: str, task_id: int):
        """解压 .3mf 提取缩略图和信息"""
        thumbnail_path = None
        estimated_time = 0
        
        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                # 1. 提取缩略图
                possible_paths = ["Metadata/plate_1.png", "Metadata/plate_1_small.png"]
                for p in possible_paths:
                    if p in z.namelist():
                        source = z.open(p)
                        target_name = f"{task_id}.png"
                        target_path = os.path.join(settings.STATIC_DIR, target_name)
                        with open(target_path, "wb") as f:
                            shutil.copyfileobj(source, f)
                        thumbnail_path = f"/static/{target_name}"
                        break
                
                # 2. 尝试提取时间 (简化版，仅读取 config)
                # 实际可能需要解析 xml，这里暂时略过复杂解析
        except Exception as e:
            logger.error(f"解析 3mf 失败: {e}")
            
        return thumbnail_path, estimated_time

    @staticmethod
    def upload_to_printer(local_path: str, remote_filename: str, printer_ip: str, access_code: str, retries: int = 3) -> bool:
        """
        使用隐式 FTPS 上传文件 (带重试机制)
        """
        for attempt in range(1, retries + 1):
            # 创建 SSL 上下文：忽略证书验证
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            ftp = ImplicitFTP_TLS(context=ctx)
            
            try:
                logger.info(f"正在连接打印机 FTP {printer_ip} (Attempt {attempt}/{retries})...")
                ftp.connect(printer_ip, 990, timeout=30)
                ftp.login("bblp", access_code)
                ftp.prot_p() # 确保数据通道也加密
                
                # 检查文件是否已存在且大小一致
                local_size = os.path.getsize(local_path)
                remote_size = -1
                
                try:
                    remote_size = ftp.size(remote_filename)
                    logger.info(f"远程文件已存在，大小: {remote_size} (本地: {local_size})")
                except Exception:
                    pass
                    
                if remote_size == local_size:
                    logger.info("✅ 文件已存在且大小一致，跳过上传")
                    ftp.quit()
                    return True
                    
                # 开始上传
                logger.info(f"开始上传文件: {local_path} -> {remote_filename}")
                with open(local_path, "rb") as f:
                    ftp.storbinary(f"STOR {remote_filename}", f)
                
                logger.info("✅ 文件上传成功")
                ftp.quit()
                return True
                
            except Exception as e:
                logger.error(f"❌ FTP 上传失败 (Attempt {attempt}): {e}")
                try:
                    ftp.quit()
                except:
                    pass
                
                if attempt < retries:
                    import time
                    time.sleep(2) # 等待2秒后重试
                else:
                    return False
        return False

    @staticmethod
    def delete_local_files(filepath: str, thumbnail_path: str = None):
        """删除本地文件和缩略图"""
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"已删除文件: {filepath}")
            
            if thumbnail_path:
                filename = os.path.basename(thumbnail_path)
                abs_path = os.path.join(settings.STATIC_DIR, filename)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                    logger.info(f"已删除缩略图: {abs_path}")
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
