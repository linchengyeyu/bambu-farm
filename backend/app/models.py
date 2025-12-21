from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime
from app.enums import TaskStatus, PrinterStatus

# --- Printer Models ---
class PrinterBase(SQLModel):
    name: str = Field(index=True)
    ip: str = Field(unique=True)
    access_code: str
    serial_no: str = Field(unique=True)
    
class Printer(PrinterBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)

class PrinterCreate(PrinterBase):
    pass

class PrinterRead(PrinterBase):
    id: int
    status: str = PrinterStatus.OFFLINE # 运行时状态，不存数据库

# --- Task Models ---
class TaskBase(SQLModel):
    filename: str
    filepath: str
    status: str = TaskStatus.PENDING # pending, printing, completed, failed
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    # 绑定特定打印机 (可选)
    assigned_printer_id: Optional[int] = Field(default=None, foreign_key="printer.id")
    
    # 优先级 (默认为0，越高越优先)
    priority: int = Field(default=0)
    
    # 打印参数覆盖
    bed_levelling: bool = True
    flow_cali: bool = True
    timelapse: bool = False
    use_ams: bool = False
    
    # 元数据
    thumbnail_path: Optional[str] = None
    estimated_time: Optional[int] = 0 # 秒

class Task(TaskBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

class TaskCreate(TaskBase):
    pass

class TaskRead(TaskBase):
    id: int
