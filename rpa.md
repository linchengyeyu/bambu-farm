
### 第二部分：Bambu Batch Manager (BBM) 产品需求文档 (PRD) v2.0

这份文档融合了你的原始需求、自动换盘的特殊逻辑、Docker 部署架构以及之前的技术积累。

#### 1. 项目概述 (Project Overview)

* **项目名称**：Bambu Batch Manager (BBM)
* **项目背景**：解决拓竹 A 系列打印机在进行批量生产（自动换盘）时，无法队列管理、需重复切片、人工干预频繁的痛点。
* **核心价值**：实现“切片一次，无限排队；无人值守，连续生产”。
* **适用设备**：拓竹 A1 / A1 Mini（及其他支持自动换盘改装的机型）。

#### 2. 系统架构 (System Architecture)

为了满足“通用性”和“部署便利性”，采用经典的 B/S 架构 + 容器化部署。

* **部署方式**：Docker Compose（一键部署，支持 Windows/Mac/Linux/NAS/树莓派）。
* **后端 (Backend)**：
* **语言**：Python (推荐 FastAPI 或 Flask，轻量且适合处理文件和 MQTT)。
* **核心模块**：
* `MQTT Watchdog`：守护进程，负责与打印机保持长连接，实时维护打印机状态机。
* `Task Scheduler`：任务调度器，管理队列逻辑。
* `3MF Parser`：文件解析器，负责解压 .3mf 提取图片和元数据。




* **前端 (Frontend)**：
* **技术栈**：Vue.js 3 + Element Plus (或 Tailwind CSS)。
* **形式**：响应式 Web 页面，适配 PC 和移动端浏览器。


* **数据库 (Database)**：
* **SQLite**：默认使用，文件型数据库，无需额外配置，数据随 Docker 卷挂载保存。



#### 3. 用户流程 (User Flow)

1. **上传**：用户在 Web 界面上传切片好的 `.gcode.3mf` 文件。
2. **解析**：后端自动提取缩略图、预估时间，并存入“文件库”。
3. **排队**：用户将文件库中的文件添加到“打印队列”，可设置数量、拖拽排序。
4. **参数**：针对队列中的每个任务，用户可微调参数（如覆盖默认的“开启/关闭调平”设置）。
5. **生产**：
* 系统检测打印机 `IDLE`（空闲）。
* 系统发送任务 A -> 打印机工作。
* 任务 A 完成 -> 打印机执行 G-code 结尾的推盘动作（物理换盘）。
* 系统监测到 `FINISH` 状态并经过“安全冷却时间”。
* 系统自动发送任务 B。



#### 4. 功能详细说明 (Functional Requirements)

##### 4.1 任务管理看板 (Task Dashboard)

* **打印队列 (Active Queue)**：
* 显示：缩略图、文件名、耗时、状态（等待中/打印中/已完成）。
* 交互：支持**拖拽排序**（改变优先级）、删除任务、一键清空。
* **总时间计算**：实时计算队列中剩余任务的总耗时（例如：`∑(任务时长)`），并显示预计完成的具体时间点（如：“预计明日 04:20 完成”）。


* **打印控制**：
* **全局开关**：开始/暂停队列（暂停后，当前打印的任务会打完，但不会开始下一个）。
* **参数覆盖**：每个任务卡片上提供 Switch 开关：
* `热床调平` (默认: On)
* `流量校准` (默认: On)
* `延时摄影` (默认: Off)





##### 4.2 文件上传与解析 (File Management)

* **后端解析优化**：
* 用户上传文件后，**后端 Python** 立即利用 `zipfile` 库读取 `.3mf`。
* **提取图片**：解压 `Metadata/plate_1.png`，保存为静态资源，供前端调用。
* **提取时间**：读取 `Metadata/slice_info.config` 或头部注释，提取 `total estimated time`，用于计算总工时。
* **提取 Gcode 路径**：自动识别内部 Gcode 路径（防止路径错误导致无法打印）。


* **文件存储**：文件存储在 Docker 映射的 `/app/data/files` 目录，确保重启不丢失。

##### 4.3 打印机状态监控 (Status Monitor)

* **实时状态**：
* 显示打印机当前状态：空闲、准备中、打印中、暂停、出错。
* 显示实时进度百分比、剩余时间、喷头/热床温度。


* **异常处理**：
* **断连重连**：MQTT 断开后自动重连。
* **错误报警**：如果打印机上报 `print_error`（如卡料、撞头），系统自动**暂停队列**，并在 Web 端弹窗报警。



#### 5. 技术实现细节与安全逻辑 (Technical Specifications)

##### 5.1 解决“强制打印”的安全逻辑 (Safe-Print Protocol)

后端必须实现一个状态机，严禁使用“盲发”指令。

