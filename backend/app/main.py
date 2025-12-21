from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, SQLModel
from typing import List, Optional
from contextlib import asynccontextmanager
import shutil
import os
import uuid

from app.database import create_db_and_tables, get_session, engine
from app.models import Task, TaskCreate, TaskRead, Printer, PrinterCreate, PrinterRead
from app.config import settings
from app.mqtt_client import manager
from app.file_handler import FileHandler
from app.scheduler import scheduler
import logging

logger = logging.getLogger(__name__)

# 自定义日志过滤器：过滤掉频繁的健康检查和任务轮询日志
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        # 过滤掉 /tasks 和 /status 的成功请求 (200 OK)
        if ("GET /tasks" in message or "GET /status" in message) and " 200 " in message:
            return False
        return True

# 将过滤器添加到 uvicorn.access 日志记录器
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    
    # 初始化打印机
    with Session(engine) as session:
        printers = session.exec(select(Printer)).all()
        if not printers and settings.DEFAULT_PRINTER_IP:
            # 自动创建默认打印机
            logger.info("Initializing default printer...")
            default_printer = Printer(
                name="Default Printer",
                ip=settings.DEFAULT_PRINTER_IP,
                access_code=settings.DEFAULT_ACCESS_CODE,
                serial_no=settings.DEFAULT_SERIAL_NO
            )
            session.add(default_printer)
            session.commit()
            printers = [default_printer]
            
        for p in printers:
            manager.add_printer(p)
            
    scheduler.start()
    
    yield
    
    # Shutdown (可选: 如果需要清理资源)
    scheduler.stop()

app = FastAPI(title="Bambu Batch Manager", version="0.2.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件 (缩略图)
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")

# --- Printer APIs ---
@app.post("/printers", response_model=PrinterRead)
def create_printer(printer: PrinterCreate, session: Session = Depends(get_session)):
    db_printer = Printer.from_orm(printer)
    session.add(db_printer)
    try:
        session.commit()
        session.refresh(db_printer)
        manager.add_printer(db_printer)
        return db_printer
    except Exception as e:
        raise HTTPException(status_code=400, detail="Printer already exists (check IP/Serial)")

@app.get("/printers", response_model=List[PrinterRead])
def get_printers(session: Session = Depends(get_session)):
    printers = session.exec(select(Printer)).all()
    # 注入运行时状态
    states = manager.get_all_states()
    result = []
    for p in printers:
        p_read = PrinterRead.from_orm(p)
        st = states.get(p.serial_no)
        if st and st.get('connected'):
            p_read.status = "online"
        else:
            p_read.status = "offline"
        result.append(p_read)
    return result

@app.delete("/printers/{printer_id}")
def delete_printer(printer_id: int, session: Session = Depends(get_session)):
    printer = session.get(Printer, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail="Printer not found")
    # 注意：这里没有停止 MQTT 连接的逻辑，实际应用需要完善
    session.delete(printer)
    session.commit()
    return {"ok": True}

@app.post("/upload", response_model=List[TaskRead])
async def upload_file(
    file: UploadFile = File(...),
    bed_levelling: bool = Form(True),
    flow_cali: bool = Form(True),
    timelapse: bool = Form(False),
    use_ams: bool = Form(False),
    repeat_count: int = Form(1),
    printer_id: int = Form(None), # 可选指定打印机
    session: Session = Depends(get_session)
):
    # 1. 保存文件 (只保存一次)
    if not file.filename.endswith(".3mf"):
        raise HTTPException(status_code=400, detail="Only .3mf files supported")
    
    file_id = str(uuid.uuid4())
    save_name = f"{file_id}_{file.filename}"
    save_path = os.path.join(settings.UPLOAD_DIR, save_name)
    
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 提取元数据 (只提取一次)
    # 我们先创建一个临时 Task 对象来获取元数据，但不保存到数据库
    # 或者稍微修改一下 FileHandler，这里简单处理：先入库第一条，拿到 ID 提取图片，然后更新所有
    
    created_tasks = []
    
    # 2. 批量创建任务
    for i in range(repeat_count):
        new_task = Task(
            filename=file.filename, # 原始文件名
            filepath=save_path,
            bed_levelling=bed_levelling,
            flow_cali=flow_cali,
            timelapse=timelapse,
            use_ams=use_ams,
            assigned_printer_id=printer_id
        )
        session.add(new_task)
        # 需要 flush 才能拿到 id
        session.flush() 
        created_tasks.append(new_task)

    # 提交事务，确保 ID 生成
    session.commit()
    
    # 3. 提取元数据 (只需要做一次)
    # 使用第一条任务的 ID 来命名缩略图
    first_task = created_tasks[0]
    thumb_path, est_time = FileHandler.extract_metadata(save_path, first_task.id)
    
    # 4. 批量更新元数据
    for task in created_tasks:
        if thumb_path:
            # 注意：这里所有任务共用一张缩略图，文件名基于第一个任务 ID
            # 前端显示时没问题，但在删除任务时要注意：只有当所有引用该图片的任务都删除了，才能删图片
            # 或者简单点：每个任务都复制一份图片（浪费空间）
            # 或者优化 FileHandler.delete_local_files 逻辑
            # 这里暂时：让所有任务指向同一个路径
            task.thumbnail_path = thumb_path
        if est_time:
            task.estimated_time = est_time
        session.add(task)
        
    session.commit()
    
    # 刷新对象以返回最新状态
    for task in created_tasks:
        session.refresh(task)
    
    return created_tasks

from pydantic import BaseModel

# ... (existing code)

class TaskUpdate(SQLModel):
    priority: Optional[int] = None

@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, task_update: TaskUpdate, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_data = task_update.dict(exclude_unset=True)
    for key, value in task_data.items():
        setattr(task, key, value)
        
    session.add(task)
    session.commit()
    session.refresh(task)
    return task

@app.post("/tasks/{task_id}/retry")
def retry_task(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 只有 failed 或 completed 的任务可以重试
    # 这里允许 completed 重试相当于“再打印一次”
    task.status = TaskStatus.PENDING
    task.completed_at = None
    task.assigned_printer_id = None # 重置分配，允许重新负载均衡
    
    session.add(task)
    session.commit()
    return {"ok": True}

@app.get("/tasks", response_model=List[TaskRead])
def get_tasks(session: Session = Depends(get_session)):
    # 排序：优先按 Priority 倒序，其次按创建时间倒序
    tasks = session.exec(select(Task).order_by(Task.priority.desc(), Task.created_at.desc())).all()
    return tasks

@app.get("/status")
def get_status():
    # 返回所有打印机的状态
    # 格式: { "printers": [ {status_dict}, ... ], "scheduler": "running" }
    all_states = manager.get_all_states()
    scheduler_status = "running" if scheduler.running and not scheduler.paused else "paused"
    
    return {
        "printers": list(all_states.values()),
        "scheduler": scheduler_status
    }

@app.post("/control/pause")
def pause_queue():
    scheduler.paused = True
    return {"status": "paused"}

@app.post("/control/resume")
def resume_queue():
    scheduler.paused = False
    return {"status": "running"}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 检查是否还有其他任务引用同一个文件
    # 排除当前要删除的任务 ID
    other_references = session.exec(
        select(Task)
        .where(Task.filepath == task.filepath)
        .where(Task.id != task_id)
    ).first()
    
    if not other_references:
        # 如果没有其他引用，才真正删除物理文件
        FileHandler.delete_local_files(task.filepath, task.thumbnail_path)
    else:
        logging.info(f"Skipping file deletion for {task.filename}, referenced by other tasks.")
    
    session.delete(task)
    session.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
