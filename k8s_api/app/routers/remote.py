import io
import re
import yaml
import paramiko
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from typing import Optional
from .device_database import update_usage_info
from .monitor import sync_bench_status
from kubernetes import client, config

router = APIRouter(prefix="/v1alpha1/remote", tags=["RemoteOps"])

# SSH 跳板机信息
JUMP_HOST = "10.64.243.100"
JUMP_PORT = 22
JUMP_USER = "root"
JUMP_PASS = "Byd@20220721"
WORKDIR = "/home/jump/config"
SCRIPT = "./generate_k8s_resources.sh"
KUBE_NS = "device-system"

def ssh_connect() -> paramiko.SSHClient:
    import logging
    logging.basicConfig(level=logging.INFO)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=JUMP_HOST, port=JUMP_PORT,
            username=JUMP_USER, password=JUMP_PASS,
            look_for_keys=False, allow_agent=False
        )
    except Exception as e:
        logging.error(f"SSH 连接失败: {e}")
        raise HTTPException(500, f"SSH 连接失败: {e}")
    return client

def run_remote_command(client: paramiko.SSHClient, cmd: str) -> str:
    """
    在远程工作目录执行命令，返回 (exit_code, stdout, stderr)
    """
    full = f"cd {WORKDIR} && {cmd}"
    stdin, stdout, stderr = client.exec_command(full)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return exit_code, out, err

def get_nodeport(client: paramiko.SSHClient, svc_name: str) -> str:
    """
    kubectl -n device-system get svc <svc_name> -o jsonpath='{.spec.ports[0].nodePort}'
    """
    cmd = (
        f"kubectl -n {KUBE_NS} get svc {svc_name} "
        "-o jsonpath=\'{.spec.ports[0].nodePort}\'"
    )
    code, out, err = run_remote_command(client, cmd)
    if code != 0 or not out.isdigit():
        raise HTTPException(500, f"获取 NodePort 失败: {err or out}")
    return out

def get_pod_node_ip(svc_name: str, namespace: str = KUBE_NS) -> str:
    """
    通过 svc 名查找对应 Pod 的节点 IP
    """
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    v1 = client.CoreV1Api()
    # 先查 svc 的 selector
    svc = v1.read_namespaced_service(svc_name, namespace)
    selector = svc.spec.selector
    if not selector:
        raise HTTPException(500, f"Service {svc_name} 没有 selector")
    # 拼接 label selector
    label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])
    pods = v1.list_namespaced_pod(namespace, label_selector=label_selector).items
    if not pods:
        raise HTTPException(500, f"未找到 {svc_name} 对应的 Pod")
    # 取第一个 Pod 的 nodeName
    node_name = pods[0].spec.node_name
    if not node_name:
        raise HTTPException(500, f"Pod 未调度到节点")
    # 查节点 IP
    node = v1.read_node(node_name)
    for addr in node.status.addresses:
        if addr.type == "InternalIP":
            return addr.address
    raise HTTPException(500, f"未找到节点 {node_name} 的 InternalIP")

# ---------- Env 配置结构体定义 ----------

class DeviceRequest(BaseModel):
    device: str = Field("", description="设备名称")

class DeviceDurationRequest(DeviceRequest):
    duration: Optional[str] = Field("", description="续期时长")

class DeviceMoreInfoRequest(DeviceDurationRequest):
    userinfo: Optional[str] = Field("", description="用户信息")

class EnvConfig(BaseModel):
    cpu:     float  = Field(0.5, description="CPU 数量")
    memory:  int    = Field(..., ge=1, description="内存（GiB）")
    storage: int    = Field(..., ge=100, description="存储（GiB）")
    image:   str    = Field("harbor-adas.byd.com/byd-image/software/infra/device-tools:ubuntu-22-1.0.2", description="容器镜像")
    purpose: str    = Field("", description="用途说明，可为空")

class SSHEnvRequest(DeviceMoreInfoRequest):
    env_config: EnvConfig

# ---------- 路由实现 -----------

@router.post("/clean")
def clean_mode(req: DeviceRequest = Body(...)):
    """
    clean
    """
    client = ssh_connect()
    cmd = f"{SCRIPT} {req.device} clean"
    try:
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")
    finally:
        client.close()
    # 写入数据库，包含clean所有信息
    update_usage_info(
        device_name=req.device,
        userinfo=None,
        usage_info=None,
        environment_purpose=None,
        connect_info=None,
    )
    return { "result": "Succeed" }


@router.get("/query_time_left")
def query_time_left(
    device: str = Query("", description="设备名称")
):
    """
    query
    """
    client = ssh_connect()
    cmd = f"{SCRIPT} {device} query_time_left"
    try:
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")
    finally:
        client.close()
    return { out }


@router.post("/renew_time_left")
def renew_time_left(
    req: DeviceDurationRequest = Body(...)
):
    """
    renew
    """
    client = ssh_connect()
    cmd = f"{SCRIPT} {req.device} renew_time_left"
    if req.duration:
        cmd += f" {req.duration}"
    try:
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")
    finally:
        client.close()
    return { "result": "Succeed" }


