from enum import Enum

class InstanceStatus(Enum):
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    TERMINATED = "TERMINATED"
    SUSPENDED = "SUSPENDED"
    STARTING = "STAGING"


class OperationStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"


class OperationType(Enum):
    START = "start"
    STOP = "stop"