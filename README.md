# GCP 开机管理面板（二次开发版）

基于 `gcp-vm-control` 独立二次开发的 Google Cloud Compute Engine 管理面板。当前版本支持多个 GCP 项目、服务账号、实例开机/关机、公网地址查看、IP 黑名单和临时公网 IP 更换。

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Containerized-blue.svg)](https://docker.com)
[![GCP](https://img.shields.io/badge/Google_Cloud-Integrated-orange.svg)](https://cloud.google.com)

## 项目定位

本项目与其他面板独立维护，不接入 GCPMX。后端使用 FastAPI、SQLModel 和 Google Cloud API，前端使用 Streamlit，数据与服务账号文件保存在 `data/` 目录中。

## 当前功能

- 多个 GCP 项目和服务账号分别保存
- 服务账号 JSON 校验与权限收紧（目录 700、文件 600）
- 项目连接测试和实例数量检查
- 跨区域读取 Compute Engine 实例
- 实例开机、关机和状态查询
- 公网地址与实例网卡外网 IP 查看
- 按实例网卡更换临时公网 IP，并自动记录原地址
- 项目级 IP 黑名单增删与去重
- SQLite 操作记录
- Docker Compose 部署

## 后续开发

1. 静态 IP 绑定、释放与历史 IP 去重策略
2. 大陆、香港、海外探针
3. 连续失败后的自动换 IP策略
4. Telegram 通知
5. 管理员登录、权限和完整审计

## 技术栈

### Backend Architecture
- **FastAPI** - High-performance async API framework with automatic OpenAPI documentation
- **SQLModel** - Type-safe database ORM with Pydantic integration
- **SQLite** - Embedded database with ACID compliance
- **Google Cloud SDK** - Native GCP API integration for compute resource management
- **Background Tasks** - Asynchronous operation monitoring and retry mechanisms
- **SMTP Integration** - Automated email notification system

### Frontend & DevOps
- **Streamlit** - Interactive web interface with real-time updates
- **Docker & Docker Compose** - Containerized microservices architecture
- **RESTful API Design** - Clean separation of concerns with proper HTTP semantics
- **Session Management** - Secure credential handling without persistent storage

### Cloud & Infrastructure
- **Google Cloud Platform** - Compute Engine API integration
- **Service Account Authentication** - Secure GCP resource access
- **Multi-zone Support** - Cross-regional instance management
- **Error Handling** - Comprehensive exception management with user-friendly messages

## API 接口

- `GET /projects`：列出已保存的 GCP 项目
- `POST /projects`：上传服务账号并添加项目
- `POST /projects/{id}/test`：测试项目 API 权限
- `DELETE /projects/{id}`：删除项目及本地凭据
- `GET /list-server?project_id=项目ID`：读取实例
- `POST /start-server`：开机
- `POST /end-server`：关机
- `GET /server-status`：读取实例状态
- `GET /ip-addresses?project_id=项目ID`：读取项目公网地址
- `GET /instances/{zone}/{name}/network`：读取实例网卡和外网 IP
- `POST /instances/{zone}/{name}/rotate-ip`：删除并重新添加临时公网访问配置
- `GET /ip-blacklist?project_id=项目ID`：读取 IP 黑名单
- `POST /ip-blacklist`：加入 IP 黑名单
- `DELETE /ip-blacklist/{id}`：删除黑名单记录

## 系统结构

```
┌─────────────────┐    HTTP/REST     ┌─────────────────┐
│   Streamlit     │ ◄──────────────► │    FastAPI      │
│   Frontend      │                  │    Backend      │
└─────────────────┘                  └─────────────────┘
                                              │
                                              ▼
┌─────────────────┐                  ┌─────────────────┐
│   SQLite DB     │                  │  Google Cloud   │
│   (Audit Log)   │                  │   Compute API   │
└─────────────────┘                  └─────────────────┘
```

## 启动

**Prerequisites**: Docker, Docker Compose, GCP Account with Compute Engine enabled

```bash
# Clone and deploy
git clone <你的新仓库地址>
cd gcp-vm-panel
cp .env.example .env

# Launch application stack
docker-compose up --build -d

# Access applications locally
# Frontend: http://localhost:8501
# API Docs: http://localhost:9001/docs
```

API 文档：`http://服务器IP:9001/docs`；管理界面：`http://服务器IP:8501`。

## 许可证

本项目基于上游 `gcp-vm-control` 的 Apache License 2.0 进行二次开发。保留原项目 `LICENSE` 文件；修改文件应注明修改内容。

## 上游 API 说明

### Core Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/load_config` | Upload service account credentials |
| `GET` | `/list-server` | Retrieve all instances across zones |
| `POST` | `/start-server` | Initialize instance startup sequence |
| `POST` | `/end-server` | Execute instance shutdown procedure |
| `GET` | `/server-status` | Query specific instance state |

**Auto-generated API documentation available at `/docs`**

## 🗃️ Data Models

### Database Schema
```python
# Parent-Child Job Tracking
ParentJob {
    id: int (PK)
    name: str (indexed)
    zone: str (indexed) 
    status: OperationStatus (indexed)
    type: OperationType (indexed)
    is_successful: bool (indexed)
}

ChildJob {
    id: int (PK)
    parent_id: int (FK)
    is_successful: bool
    request_time: datetime
    start_time: datetime
    end_time: datetime
}
```



## 🧪 Development Workflow

```bash
# Local development setup
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# Run backend with hot reload
uvicorn api.main:app --reload --host 0.0.0.0 --port 9001

# Run frontend with auto-refresh
streamlit run frontend/app.py --server.port 8501
```
