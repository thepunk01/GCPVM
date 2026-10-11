from typing import Optional

from pydantic import BaseModel

from core.enums import InstanceStatus, OperationStatus
from core.enums import OperationType


class InstanceTimestamps(BaseModel):
    creationTimestamp: str
    deletionTimestamp: Optional[str]
    lastStartTimestamp: Optional[str]
    lastStopTimestamp: Optional[str]


class InstanceData(BaseModel):
    name: str
    status: InstanceStatus
    zone: str
    machineType: str
    timestamps: InstanceTimestamps

class OperationTimestamps(BaseModel):
    insertTime: str
    startTime: Optional[str]
    endTime: Optional[str]


class OperationData(BaseModel):
    name: str
    type: OperationType
    status: OperationStatus
    zone: str
    timestamps: OperationTimestamps