* **步骤 1：主动查询**
* 服务启动时，发送 `{"pushing": {"sequence_id": "0", "command": "pushall"}}`。


* **步骤 2：状态判定 (Status Gatekeeper)**
* 定义允许开始打印的状态码集合：`ALLOW_START = [1]` (1 代表 IDLE)。
* 定义上一盘结束的判定：当状态从 `RUNNING` 变为 `FINISH` (100) 或 `IDLE` (1)。


* **步骤 3：换盘安全期 (Swap Buffer)**
* 由于推盘动作是物理 G-code 执行的，MQTT 可能在推盘还没结束时就报了 `FINISH`。
* **强制冷却**：在检测到上一个任务完成后，程序强制倒计时（例如 60秒 或 120秒，用户可配置），等待物理推盘动作彻底完成后，才下发下一个任务。



##### 5.2 缩略图提取代码示例 (Backend Python)

```python
import zipfile
import shutil

def extract_thumbnail(upload_path, task_id):
    # 目标：从 .3mf 里把 plate_1.png 挖出来
    with zipfile.ZipFile(upload_path, 'r') as z:
        # 常见路径，如果找不到可以遍历查找 .png
        possible_paths = ["Metadata/plate_1.png", "Metadata/plate_1_small.png"]
        for p in possible_paths:
            if p in z.namelist():
                source = z.open(p)
                target_path = f"./static/thumbnails/{task_id}.png"
                with open(target_path, "wb") as f:
                    shutil.copyfileobj(source, f)
                return target_path
    return None # 没图

```

##### 5.3 Docker 部署配置 (docker-compose.yml)

```yaml
version: '3.8'
services:
  bambu-batch-manager:
    image: bbm-app:latest
    container_name: bambu_manager
    restart: always
    ports:
      - "8080:80"  # 网页访问端口
    volumes:
      - ./data:/app/data  # 挂载数据目录(存文件和数据库)
      - ./config.yaml:/app/config.yaml # 配置文件(打印机IP/SN)
    environment:
      - TZ=Asia/Shanghai

```

#### 6. 开发路线图 (Roadmap)

1. **阶段一 (MVP)**：
* 实现后端 MQTT 连接保活 + 主动状态查询 (`pushall`)。
* 实现 `curl` 上传 + 打印指令的 Python 封装。
* 简单的 API：`POST /task` (添加任务), `GET /status` (看状态)。


2. **阶段二 (Web UI)**：
* 搭建 Vue 前端，实现任务列表和拖拽。
* 对接后端 API，显示实时进度。


3. **阶段三 (优化)**：
* 加入缩略图解析。
* 加入“换盘安全冷却时间”配置。
* Docker 镜像打包发布。



---

action：
主题：关于拓竹打印机 MQTT 通信协议的生产环境规范

背景： 在之前的 POC (概念验证) 阶段，我们使用了“强制发送 (Force Print)”的方式来驱动打印机。虽然测试通过，但在 -1 (Unknown) 状态下盲发指令存在极高的安全隐患。为了构建稳定可靠的 Bambu Batch Manager，我们需要从“单向指令”升级为“双向状态机”。

核心问题：为什么不能用“强制打印”？

状态盲区：拓竹 MQTT 协议默认为“事件驱动”。客户端连上后，如果不主动询问，打印机不会推送当前状态（导致我们看到的 g_st 一直是 -1）。

并发冲突风险：如果上一盘刚打完，机器正在执行 G-code 结尾的“推盘动作”（物理运动中），此时若强制下发新任务，可能导致：

指令被丢弃（静默失败）。

步进电机丢步或逻辑混乱（严重时撞头）。

用户体验缺失：前端界面无法显示“打印中”、“剩余时间”或“出错”，用户看到的永远是“等待中”，不符合商业软件标准。

解决方案：基于 pushall 的状态机守护进程 我们需要实现一个 MQTT Daemon，逻辑如下：

Connect：连接 MQTT Broker (TLS/SSL)。

Active Query (关键)：连接成功毫秒内，发送 {"pushing": {"command": "pushall"}} 指令。这会强制打印机立即推送包含 g_st (全局状态)、温度、进度的完整 JSON 包。

State Gatekeeper (状态守门员)：

维护一个内存变量 printer_status。

仅当 g_st == 1 (IDLE) 且 stage_id == 0 时，才允许从队列中 Pop 出下一个任务并执行。

任何其他状态下，拒绝执行打印指令，防止事故。
这份代码展示了如何主动获取状态并建立安全围栏。请让工程师基于此代码构建后端服务。
import ssl
import json
import time
import threading
import paho.mqtt.client as mqtt

# === 基础配置 ===
PRINTER_IP = "192.168.31.175"
ACCESS_CODE = "30131176"
SERIAL_NO = "0300AA5A1603936"

