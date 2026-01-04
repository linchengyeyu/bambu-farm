# 拓竹(Bambu Lab) 打印农场自动化任务调度系统

## 简介
这是一个专为拓竹 3D 打印机（X1/P1 系列）设计的自动化任务管理系统。它能够将你的单台或多台打印机变成一个自动化的“打印农场”。你只需要把要打印的 3MF 文件批量上传，系统就会自动根据打印机的空闲状态进行任务分发、上传和打印。

不再需要手动一个个打开 Bambu Studio 发送任务，也不需要半夜盯着打印机看什么时候打完。

## 核心功能

*   **🚀 批量任务队列**：支持一次性上传几十个打印任务，系统自动排队。
*   **🤖 智能调度**：
    *   自动检测打印机状态（空闲/打印中/故障）。
    *   一旦打印机空闲，自动下发下一个任务。
    *   支持多台打印机负载均衡（自动分配给最先空闲的机器）。
*   **🔄 自动重试与纠错**：
    *   上传失败自动重试（防止网络波动导致任务丢失）。
    *   支持手动“插队”（提高任务优先级）。
*   **📂 文件管理**：自动解析 3MF 文件缩略图，直观管理模型。
*   **🐳 轻松部署**：基于 Docker，支持 Windows/Mac/NAS (群晖/威联通) 一键部署。

---

## 部署指南 (以威联通 NAS 为例)

### 1. 准备工作
*   确保 NAS 已安装 **Container Station**。
*   下载本项目的代码包，解压得到 `backend` 文件夹。
*   将 `backend` 文件夹上传到 NAS（推荐路径：`/share/Container/bambu/backend`）。

### 2. 获取打印机信息
你需要知道你的拓竹打印机的：
*   **IP 地址** (例如 192.168.31.175)
*   **访问码 (Access Code)** (在打印机屏幕上查看设置 -> 网络)
*   **序列号 (Serial No)** (可选，但推荐填)

### 3. 创建应用
1.  打开 **Container Station** -> **应用程序 (Applications)** -> **创建 (Create)**。
2.  应用名称填 `bambu-farm`。
3.  复制以下 YAML 代码（**修改其中的路径和配置**）：

```yaml
version: '3.8'
services:
  bambu-batch-manager:
    # ⚠️ 必须修改为你的真实代码路径
    build: /share/Container/bambu/backend
    
    container_name: bambu_manager
    restart: always
    ports:
      - "3508:8000"  # 访问端口改为 3508
    volumes:
      # ⚠️ 建议修改为真实路径，确保数据持久化
      - /share/Container/bambu/data:/app/data
      - /share/Container/bambu/uploads:/app/uploads
      - /share/Container/bambu/static:/app/static
    environment:
      - TZ=Asia/Shanghai
      - PRINTER_IP=192.168.31.175  # 你的打印机 IP
      - ACCESS_CODE=12345678       # 你的访问码
      - SERIAL_NO=0300AA5A...      # 你的序列号
      - SWAP_COOLDOWN=60           # 打印完成后冷却时间(秒)
```
4. 点击创建，等待部署完成。

### 4. 开始使用
在浏览器访问 `http://NAS_IP:3508` 即可进入管理后台。

---

## 常见问题

**Q: 支持 P1P/P1S 吗？**
A: 支持。只要是支持 MQTT 和 FTP 协议的拓竹机型理论上都支持。

**Q: 为什么上传后没有立即打印？**
A: 系统会检查打印机状态。如果打印机状态不是 `IDLE` (空闲)，任务会处于 `pending` (等待中) 状态。请确保打印机热床已清空且处于主界面。

**Q: 部署报错 "no such file or directory"？**
A: 请检查 YAML 中的 `build` 路径是否填写正确，必须是 NAS 里的绝对路径。

**Q: 打开网页显示 `{"detail":"Not Found"}`？**
A: **这是因为 Docker 挂载覆盖了容器内的文件。**
*   **原因**：当您在 Docker 配置中将 NAS 的 `static` 目录挂载到容器的 `/app/static` 时，如果 NAS 上的 `static` 目录是空的（新建的），它会覆盖容器镜像里原本存在的网页文件。
*   **解决方法**：
    1.  在您的电脑上找到项目源码中的 `backend/static` 文件夹（里面有 `index.html`）。
    2.  通过 NAS 的文件管理器（File Station），将 `index.html` 手动上传到 NAS 上对应的挂载目录（例如 `/share/Container/bambu/static`）。
    3.  刷新浏览器即可（无需重启容器）。

## 开源协议
本项目采用 [MIT License](LICENSE) 开源协议。

