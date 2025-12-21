import time
import threading
import logging
import requests
from concurrent.futures import ThreadPoolExecutor
from sqlmodel import Session, select
from app.database import engine
from app.models import Task, Printer
from app.mqtt_client import manager
from app.file_handler import FileHandler
from app.config import settings
from datetime import datetime

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        self.paused = False # 全局暂停开关
        # 创建线程池，最大并发数设为 5 (可根据打印机数量调整)
        self.executor = ThreadPoolExecutor(max_workers=5)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            logger.info("📅 调度器已启动")

    def stop(self):
        self.running = False
        self.executor.shutdown(wait=False)

    def _loop(self):
        while self.running:
            try:
                if not self.paused:
                    self._check_and_run()
            except Exception as e:
                logger.error(f"调度循环异常: {e}")
            
            time.sleep(2) # 2秒轮询一次

    def _check_and_run(self):
        with Session(engine) as session:
            # 获取所有打印机
            printers = session.exec(select(Printer)).all()
            
            for printer in printers:
                self._process_printer(session, printer)

    def _process_printer(self, session: Session, printer: Printer):
        """处理单个打印机的调度逻辑"""
        state = manager.get_state(printer.serial_no)
        if not state:
            return

        # 0. 同步状态：如果打印机空闲，但数据库里有该打印机的 printing 任务
        is_safe, reason = state.is_safe_to_print()
        
        if is_safe:
            # 查找该打印机正在进行的任务
            printing_tasks = session.exec(
                select(Task)
                .where(Task.status == "printing")
                .where(Task.assigned_printer_id == printer.id)
            ).all()
            
            for t in printing_tasks:
                logger.info(f"[{printer.name}] 🔄 自动修正任务状态: {t.filename} -> completed")
                t.status = "completed"
                t.completed_at = datetime.now()
                session.add(t)
                
                # 触发 Webhook 通知
                self._send_notification(f"✅ 打印完成: {t.filename} ({printer.name})")
                
            if printing_tasks:
                session.commit()

        # 1. 检查打印机状态
        if not is_safe:
            return

        # 2. 检查队列 (简单的负载均衡)
        statement = (
            select(Task)
            .where(Task.status == "pending")
            .where(
                (Task.assigned_printer_id == None) | 
                (Task.assigned_printer_id == printer.id)
            )
            .order_by(Task.priority.desc(), Task.id) # 优先处理 priority 高的，同级按 ID 顺序
            .limit(1)
        )
        task = session.exec(statement).first()
        
        if not task:
            return

        # --- 新增并发检查逻辑 ---
        # 检查是否有其他任务正在上传同一个文件
        # 如果有，则跳过当前任务，等待那个任务传完
        uploading_same_file = session.exec(
            select(Task)
            .where(Task.status == "uploading")
            .where(Task.filepath == task.filepath)
        ).first()

        if uploading_same_file:
            logger.info(f"[{printer.name}] 文件正在被任务 {uploading_same_file.id} 上传中，当前任务 {task.id} 等待...")
            return
        # ------------------------

        logger.info(f"[{printer.name}] ✨ 发现新任务: {task.filename} (ID: {task.id})")
        
        # 3. 开始处理流程
        # 3.1 锁定任务 (防止被其他打印机抢走)
        task.status = "uploading"
        task.assigned_printer_id = printer.id # 明确归属
        session.add(task)
        session.commit()
        session.refresh(task)

        # 3.2 提交到线程池异步执行 (避免阻塞主循环)
        # 传递 ID 而不是对象，防止 Session 跨线程问题
        self.executor.submit(self._execute_task_job, printer.id, task.id)

    def _execute_task_job(self, printer_id: int, task_id: int):
        """在独立线程中执行耗时的上传和指令发送"""
        # 每个线程必须创建独立的 Session
        with Session(engine) as session:
            printer = session.get(Printer, printer_id)
            task = session.get(Task, task_id)
            
            if not printer or not task:
                logger.error(f"异步任务失败: 打印机或任务不存在 (PID:{printer_id}, TID:{task_id})")
                return

            try:
                # 1. 上传文件 (FTP)
                if not FileHandler.upload_to_printer(task.filepath, task.filename, printer_ip=printer.ip, access_code=printer.access_code):
                    logger.error(f"[{printer.name}] 上传失败，任务标记为 failed")
                    task.status = "failed"
                    session.add(task)
                    session.commit()
                    self._send_notification(f"❌ 上传失败: {task.filename} ({printer.name})")
                    return

                # 2. 计算 MD5
                md5 = FileHandler.calculate_md5(task.filepath)

                # 3. 发送 MQTT 指令
                params = {
                    "timelapse": task.timelapse,
                    "bed_levelling": task.bed_levelling,
                    "flow_cali": task.flow_cali,
                    "use_ams": task.use_ams
                }
                
                # 注意：manager 是全局单例，本身是线程安全的
                if manager.publish_print_task(printer, task.filename, md5, params):
                    # 4. 更新状态
                    task.status = "printing"
                    task.completed_at = None
                    session.add(task)
                    session.commit()
                    logger.info(f"[{printer.name}] ✅ 任务 {task.id} 已下发 (异步)")
                    self._send_notification(f"🚀 开始打印: {task.filename} ({printer.name})")
                else:
                    logger.error(f"[{printer.name}] MQTT指令发送失败")
                    task.status = "failed"
                    session.add(task)
                    session.commit()
                    
            except Exception as e:
                logger.error(f"[{printer.name}] 异步执行异常: {e}")
                task.status = "failed"
                session.add(task)
                session.commit()

    def _send_notification(self, content: str):
        """发送 Webhook 通知"""
        if not settings.WEBHOOK_URL:
            return
            
        try:
            # 适配常见的 Webhook 格式 (如企业微信、钉钉、飞书、PushPlus)
            # 这里使用通用的 JSON 格式
            payload = {
                "msgtype": "text",
                "text": {"content": f"[BambuBatch] {content}"}, # 企业微信/钉钉
                "content": f"[BambuBatch] {content}", # PushPlus
            }
            requests.post(settings.WEBHOOK_URL, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

scheduler = Scheduler()
