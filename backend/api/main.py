import logging
import ipaddress
from fastapi import FastAPI, BackgroundTasks, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from api.utils import check_operation_status
from core.enums import OperationType
from core.gcloud import GCloud
from api.schema import (create_db_and_tables, ParentJob, ParentJobPublic, ProjectConfig,
                        IpBlacklist, get_session)
from core.project_manager import (client_for, invalidate, remove_credentials,
                                   store_credentials, validate_credentials)
import uuid

class RequestBody(BaseModel):
    zone: str
    instance_name: str
    receiver: str
    project_id: int | None = None


class ProjectPublic(BaseModel):
    id: int
    name: str
    project_id: str
    service_account_email: str | None = None
    enabled: bool
    created_at: str


class IpBlacklistCreate(BaseModel):
    project_id: int
    ip_address: str
    note: str = ""


class IpBlacklistPublic(BaseModel):
    id: int
    project_id: int
    ip_address: str
    note: str | None = None
    enabled: bool
    created_at: str


class RotateIpRequest(BaseModel):
    project_id: int | None = None
    network_interface: str = "nic0"
    blacklist_current: bool = True

app = FastAPI()

logging.basicConfig(filename="app.log",level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.get("/hello")
def Hello():
    return {"status": "success", "message": "Hello World"}

gcloud = None  # Kept for compatibility with the original /load_config endpoint.
default_project_id: int | None = None


def project_or_404(project_id: int | None, session: Session) -> ProjectConfig:
    selected_id = project_id or default_project_id
    project = session.get(ProjectConfig, selected_id) if selected_id is not None else None
    if project is None and selected_id is None:
        project = session.exec(select(ProjectConfig).order_by(ProjectConfig.id)).first()
    if not project or not project.enabled:
        raise HTTPException(400 if selected_id is None else 404,
                            "请先添加一个 GCP 项目和服务账号" if selected_id is None else "GCP 项目不存在或已停用")
    return project


def project_public(project: ProjectConfig) -> ProjectPublic:
    return ProjectPublic(id=project.id, name=project.name, project_id=project.project_id,
                         service_account_email=project.service_account_email,
                         enabled=project.enabled, created_at=project.created_at.isoformat())


def create_project_record(name: str, raw: bytes, session: Session) -> ProjectConfig:
    metadata = validate_credentials(raw)
    clean_name = name.strip() or metadata["project_id"]
    if len(clean_name) > 80:
        raise HTTPException(400, "项目名称不能超过 80 个字符")
    existing = session.exec(select(ProjectConfig).where(ProjectConfig.name == clean_name)).first()
    if existing:
        raise HTTPException(409, "项目名称已存在")
    key = uuid.uuid4().hex
    path = store_credentials(key, raw)
    project = ProjectConfig(name=clean_name, project_id=metadata["project_id"],
                            credential_path=str(path), service_account_email=metadata["client_email"])
    session.add(project)
    try:
        session.commit()
        session.refresh(project)
        # Instantiate once during setup to catch malformed credentials early.
        client_for(project)
    except Exception:
        session.rollback()
        remove_credentials(path)
        raise
    return project


@app.get("/projects", response_model=list[ProjectPublic])
def list_projects(session: Session = Depends(get_session)):
    return [project_public(item) for item in session.exec(select(ProjectConfig).order_by(ProjectConfig.id)).all()]


@app.post("/projects", response_model=ProjectPublic)
async def add_project(name: str = Form(""), file: UploadFile = File(...), session: Session = Depends(get_session)):
    raw = await file.read()
    try:
        project = create_project_record(name, raw, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    global default_project_id, gcloud
    default_project_id = project.id
    gcloud = client_for(project)
    return project_public(project)


@app.post("/projects/{project_id}/test")
def test_project(project_id: int, session: Session = Depends(get_session)):
    project = project_or_404(project_id, session)
    try:
        instances = client_for(project).list_all_instances()
        count = sum(len(items) for items in instances.values())
    except Exception as exc:
        raise HTTPException(502, f"GCP API 连接失败：{exc}") from exc
    return {"ok": True, "project": project_public(project), "instance_count": count}


@app.delete("/projects/{project_id}")
def delete_project(project_id: int, session: Session = Depends(get_session)):
    global default_project_id, gcloud
    project = project_or_404(project_id, session)
    if session.exec(select(ParentJob).where(ParentJob.project_id == project_id)).first():
        raise HTTPException(409, "该项目仍有关联操作记录，暂时不能删除")
    path = project.credential_path
    invalidate(project_id)
    for record in session.exec(select(IpBlacklist).where(IpBlacklist.project_id == project_id)).all():
        session.delete(record)
    session.delete(project)
    session.commit()
    remove_credentials(path)
    if default_project_id == project_id:
        default_project_id = None
        gcloud = None
    return {"ok": True}


@app.get("/ip-addresses")
def list_ip_addresses(project_id: int | None = None, session: Session = Depends(get_session)):
    project = project_or_404(project_id, session)
    try:
        return client_for(project).list_external_addresses()
    except Exception as exc:
        raise HTTPException(502, f"GCP 地址读取失败：{exc}") from exc


@app.get("/instances/{zone}/{instance_name}/network")
def instance_network(zone: str, instance_name: str, project_id: int | None = None,
                     session: Session = Depends(get_session)):
    project = project_or_404(project_id, session)
    try:
        return client_for(project).list_instance_networks(zone, instance_name)
    except Exception as exc:
        raise HTTPException(502, f"实例网络读取失败：{exc}") from exc


@app.post("/instances/{zone}/{instance_name}/rotate-ip")
def rotate_instance_ip(zone: str, instance_name: str, body: RotateIpRequest,
                       session: Session = Depends(get_session)):
    project = project_or_404(body.project_id, session)
    client = client_for(project)
    try:
        networks = client.list_instance_networks(zone, instance_name)
        selected = next((item for item in networks
                         if item["network_interface"] == body.network_interface), None)
        if selected is None:
            raise HTTPException(404, "找不到指定网卡")
        if body.blacklist_current and selected.get("external_ip"):
            add_ip_blacklist_record(session, project.id, selected["external_ip"], "自动换 IP 前保留")
        result = client.rotate_instance_external_ip(zone, instance_name, body.network_interface)
        return {"ok": True, "project_id": project.id, "instance_name": instance_name, **result}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"公网 IP 更换失败：{exc}") from exc


def add_ip_blacklist_record(session: Session, project_id: int, ip_address: str, note: str = "") -> IpBlacklist:
    existing = session.exec(select(IpBlacklist).where(
        (IpBlacklist.project_id == project_id) & (IpBlacklist.ip_address == ip_address)
    )).first()
    if existing:
        if note and not existing.note:
            existing.note = note
        existing.enabled = True
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    record = IpBlacklist(project_id=project_id, ip_address=ip_address, note=note or None)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def ip_blacklist_public(record: IpBlacklist) -> IpBlacklistPublic:
    return IpBlacklistPublic(id=record.id, project_id=record.project_id,
                             ip_address=record.ip_address, note=record.note,
                             enabled=record.enabled, created_at=record.created_at.isoformat())


@app.get("/ip-blacklist", response_model=list[IpBlacklistPublic])
def list_ip_blacklist(project_id: int | None = None, session: Session = Depends(get_session)):
    project = project_or_404(project_id, session)
    records = session.exec(select(IpBlacklist).where(IpBlacklist.project_id == project.id)
                           .order_by(IpBlacklist.id)).all()
    return [ip_blacklist_public(record) for record in records]


@app.post("/ip-blacklist", response_model=IpBlacklistPublic)
def create_ip_blacklist(body: IpBlacklistCreate, session: Session = Depends(get_session)):
    project_or_404(body.project_id, session)
    try:
        ipaddress.ip_address(body.ip_address)
    except ValueError as exc:
        raise HTTPException(400, "IP 地址格式不正确") from exc
    return ip_blacklist_public(add_ip_blacklist_record(session, body.project_id,
                                                       body.ip_address, body.note.strip()))


@app.delete("/ip-blacklist/{record_id}")
def delete_ip_blacklist(record_id: int, project_id: int | None = None,
                        session: Session = Depends(get_session)):
    record = session.get(IpBlacklist, record_id)
    if record is None or (project_id is not None and record.project_id != project_id):
        raise HTTPException(404, "黑名单记录不存在")
    session.delete(record)
    session.commit()
    return {"ok": True}

@app.post("/load_config", response_model=ProjectPublic)
async def load_config(file: UploadFile = File(...), project_name: str = Form(""), session: Session = Depends(get_session)):
    """Backward-compatible alias for the original single-project upload UI."""
    return await add_project(name=project_name, file=file, session=session)

@app.post("/start-server", response_model=ParentJobPublic)
def start_server(body: RequestBody, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    project = project_or_404(body.project_id, session)
    client = client_for(project)
    operation = client.start_instance(body.zone, body.instance_name)
    parentjob = ParentJob(name=body.instance_name, zone=body.zone,
                        status=operation.status, type=OperationType.START,
                        is_successful=False, project_id=project.id)
    session.add(parentjob)
    session.commit()
    session.refresh(parentjob)
    background_tasks.add_task(check_operation_status, body.zone, client, body.receiver, operation.name, parentjob)
    return ParentJobPublic.model_validate(parentjob)

@app.post("/end-server", response_model=ParentJobPublic) 
def stop_server(body: RequestBody, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    project = project_or_404(body.project_id, session)
    client = client_for(project)
    operation = client.stop_instance(body.zone, body.instance_name)
    parentjob = ParentJob(name=body.instance_name, zone=body.zone,
                        status=operation.status, type=OperationType.STOP,
                        is_successful=False, project_id=project.id)
    session.add(parentjob)
    session.commit()
    session.refresh(parentjob)
    
    background_tasks.add_task(check_operation_status, body.zone, client, body.receiver, operation.name, parentjob)
    return parentjob
    
@app.get("/server-status")
def server_status(zone: str, instance_name: str, project_id: int | None = None,
                  session: Session = Depends(get_session)):
    project = project_or_404(project_id, session)
    return client_for(project).get_instance_status(zone, instance_name)

@app.get("/list-server")
def list_server(project_id: int | None = None, session: Session = Depends(get_session)):
    try:
        project = project_or_404(project_id, session)
        client = client_for(project)
        result = []
        instances = client.list_all_instances()
        for zone, instance in instances.items():
            for machine in instance:
                result.append({"Instance Name": machine.name, "Instance Status": machine.status,
                               "Zone": zone, "Project ID": project.id,
                               "GCP Project": project.project_id})
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Server error: {str(e)}")

