import ssl
import json
import time
import threading
import logging
import paho.mqtt.client as mqtt
from typing import Dict, Optional
from app.config import settings
from app.models import Printer

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PrinterState:
    def __init__(self, serial_no: str):
        self.serial_no = serial_no
        self.g_st = -1          # 全局状态码 (-1:未知, 1:空闲, 6:打印中...)
        self.print_error = 0    # 错误码
        self.progress = 0       # 进度
        self.nozzle_temp = 0    # 喷头温度
        self.bed_temp = 0       # 热床温度
        self.lock = threading.Lock()
        self.last_finish_time = 0 # 上次完成时间戳
        self.is_cooling_down = False # 是否处于换盘冷却期
        self.connected = False # MQTT连接状态

    def update(self, payload):
        with self.lock:
            old_gst = self.g_st
            old_progress = self.progress
            
            if 'g_st' in payload: self.g_st = int(payload['g_st'])
            if 'print_error' in payload: self.print_error = int(payload['print_error'])
            if 'mc_percent' in payload: self.progress = int(payload['mc_percent'])
            if 'nozzle_temper' in payload: self.nozzle_temp = float(payload['nozzle_temper'])
            if 'bed_temper' in payload: self.bed_temp = float(payload['bed_temper'])
            
            # 判断逻辑变更：兼容 -1 状态
            # 1. 传统 g_st 判定: 6 -> 100/1
            gst_finished = (old_gst == 6 and (self.g_st == 100 or self.g_st == 1))
            
            # 2. 进度判定: 之前没满，现在满了
            progress_finished = (old_progress < 100 and self.progress == 100)
            
            if gst_finished or progress_finished:
                logger.info(f"[{self.serial_no}] 🎉 判定打印完成 (g_st: {old_gst}->{self.g_st}, progress: {old_progress}->{self.progress})，进入冷却期...")
                self.last_finish_time = time.time()
                self.is_cooling_down = True
                
            # 日志优化：只在关键字段变化时返回 True，告知上层打印日志
            has_changed = (self.g_st != old_gst) or (self.progress != old_progress)
            return has_changed

    def check_cooldown(self):
        """检查冷却是否结束"""
        with self.lock:
            if self.is_cooling_down:
                elapsed = time.time() - self.last_finish_time
                if elapsed >= settings.SWAP_COOLDOWN:
                    self.is_cooling_down = False
                    logger.info(f"[{self.serial_no}] ❄️ 冷却期结束，准备就绪")
                else:
                    return False # 还在冷却
            return True

    def is_safe_to_print(self):
        """核心安全检查"""
        if not self.check_cooldown():
            return False, "Cooling down"

        with self.lock:
            # 宽松判定：
            # 1. g_st == 1 (标准空闲)
            # 2. g_st == -1 且 error=0 且 (progress=100 或 progress=0)
            # 注意：如果 progress=100 且冷却已过，我们认为上一张已推走
            is_idle = (self.g_st == 1)
            is_unknown_but_likely_idle = (
                self.g_st == -1 and 
                self.print_error == 0 and 
                (self.progress == 100 or self.progress == 0)
            )
            
            if is_idle or is_unknown_but_likely_idle:
                return True, "Ready"
            
            return False, f"Busy/Error (g_st={self.g_st}, err={self.print_error}, prog={self.progress})"

    def get_status_dict(self):
        with self.lock:
            return {
                "serial_no": self.serial_no,
                "g_st": self.g_st,
                "error": self.print_error,
                "progress": self.progress,
                "nozzle_temp": self.nozzle_temp,
                "bed_temp": self.bed_temp,
                "is_cooling": self.is_cooling_down,
                "connected": self.connected
            }

