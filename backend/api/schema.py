import os
from pathlib import Path
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine
from datetime import datetime, timezone
from typing import Optional
from core.enums import OperationStatus, OperationType
from sqlalchemy.orm import relationship

class ParentJob(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    zone: str = Field(index=True)
    status: OperationStatus = Field(index=True)
    type: OperationType = Field(index=True)
    is_successful: bool = Field(default=False, index=True)
    project_id: int | None = Field(default=None, foreign_key="projectconfig.id", index=True)

    children: list["ChildJob"] = Relationship(back_populates="parent",
    sa_relationship=relationship("ChildJob", back_populates="parent"))
    
class ParentJobPublic(ParentJob):
    model_config = {"table": False}
    children: list["ChildJob"] = []
    
class ChildJob(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    is_successful: bool = Field(default=False, index=True)
    request_time: Optional[datetime] = None  
    start_time: Optional[datetime] = None 
    end_time: Optional[datetime] = None  

    parent_id: int | None = Field(default=None, foreign_key="parentjob.id")
    parent: ParentJob | None = Relationship(back_populates="children",
    sa_relationship=relationship("ParentJob", back_populates="children"))


class ProjectConfig(SQLModel, table=True):
    """A stored GCP project connection.

    Credentials stay in a root-readable JSON file; only its path and safe
    project metadata are persisted in SQLite.
    """
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    project_id: str = Field(index=True)
    credential_path: str
    service_account_email: Optional[str] = None
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IpBlacklist(SQLModel, table=True):
    """An operator-managed list of addresses that should not be reused."""
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projectconfig.id", index=True)
    ip_address: str = Field(index=True)
    note: Optional[str] = None
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


data_dir = Path(os.getenv("GCP_PANEL_DATA_DIR", "data"))
data_dir.mkdir(parents=True, exist_ok=True)
sqlite_file_name = os.getenv("GCP_PANEL_DATABASE", str(data_dir / "database.db"))
sqlite_url = sqlite_file_name if sqlite_file_name.startswith("sqlite:") else f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
