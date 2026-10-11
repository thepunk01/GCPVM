import os
import time

import requests
import streamlit as st


st.set_page_config(page_title="GCP 开机管理面板", page_icon="☁️", layout="wide")
st.title("☁️ GCP 开机管理面板")
st.caption("独立管理多个 Google Cloud 项目的 Compute Engine 实例")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:9001").rstrip("/")


def api(method, path, **kwargs):
    kwargs.setdefault("timeout", 30)
    response = requests.request(method, f"{BACKEND_URL}{path}", **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text or f"HTTP {response.status_code}"}
    if response.status_code >= 400:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        raise RuntimeError(str(detail))
    return body


def load_projects():
    try:
        return api("GET", "/projects")
    except Exception as exc:
        st.error(f"无法连接管理后端：{exc}")
        return []


def project_label(project):
    return f"{project['name']} · {project['project_id']}"


projects = load_projects()
project_ids = [item["id"] for item in projects]
if "active_project_id" not in st.session_state or st.session_state.active_project_id not in project_ids:
    st.session_state.active_project_id = project_ids[0] if project_ids else None

with st.sidebar:
    st.header("项目管理")
    if projects:
        labels = {project_label(item): item["id"] for item in projects}
        selected_label = st.selectbox(
            "当前项目",
            list(labels),
            index=list(labels.values()).index(st.session_state.active_project_id)
            if st.session_state.active_project_id in labels.values() else 0,
        )
        st.session_state.active_project_id = labels[selected_label]
    else:
        st.info("还没有 GCP 项目，请先上传服务账号。")

    with st.expander("添加 GCP 项目", expanded=not projects):
        project_name = st.text_input("项目名称", placeholder="例如：新加坡节点项目")
        credential_file = st.file_uploader("服务账号 JSON", type=["json"], key="credential_file")
        if st.button("保存项目", type="primary", use_container_width=True):
            if credential_file is None:
                st.warning("请选择服务账号 JSON 文件。")
            else:
                try:
                    created = api(
                        "POST",
                        "/projects",
                        data={"name": project_name},
                        files={"file": (credential_file.name, credential_file.getvalue(), "application/json")},
                    )
                    st.session_state.active_project_id = created["id"]
                    st.success(f"项目 {created['name']} 已保存。")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if st.button("刷新项目和实例", use_container_width=True):
        st.rerun()

if not projects or st.session_state.active_project_id is None:
    st.info("请在左侧添加一个 GCP 项目后开始管理。")
    st.stop()

active_project = next(item for item in projects if item["id"] == st.session_state.active_project_id)
project_id = active_project["id"]

col1, col2, col3 = st.columns([4, 1, 1])
with col1:
    st.subheader(f"{active_project['name']} · {active_project['project_id']}")
    st.caption(active_project.get("service_account_email") or "服务账号")
with col2:
    if st.button("测试连接", use_container_width=True):
        try:
            result = api("POST", f"/projects/{project_id}/test")
            st.success(f"连接正常，发现 {result['instance_count']} 台实例")
        except Exception as exc:
            st.error(str(exc))
with col3:
    if st.button("删除项目", use_container_width=True):
        try:
            api("DELETE", f"/projects/{project_id}")
            st.success("项目已删除")
            time.sleep(0.5)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


try:
    servers = api("GET", f"/list-server?project_id={project_id}")
except Exception as exc:
    st.error(str(exc))
    servers = []

st.subheader("Compute Engine 实例")
if not servers:
    st.info("当前项目没有读取到实例，或服务账号没有 Compute Engine 读取权限。")
else:
    for index, server in enumerate(servers):
        instance_name = server["Instance Name"]
        zone = server["Zone"]
        status = str(server["Instance Status"])
        status_text = status.split(".")[-1]
        col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 2])
        with col1:
            st.markdown(f"**{instance_name}**")
            st.caption(zone)
        with col2:
            st.write(f"状态：`{status_text}`")
        with col3:
            if st.button("查看状态", key=f"status_{project_id}_{index}"):
                try:
                    current = api("GET", "/server-status", params={"project_id": project_id, "zone": zone, "instance_name": instance_name})
                    st.info(str(current))
                except Exception as exc:
                    st.error(str(exc))
        with col4:
            if status_text == "RUNNING":
                if st.button("关机", key=f"stop_{project_id}_{index}", type="secondary"):
                    try:
                        api("POST", "/end-server", json={"project_id": project_id, "zone": zone, "instance_name": instance_name, "receiver": ""})
                        st.success(f"已提交 {instance_name} 关机任务")
                        time.sleep(1)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            elif status_text in {"TERMINATED", "STOPPED", "SUSPENDED"}:
                if st.button("开机", key=f"start_{project_id}_{index}", type="primary"):
                    try:
                        api("POST", "/start-server", json={"project_id": project_id, "zone": zone, "instance_name": instance_name, "receiver": ""})
                        st.success(f"已提交 {instance_name} 开机任务")
                        time.sleep(1)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        with col5:
            if st.button("换公网 IP", key=f"rotate_{project_id}_{index}"):
                try:
                    rotated = api(
                        "POST",
                        f"/instances/{zone}/{instance_name}/rotate-ip",
                        json={"project_id": project_id, "blacklist_current": True},
                    )
                    st.success(f"已提交换 IP 操作，原地址：{rotated.get('previous_ip') or '未知'}")
                    time.sleep(1)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

st.subheader("公网 IP 与黑名单")
try:
    addresses = api("GET", "/ip-addresses", params={"project_id": project_id})
    if addresses:
        st.dataframe(
            [
                {
                    "名称": item.get("name"),
                    "地址": item.get("address"),
                    "状态": item.get("status"),
                    "类型": item.get("address_type"),
                    "范围": item.get("scope"),
                }
                for item in addresses
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("当前项目没有保留公网地址。")
except Exception as exc:
    st.error(str(exc))

with st.expander("IP 黑名单", expanded=False):
    try:
        blacklist = api("GET", "/ip-blacklist", params={"project_id": project_id})
        if blacklist:
            for item in blacklist:
                row = st.columns([3, 5, 1])
                row[0].write(item["ip_address"])
                row[1].caption(item.get("note") or "")
                if row[2].button("删除", key=f"delete_blacklist_{item['id']}"):
                    api("DELETE", f"/ip-blacklist/{item['id']}", params={"project_id": project_id})
                    st.rerun()
        else:
            st.caption("暂无黑名单地址。")
        with st.form(f"add_blacklist_{project_id}"):
            ip_address = st.text_input("IP 地址", placeholder="例如：203.0.113.10")
            note = st.text_input("备注", placeholder="例如：被风控拦截")
            if st.form_submit_button("加入黑名单"):
                try:
                    api("POST", "/ip-blacklist", json={"project_id": project_id, "ip_address": ip_address, "note": note})
                    st.success("已加入黑名单")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    except Exception as exc:
        st.error(str(exc))
