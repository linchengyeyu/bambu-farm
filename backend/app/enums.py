from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"

class PrinterStatus(str, Enum):
    UNKNOWN = "unknown"
    OFFLINE = "offline"
    ONLINE = "online"
    IDLE = "idle"
    BUSY = "busy"
