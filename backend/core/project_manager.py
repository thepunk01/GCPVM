"""GCP project credential and client lifecycle helpers."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from google.oauth2 import service_account

from core.gcloud import GCloud


MAX_CREDENTIAL_BYTES = 1024 * 1024
_clients: dict[int, tuple[str, float, GCloud]] = {}
_lock = threading.RLock()


def credentials_dir() -> Path:
    path = Path(os.getenv("GCP_PANEL_CREDENTIALS_DIR", "data/credentials"))
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def validate_credentials(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ValueError("服务账号文件为空")
    if len(raw) > MAX_CREDENTIAL_BYTES:
        raise ValueError("服务账号文件不能超过 1 MB")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("服务账号文件不是有效 JSON") from exc
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise ValueError("必须上传 Google Cloud service account JSON 文件")
    project_id = str(data.get("project_id") or "").strip()
    client_email = str(data.get("client_email") or "").strip()
    private_key = str(data.get("private_key") or "").strip()
    if not project_id or not client_email or not private_key:
        raise ValueError("服务账号文件缺少 project_id、client_email 或 private_key")
    # Parse the key before storing it, so an invalid credential never becomes
    # an apparently configured project in the panel.
    service_account.Credentials.from_service_account_info(data)
    return {"project_id": project_id, "client_email": client_email}


def store_credentials(project_key: str, raw: bytes) -> Path:
    """Write a validated credential file with owner-only permissions."""
    path = credentials_dir() / f"project-{project_key}.json"
    temp = path.with_suffix(".tmp")
    temp.write_bytes(raw)
    try:
        os.chmod(temp, 0o600)
        temp.replace(path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()
    return path


def remove_credentials(path: str | Path) -> None:
    target = Path(path)
    root = credentials_dir().resolve()
    try:
        if target.resolve().parent != root:
            return
        target.unlink(missing_ok=True)
    except OSError:
        pass


def client_for(project: Any) -> GCloud:
    """Return a cached GCloud client and invalidate it when the file changes."""
    path = Path(project.credential_path)
    if not path.is_file():
        raise FileNotFoundError("服务账号文件不存在，请重新上传")
    mtime = path.stat().st_mtime_ns
    with _lock:
        cached = _clients.get(int(project.id)) if project.id is not None else None
        if cached and cached[0] == str(path) and cached[1] == mtime:
            return cached[2]
        client = GCloud(credential_path=path)
        _clients[int(project.id)] = (str(path), mtime, client)
        return client


def invalidate(project_id: int) -> None:
    with _lock:
        _clients.pop(project_id, None)

