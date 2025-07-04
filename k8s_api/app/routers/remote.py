import io
import re
import yaml
import paramiko
import asyncio
import requests
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Body, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List
from kubernetes import config as k8s_config, client as k8s_client, watch as k8s_watch
from kubernetes.client.exceptions import ApiException

from .device_database import (
    update_usage_info,
    update_versions,
    insert_test_bench_task,
    finish_test_bench_task,
)
from .monitor import sync_bench_status

# ================== 配置与常量 ==================
router = APIRouter(prefix="/v1alpha1/remote", tags=["RemoteOps"])
JUMP_HOST = "10.64.243.100"
JUMP_PORT = 22
JUMP_USER = "root"
JUMP_PASS = "Byd@20220721"
WORKDIR = "/home/jump/config"
SCRIPT = "./generate_k8s_resources.sh"
KUBE_NS = "device-system"

k8s_config.load_kube_config()
batch_v1 = k8s_client.BatchV1Api()
core_v1 = k8s_client.CoreV1Api()

# ================== 工具函数 ==================

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=JUMP_HOST, port=JUMP_PORT,
        username=JUMP_USER, password=JUMP_PASS,
        look_for_keys=False, allow_agent=False
    )
    return client

def run_remote_command(client, cmd):
    full = f"cd {WORKDIR} && {cmd}"
    stdin, stdout, stderr = client.exec_command(full)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return exit_code, out, err

def get_nodeport(client, svc_name):
    cmd = f"kubectl -n {KUBE_NS} get svc {svc_name} -o jsonpath='{{.spec.ports[0].nodePort}}'"
    code, out, err = run_remote_command(client, cmd)
    if code != 0 or not out.isdigit():
        raise HTTPException(500, f"获取 NodePort 失败: {err or out}")
    return out

def get_pod_node_ip(svc_name, namespace=KUBE_NS):
    v1 = k8s_client.CoreV1Api()
    svc = v1.read_namespaced_service(svc_name, namespace)
    selector = svc.spec.selector
    if not selector:
        raise HTTPException(500, f"Service {svc_name} 没有 selector")
    label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])
    pods = v1.list_namespaced_pod(namespace, label_selector=label_selector).items
    if not pods:
        raise HTTPException(500, f"未找到 {svc_name} 对应的 Pod")
    node_name = pods[0].spec.node_name
    if not node_name:
        raise HTTPException(500, f"Pod 未调度到节点")
    node = v1.read_node(node_name)
    for addr in node.status.addresses:
        if addr.type == "InternalIP":
            return addr.address
    raise HTTPException(500, f"未找到节点 {node_name} 的 InternalIP")

def clean_device(device_name):
    client = ssh_connect()
    cmd = f"{SCRIPT} {device_name} clean"
    try:
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            print(f"Clean failed for {device_name}: {err or out}")
        else:
            print(f"Clean succeed for {device_name}")
    finally:
        client.close()
    update_usage_info(
        device_name=device_name,
        userinfo=None,
        usage_info=None,
        environment_purpose=None,
        connect_info=None,
    )

def parse_versions(pod_name, namespace=KUBE_NS):
    sv, soc, mcu = None, None, None
    try:
        log = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
        for line in log.splitlines():
            if "SwVersion=" in line:
                sv = line.strip().split("=",1)[1]
            if line.startswith("SOC="):
                soc = line.strip().split("=",1)[1]
            if line.startswith("MCU="):
                mcu = line.strip().split("=",1)[1]
    except Exception as e:
        print(f"Error reading pod log for {pod_name}: {e}")
    return {"SwVersion": sv, "SOC": soc, "MCU": mcu}

def call_generate_ota_job(client, device, oss_link):
    cmd = f"./generate_ota_job.sh {device} {oss_link}"
    code, out, err = run_remote_command(client, cmd)
    if code != 0:
        raise HTTPException(500, f"generate_ota_job.sh failed (exit {code}): {err or out}")
    return out