@router.post("/ssh_dev")
def ssh_to_dev(
    req: DeviceMoreInfoRequest = Body(...)
):
    """
    ssh_dev
    """
    client = ssh_connect()
    try:
        # 1) 执行脚本
        cmd = f"{SCRIPT} {req.device} ssh_dev"
        if req.duration:
            cmd += f" {req.duration}"
        code, out, err = run_remote_command(client, cmd)

        # 2) 判断退出码
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")

        # 3) 获取 dev NodePort
        svc_dev = f"{req.device.lower()}-dc-proxy-svc"
        dev_port = get_nodeport(client, svc_dev)
        ssh_dev_cmd = f"ssh -p {dev_port} root@{JUMP_HOST}"
        # 写入数据库，包含所有ssh信息
        connect_info = f"ssh_dev: {ssh_dev_cmd}"
        update_usage_info(
            device_name=req.device,
            userinfo=req.userinfo,
            usage_info="dev直连环境",
            environment_purpose="",
            connect_info=connect_info
        )
        return {"ssh_dev": ssh_dev_cmd}
    finally:
        client.close()

@router.post("/ssh_env")
def ssh_to_env(
    req: SSHEnvRequest = Body(...)
):
    """
    ssh_env
    """
    cfg_path = f"{WORKDIR}/config_{req.device.lower()}.yaml"
    yaml_text = yaml.safe_dump(req.env_config.dict(), sort_keys=False)

    client = ssh_connect()
    try:
        # 1) 写入 config_<device>.yaml
        sftp = client.open_sftp()
        with sftp.file(cfg_path, "w") as f:
            f.write(yaml_text)
        sftp.close()

        # 5) AdmissionReview 校验
        import requests
        admission_review = {
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "request": {
                "uid": "ssh-env-" + req.device,
                "kind": {"group":"", "version":"v1", "kind":"Pod"},
                "resource": {"group":"", "version":"v1", "resource":"pods"},
                "object": {
                    "spec": {
                        "containers": [
                            {
                                "name": req.device + "-env",
                                "image": req.env_config.image,
                                "resources": {
                                    "requests": {
                                        "cpu": f"{req.env_config.cpu}",
                                        "memory": f"{req.env_config.memory}Gi"
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }

        try:
            resp = requests.post(
                "http://localhost:65516/admission/validate",
                json=admission_review,
                timeout=5
            )
            resp.raise_for_status()
            review_resp = resp.json().get("response", {})
            allowed = review_resp.get("allowed", False)
            message = review_resp.get("status", {}).get("message", "")
        except Exception as e:
            # Webhook 调用失败，记录日志后默认拒绝
            allowed = False
            message = f"AdmissionWebhook 调用异常: {e}"

        if allowed:
            # 2) 执行脚本
            cmd = f"{SCRIPT} {req.device} ssh_env"
            if req.duration:
                cmd += f" {req.duration}"
            code, out, err = run_remote_command(client, cmd)

            # 3) 判断退出码
            if code != 0:
                raise HTTPException(500, f"Failed (exit {code}): {err or out}")

            # 4) 获取 dev 与 env 的 NodePort
            dev_svc = f"{req.device.lower()}-dc-proxy-svc"
            env_svc = f"{req.device.lower()}-env-svc"
            dev_port = get_nodeport(client, dev_svc)
            env_port = get_nodeport(client, env_svc)
            # 在 ssh_to_env 里替换 JUMP_HOST
            dev_node_ip = get_pod_node_ip(dev_svc)
            env_node_ip = get_pod_node_ip(env_svc)
            ssh_dev_cmd = f"ssh -p {dev_port} root@{dev_node_ip}"
            ssh_env_cmd = f"ssh -p {env_port} user@{env_node_ip}"
            # 写入数据库，包含所有ssh信息
            connect_info = f"ssh_dev: {ssh_dev_cmd}; ssh_env: {ssh_env_cmd}"
            update_usage_info(
                device_name=req.device,
                userinfo=req.userinfo,
                usage_info="env直连环境",
                environment_purpose=req.env_config.purpose,
                connect_info=connect_info
            )
            return {
                "ssh_dev": ssh_dev_cmd,
                "ssh_env": ssh_env_cmd
            }
        else:
            raise HTTPException(403, f"Failed: {message}")
    finally:
        client.close()

@router.post("/sync_devices_status")
def sync_devices_status():
    """
    sync_devices_status
    """
    client = ssh_connect()
    cfg_path = f"{WORKDIR}/devices_monitor.csv"
    results = []
    try:
        # 读取 CSV 文件内容
        sftp = client.open_sftp()
        with sftp.file(cfg_path, "r") as f:
            lines = f.readlines()
        sftp.close()

        # 逐行处理，第一列为设备名
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            device = line.split(",")[0].strip()
            if device:
                try:
                    res = sync_bench_status(device)
                except Exception as e:
                    res = {"device": device, "error": str(e)}
                results.append(res)
    finally:
        client.close()
    return {"results": results}