class PrinterManager:
    def __init__(self):
        self.clients: Dict[str, mqtt.Client] = {}
        self.states: Dict[str, PrinterState] = {}
        self.lock = threading.Lock()

    def get_state(self, serial_no: str) -> Optional[PrinterState]:
        return self.states.get(serial_no)

    def get_all_states(self) -> Dict[str, dict]:
        return {sn: state.get_status_dict() for sn, state in self.states.items()}

    def add_printer(self, printer: Printer):
        with self.lock:
            if printer.serial_no in self.clients:
                logger.warning(f"Printer {printer.serial_no} already managed, skipping add.")
                return

            logger.info(f"Adding printer manager for {printer.name} ({printer.ip})...")
            
            # 初始化状态
            self.states[printer.serial_no] = PrinterState(printer.serial_no)
            
            # 初始化 MQTT 客户端
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.username_pw_set("bblp", printer.access_code)
            client.tls_set(cert_reqs=ssl.CERT_NONE)
            client.tls_insecure_set(True)
            
            # 绑定回调 (闭包捕获 serial_no)
            client.on_connect = self._create_on_connect(printer.serial_no)
            client.on_message = self._create_on_message(printer.serial_no)
            client.on_disconnect = self._create_on_disconnect(printer.serial_no)
            
            try:
                client.connect(printer.ip, 8883, 60)
                client.loop_start()
                self.clients[printer.serial_no] = client
            except Exception as e:
                logger.error(f"Failed to connect to printer {printer.serial_no}: {e}")

    def _create_on_connect(self, serial_no: str):
        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                logger.info(f"[{serial_no}] ✅ MQTT 连接成功")
                if serial_no in self.states:
                    self.states[serial_no].connected = True
                
                client.subscribe(f"device/{serial_no}/report")
                
                # 发送状态全量查询
                push_cmd = {"pushing": {"sequence_id": "1", "command": "pushall"}}
                client.publish(f"device/{serial_no}/request", json.dumps(push_cmd))
            else:
                logger.error(f"[{serial_no}] ❌ MQTT 连接失败 code: {rc}")
        return on_connect

    def _create_on_disconnect(self, serial_no: str):
        def on_disconnect(client, userdata, flags, rc, properties=None):
            logger.warning(f"[{serial_no}] 🔌 MQTT 断开连接")
            if serial_no in self.states:
                self.states[serial_no].connected = False
        return on_disconnect

    def _create_on_message(self, serial_no: str):
        def on_message(client, userdata, msg):
            try:
                payload_str = msg.payload.decode()
                payload = json.loads(payload_str)
                state = self.states.get(serial_no)
                
                if state and 'print' in payload:
                    has_changed = state.update(payload['print'])
                    if has_changed:
                        status = state.get_status_dict()
                        logger.info(f"[{serial_no}] 🔄 状态: {status['g_st']} | {status['progress']}%")
            except Exception as e:
                logger.error(f"[{serial_no}] 解析错误: {e}")
        return on_message

    def publish_print_task(self, printer: Printer, filename: str, md5: str, params: dict):
        client = self.clients.get(printer.serial_no)
        if not client:
            logger.error(f"Cannot publish task: Printer {printer.serial_no} not connected")
            return False

        payload = {
            "print": {
                "sequence_id": str(int(time.time())), 
                "command": "project_file",
                "param": "Metadata/plate_1.gcode", 
                "project_id": "0",
                "profile_id": "0",
                "task_id": "0",
                "subtask_id": "0",
                "subtask_name": "",
                "file": filename,
                "url": f"file:///sdcard/{filename}",
                "md5": md5,
                "timelapse": params.get('timelapse', False),
                "bed_levelling": params.get('bed_levelling', True),
                "flow_cali": params.get('flow_cali', True),
                "vibration_cali": True,
                "layer_inspect": True,
                "use_ams": params.get('use_ams', False)
            }
        }
        client.publish(f"device/{printer.serial_no}/request", json.dumps(payload))
        logger.info(f"[{printer.serial_no}] 🚀 打印指令已发送: {filename}")
        return True

# 全局单例
manager = PrinterManager()