# === 全局状态存储 (内存数据库) ===
class PrinterState:
    def __init__(self):
        self.g_st = -1          # 全局状态码 (-1:未知, 1:空闲, 6:打印中...)
        self.print_type = ""    # 当前任务类型
        self.print_error = 0    # 错误码
        self.progress = 0       # 进度
        self.lock = threading.Lock()

    def update(self, payload):
        with self.lock:
            # 提取关键状态
            if 'g_st' in payload: self.g_st = int(payload['g_st'])
            if 'print_error' in payload: self.print_error = int(payload['print_error'])
            if 'mc_percent' in payload: self.progress = int(payload['mc_percent'])
            
            # 翻译状态 (仅作日志调试用)
            status_text = self.get_status_text()
            print(f"🔄 状态更新: [{status_text}] (g_st: {self.g_st}) | 进度: {self.progress}%")

    def is_safe_to_print(self):
        """核心安全检查：只有在完全空闲且无报错时才返回 True"""
        with self.lock:
            # g_st = 1 代表 IDLE (空闲)
            # print_error = 0 代表无故障
            if self.g_st == 1 and self.print_error == 0:
                return True
            return False

    def get_status_text(self):
        # 拓竹常见状态码映射
        mapping = {
            -1: "连接中/未知", 0: "离线", 1: "空闲 (Ready)", 
            2: "准备中", 3: "打印中", 4: "暂停", 
            5: "完成", 6: "打印中", 100: "已完成(等待清理)"
        }
        return mapping.get(self.g_st, f"未知({self.g_st})")

# 实例化状态对象
state = PrinterState()

# === MQTT 回调函数 ===

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ MQTT 连接成功")
        # 1. 订阅报告频道
        client.subscribe(f"device/{SERIAL_NO}/report")
        
        # 2. 【关键步骤】主动发送 pushall 指令
        # 这就是解决 "-1" 问题的核心，强迫打印机把所有数据吐出来
        print("⚡ 发送状态全量查询 (pushall)...")
        push_cmd = {
            "pushing": {
                "sequence_id": "1",
                "command": "pushall"
            }
        }
        client.publish(f"device/{SERIAL_NO}/request", json.dumps(push_cmd))
    else:
        print(f"❌ 连接失败 code: {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        
        # 只处理 print 相关的报告
        if 'print' in payload:
            state.update(payload['print'])
            
    except Exception as e:
        print(f"解析错误: {e}")

# === 模拟业务逻辑：尝试发起打印 ===
def try_start_job(client, filename):
    print(f"\n📋 尝试申请打印任务: {filename}...")
    
    # 1. 安全检查 (Gatekeeper)
    if not state.is_safe_to_print():
        print(f"⛔ 拒绝执行：打印机当前不为空闲！状态: {state.get_status_text()} (代码: {state.g_st})")
        return False
    
    # 2. 如果检查通过，执行打印逻辑
    print("✅ 安全检查通过，允许打印！")
    
    # (这里插入之前的 curl 上传逻辑)
    # simulate_upload() 
    
    # (这里插入之前的 start_print 发送逻辑)
    print("🚀 发送 MQTT 打印指令...")
    # ... client.publish(...) ...
    
    return True

# === 主程序 ===
if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set("bblp", ACCESS_CODE)
    
    # SSL 配置
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    
    client.on_connect = on_connect
    client.on_message = on_message

    # 启动后台线程处理网络
    client.connect(PRINTER_IP, 8883, 60)
    client.loop_start() 

    # 模拟主程序的调度循环
    try:
        while True:
            # 假设这是 Web 端点击了“开始”
            user_input = input("\n按回车键尝试发起打印 (输入 'q' 退出): ")
            if user_input == 'q': break
            
            # 尝试执行
            if try_start_job(client, "test_job.3mf"):
                print(">>> 任务已下发")
            else:
                print(">>> 请等待打印机空闲后再试")
                
            time.sleep(1)
            
    except KeyboardInterrupt:
        pass
    
    client.loop_stop()
    print("程序退出")


    工程师需要注意的关键点 (Key Takeaways)
pushall 是必须的：代码第 63-69 行。连接成功后必须发这个，否则程序启动后的几分钟内，状态都会是“死”的。

state.is_safe_to_print() 是安全阀：所有的打印请求（无论是自动队列还是手动点击），必须经过这个函数的 return True 才能执行。

状态码 100 (FINISH)：注意，当打印机刚打完时，状态码通常是 100（FINISH）。此时虽然打完了，但不能立即开始下一个。

业务逻辑补充：在监测到从 6 (RUNNING) 变到 100 (FINISH) 后，你的代码应该启动一个 “换盘冷却计时器”（比如 1 分钟）。

只有当计时器结束 并且 状态变回 1 (IDLE) 时，才触发下一个任务。