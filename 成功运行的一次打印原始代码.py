import ssl
import json
import time
import os
import hashlib
import paho.mqtt.client as mqtt

# ================= 你的配置中心 =================
PRINTER_IP = "192.168.31.175"
ACCESS_CODE = "30131176"
SERIAL_NO = "0300AA5A1603936"

# ❗重要：这里填你 SD 卡里那个确实能用的文件名
FILENAME = "lifangti.gcode.3mf"          
# ❗重要：这是 3mf 内部的标准路径，通常不用改
INTERNAL_PATH = "Metadata/plate_1.gcode" 
# ===============================================

def calculate_md5(file_path):
    """计算文件的数字指纹，确保骗过打印机的安全检查"""
    if not os.path.exists(file_path):
        print(f"❌ 错误：脚本找不到本地文件 {file_path}")
        exit()
    print(f"🧮 正在计算 {file_path} 的指纹...")
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ MQTT 连接成功！")
        
        # 1. 算 MD5
        md5_val = calculate_md5(FILENAME)
        print(f"🔑 文件校验码: {md5_val}")
        
        print("🚀 发送启动指令...")
        
        # 2. 构建 A1 Mini 专用指令
        payload = {
            "print": {
                "sequence_id": "60001", # 每次可以随便改个数字
                "command": "project_file",
                "param": INTERNAL_PATH,
                "project_id": "0",
                "profile_id": "0",
                "task_id": "0",
                "subtask_id": "0",
                "subtask_name": "",
                "file": FILENAME,
                "url": f"file:///sdcard/{FILENAME}",
                "md5": md5_val,
                "timelapse": False,
                "bed_levelling": True,
                "flow_cali": True,
                "vibration_cali": True,
                "layer_inspect": True,
                "use_ams": False
            }
        }
        
        # 3. 发送！
        client.publish(f"device/{SERIAL_NO}/request", json.dumps(payload))
        print("📨 指令已强制发出！")
        
        print("⏳ 等待 3 秒...")
        time.sleep(3)
        print("👋 任务完成，脚本退出。")
        client.disconnect()
    else:
        print(f"❌ 连接失败 code: {rc}")

# === 主程序 ===
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set("bblp", ACCESS_CODE)
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)
client.on_connect = on_connect

print(f"⏳ 正在连接 {PRINTER_IP}...")
try:
    client.connect(PRINTER_IP, 8883, 60)
    client.loop_forever()
except KeyboardInterrupt:
    pass