def admission_review_validate(device, env_config):
    admission_review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "ssh-env-" + device,
            "kind": {"group":"", "version":"v1", "kind":"Pod"},
            "resource": {"group":"", "version":"v1", "resource":"pods"},
            "object": {
                "spec": {
                    "containers": [
                        {
                            "name": device + "-env",
                            "image": env_config.image,
                            "resources": {
                                "requests": {
                                    "cpu": f"{env_config.cpu}",
                                    "memory": f"{env_config.memory}Gi"
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
        allowed = False
        message = f"AdmissionWebhook 调用异常: {e}"
    return allowed, message

# ================== 数据模型 ==================

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

# ================== 路由实现 ==================

@router.post("/clean")
def clean_mode(req: DeviceRequest = Body(...)):
    clean_device(req.device)
    return {"result": "Succeed"}

@router.get("/query_time_left")
def query_time_left(device: str = Query("", description="设备名称")):
    client = ssh_connect()
    cmd = f"{SCRIPT} {device} query_time_left"
    try:
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")
    finally:
        client.close()
    return {out}

@router.post("/renew_time_left")
def renew_time_left(req: DeviceDurationRequest = Body(...)):
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
    return {"result": "Succeed"}

@router.post("/ssh_dev")
def ssh_to_dev(req: DeviceMoreInfoRequest = Body(...)):
    client = ssh_connect()
    try:
        cmd = f"{SCRIPT} {req.device} ssh_dev"
        if req.duration:
            cmd += f" {req.duration}"
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")
        svc_dev = f"{req.device.lower()}-dc-proxy-svc"
        dev_port = get_nodeport(client, svc_dev)
        ssh_dev_cmd = f"ssh -p {dev_port} root@{JUMP_HOST}"
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
def ssh_to_env(req: SSHEnvRequest = Body(...)):
    cfg_path = f"{WORKDIR}/config_{req.device.lower()}.yaml"
    yaml_text = yaml.safe_dump(req.env_config.dict(), sort_keys=False)
    client = ssh_connect()
    try:
        sftp = client.open_sftp()
        with sftp.file(cfg_path, "w") as f:
            f.write(yaml_text)
        sftp.close()
        allowed, message = admission_review_validate(req.device, req.env_config)
        if not allowed:
            raise HTTPException(403, f"Failed: {message}")
        cmd = f"{SCRIPT} {req.device} ssh_env"
        if req.duration:
            cmd += f" {req.duration}"
        code, out, err = run_remote_command(client, cmd)
        if code != 0:
            raise HTTPException(500, f"Failed (exit {code}): {err or out}")
        dev_svc = f"{req.device.lower()}-dc-proxy-svc"
        env_svc = f"{req.device.lower()}-env-svc"
        dev_port = get_nodeport(client, dev_svc)
        env_port = get_nodeport(client, env_svc)
        dev_node_ip = get_pod_node_ip(dev_svc)
        env_node_ip = get_pod_node_ip(env_svc)
        ssh_dev_cmd = f"ssh -p {dev_port} root@{dev_node_ip}"
        ssh_env_cmd = f"ssh -p {env_port} user@{env_node_ip}"
        connect_info = f"ssh_dev: {ssh_dev_cmd}; ssh_env: {ssh_env_cmd}"
        update_usage_info(
            device_name=req.device,
            userinfo=req.userinfo,
            usage_info="env直连环境",
            environment_purpose=req.env_config.purpose,
            connect_info=connect_info
        )
        return {"ssh_dev": ssh_dev_cmd, "ssh_env": ssh_env_cmd}
    finally:
        client.close()

@router.post("/sync_devices_status")
def sync_devices_status():
    client = ssh_connect()
    cfg_path = f"{WORKDIR}/devices_monitor.csv"
    results = []
    try:
        sftp = client.open_sftp()
        with sftp.file(cfg_path, "r") as f:
            lines = f.readlines()
        sftp.close()
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

@router.post("/ota_jobs/submit_async")
async def ota_jobs_submit_async(
    devices: str = Body("", embed=True),
    oss_link: str = Body("", embed=True),
    user: str = Body("", embed=True),
    background_tasks: BackgroundTasks = None
):
    device_list = [d.strip() for d in devices.split(",") if d.strip()]
    succeed, failed = [], []
    for dev in device_list:
        try:
            await submit_jobs([dev], oss_link, user)
            succeed.append(dev)
        except Exception as e:
            print(f"Submit job for {dev} failed: {e}")
            failed.append(dev)
    return {"succeed": succeed, "failed": failed}

# ================== 业务流程 ==================

async def submit_jobs(devices: List[str], oss_link: str, user: str):
    client = ssh_connect()
    try:
        for dev in devices:
            call_generate_ota_job(client, dev, oss_link)
            svc_dev = f"{dev.lower()}-dc-proxy-svc"
            dev_port = get_nodeport(ssh_connect(), svc_dev)
            ssh_dev_cmd = f"ssh -p {dev_port} root@{JUMP_HOST}"
            connect_info = f"ssh_dev: {ssh_dev_cmd}"
            update_usage_info(
                device_name=dev,
                userinfo=user,
                usage_info="task",
                environment_purpose="",
                connect_info=connect_info
            )
            job_name = f"ota-{dev.lower()}"
            start_time = datetime.now()
            insert_test_bench_task(
                device_name=dev,
                task_name=job_name,
                task_type="OTA",
                user=user,
                start_time=start_time,
                result="执行中"
            )
            asyncio.create_task(watch_job(job_name, KUBE_NS, dev, oss_link, start_time, user))
    finally:
        client.close()

async def watch_job(job_name, ns, device, oss, start_time, user):
    label_selector = f"job-name={job_name}"
    pods = core_v1.list_namespaced_pod(ns, label_selector=label_selector).items
    while not pods:
        await asyncio.sleep(1)
        pods = core_v1.list_namespaced_pod(ns, label_selector=label_selector).items
    pod_name = pods[0].metadata.name
    log_task = asyncio.create_task(stream_logs(ns, pod_name))
    succeeded = False
    try:
        while True:
            job = batch_v1.read_namespaced_job(job_name, ns)
            if job.status.succeeded:
                succeeded = True
                break
            if job.status.failed and job.status.failed > 0:
                break
            await asyncio.sleep(2)
    finally:
        # 任务结束时，主动取消日志流
        log_task.cancel()
        try:
            await log_task
        except asyncio.CancelledError:
            pass
    end_time = datetime.now()
    # 拉取一次完整日志
    if succeeded:
        version_info = parse_versions(pod_name)
        update_versions(device, version_info.get("SOC"), version_info.get("MCU"), version_info.get("SwVersion"))
    result = "成功" if succeeded else "失败"
    finish_test_bench_task(
        device_name=device,
        task_name=job_name,
        start_time=start_time,
        end_time=end_time,
        result=result
    )
    try:
        clean_device(device)
    except Exception as e:
        print(f"Error cleaning device {device} after job: {e}")

async def stream_logs(namespace, pod_name):
    loop = asyncio.get_running_loop()
    def log_worker():
        w = k8s_watch.Watch()
        for line in w.stream(core_v1.read_namespaced_pod_log,
                             name=pod_name, namespace=namespace, follow=True):
            print(f"[{pod_name}] {line}")
            with open(f"/tmp/{pod_name}.log", "a") as f:
                f.write(line + "\n")
    try:
        await loop.run_in_executor(None, log_worker)
    except ApiException as e:
        body_str = e.body.decode() if isinstance(e.body, bytes) else str(e.body)
        if e.status == 400 and "ContainerCreating" in body_str:
            await asyncio.sleep(1)
            await stream_logs(namespace, pod_name)
        else:
            print(f"Error streaming logs for {pod_name}: {e}")