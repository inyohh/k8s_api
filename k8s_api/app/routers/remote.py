import io
import re
import yaml
import paramiko
from fastapi import APIRouter, HTTPException, Form, Query
from pydantic import BaseModel
from typing import Optional, List, Tuple

router = APIRouter(prefix="/v1alpha1/remote", tags=["RemoteOps"])

# SSH 跳板机信息
JUMP_HOST = "10.64.243.100"
JUMP_PORT = 22
JUMP_USER = "root"
JUMP_PASS = "jump666"
WORKDIR = "/home/jump/config"
SCRIPT = "./generate_k8s_resources.sh"

# ---------- 辅助函数 ----------

def ssh_connect() -> paramiko.SSHClient:
    """建立到 jump-master 的 SSH 连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=JUMP_HOST, port=JUMP_PORT,
            username=JUMP_USER, password=JUMP_PASS,
            look_for_keys=False, allow_agent=False
        )
    except Exception as e:
        raise HTTPException(500, f"SSH 连接失败: {e}")
    return client

def run_remote_command(client: paramiko.SSHClient, cmd: str) -> str:
    """在指定工作目录执行命令并返回 stdout"""
    full = f"cd {WORKDIR} && {cmd}"
    stdin, stdout, stderr = client.exec_command(full)
    err = stderr.read().decode()
    if err:
        raise HTTPException(500, f"远程命令异常: {err.strip()}")
    return stdout.read().decode().strip()

def parse_node_info(output: str) -> Tuple[str, str]:
    """
    从脚本输出中提取 NodePort 和 节点 IP，
    假设输出中包含类似：
      NodePort: 30080
      NodeIP: 192.168.8.52
    """
    port_m = re.search(r"NodePort[:\s]+(\d+)", output)
    ip_m   = re.search(r"NodeIP[:\s]+([\d\.]+)", output)
    if not port_m or not ip_m:
        raise HTTPException(500, "无法解析 NodePort/NodeIP 信息")
    return port_m.group(1), ip_m.group(1)

# ---------- 请求模型 ----------

class SSHEnvModel(BaseModel):
    device: str
    duration: Optional[str]    = None
    cpu:      Optional[str]    = None
    memory:   Optional[str]    = None
    storage:  Optional[str]    = None
    image:    Optional[str]    = None
    purpose:  Optional[str]    = None

# ---------- 路由实现 ----------

@router.post("/clean")
def clean_mode(device: str = Form(..., description="设备名称")):
    """
    mode=clean：清理模式
    调用：./generate_k8s_resources.sh <device> clean
    """
    client = ssh_connect()
    out = run_remote_command(client, f"{SCRIPT} {device} clean")
    client.close()
    return {"output": out}


@router.get("/query_time_left")
def query_time_left(
    device: str = Query(..., description="设备名称")
):
    """
    mode=query_time_left：查询剩余时间
    调用：./generate_k8s_resources.sh <device> query_time_left
    """
    client = ssh_connect()
    out = run_remote_command(client, f"{SCRIPT} {device} query_time_left")
    client.close()
    return {"remaining_time": out}


@router.post("/renew_expire")
def renew_expire(
    device: str = Form(..., description="设备名称")
):
    """
    mode=renew_expire：续期
    调用：./generate_k8s_resources.sh <device> renew_expire
    """
    client = ssh_connect()
    out = run_remote_command(client, f"{SCRIPT} {device} renew_expire")
    client.close()
    return {"output": out}


@router.post("/ssh_dev")
def ssh_to_dev(
    device: str = Form(..., description="设备名称"),
    duration: Optional[str] = Form(None, description="可选：续期时长")
):
    """
    mode=ssh_dev：SSH 到 Dev 容器
    调用：./generate_k8s_resources.sh <device> ssh_dev [duration]
    返回：ssh -p NodePort root@NodeIP
    """
    client = ssh_connect()
    cmd = f"{SCRIPT} {device} ssh_dev"
    if duration:
        cmd += f" {duration}"
    out = run_remote_command(client, cmd)
    port, ip = parse_node_info(out)
    client.close()
    return {"ssh_cmd": f"ssh -p {port} root@{ip}"}


@router.post("/ssh_env")
def ssh_to_env(spec: SSHEnvModel):
    """
    mode=ssh_env：SSH 到 Env 容器
    1) 先将 [cpu,memory,storage,image,purpose] 写入 config_<device>.yaml
    2) 执行：./generate_k8s_resources.sh <device> ssh_env [duration]
    返回：ssh -p NodePort root@NodeIP
    """
    device_lc = spec.device.lower()
    # 1) 准备 config_文件的 YAML 内容
    cfg = {
        "cpu": spec.cpu,
        "memory": spec.memory,
        "storage": spec.storage,
        "image": spec.image,
        "purpose": spec.purpose
    }
    yaml_text = yaml.safe_dump(cfg)

    client = ssh_connect()
    # 上传 config_<device>.yaml
    sftp = client.open_sftp()
    remote_path = f"{WORKDIR}/config_{device_lc}.yaml"
    with sftp.file(remote_path, "w") as f:
        f.write(yaml_text)
    sftp.close()

    # 2) 调用脚本
    cmd = f"{SCRIPT} {spec.device} ssh_env"
    if spec.duration:
        cmd += f" {spec.duration}"
    out = run_remote_command(client, cmd)

    # 3) 解析并返回 SSH 命令
    port, ip = parse_node_info(out)
    client.close()
    return {"ssh_cmd": f"ssh -p {port} root@{ip}"}
