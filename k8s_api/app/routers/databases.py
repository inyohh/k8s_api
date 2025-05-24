import os
import tempfile
import subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from jinja2 import Environment, FileSystemLoader
from kubernetes.client.rest import ApiException
from kubernetes.client import V1Namespace, V1ObjectMeta
from config import core_v1_api
from kubernetes import client

router = APIRouter(prefix="/v1alpha1", tags=["Databases"])

# 接口模型
class DbDeploySpec(BaseModel):
    name: str = Field(..., min_length=1)
    namespace: str = Field(..., min_length=1)
    image: str
    replicas: int = 1
    container_port: int = 5432
    service_port: int = 5432
    node_port: int | None = None
    req_cpu: str = "2"
    req_mem: str = "4Gi"
    limit_cpu: str = "4"
    limit_mem: str = "8Gi"
    storage: str = "100Gi"
    mount_path: str = "/var/lib/data"
    env: dict[str, str] = {}

    class Config:
        schema_extra = {
            "example": {
                "name": "pg-db",
                "namespace": "test-ns",
                "image": "postgres:15",
                "replicas": 1,
                "container_port": 5432,
                "service_port": 5432,
                "node_port": 30001,
                "req_cpu": "500m",
                "req_mem": "1Gi",
                "limit_cpu": "1",
                "limit_mem": "2Gi",
                "storage": "10Gi",
                "mount_path": "/var/lib/postgresql/data",
                "env": {
                    "POSTGRES_PASSWORD": "example"
                }
            }
        }

# Jinja2 环境
env = Environment(loader=FileSystemLoader("templates"))

@router.post("/namespaces/{namespace}/databases", response_model=dict)
def create_db(namespace: str, spec: DbDeploySpec):
    spec.namespace = namespace

    # 检查 namespace 是否存在，不存在则创建
    try:
        core_v1_api.read_namespace(namespace)
    except ApiException as e:
        if e.status == 404:
            ns_body = V1Namespace(metadata=V1ObjectMeta(name=namespace))
            core_v1_api.create_namespace(ns_body)
        else:
            raise HTTPException(500, f"read namespace failed: {e}")

    tmpl = env.get_template("statefulset.yaml.j2")
    yaml_text = tmpl.render(**spec.dict())

    # 写临时文件并应用
    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        path = f.name

    try:
        subprocess.run(["kubectl", "apply", "-f", path],
                       check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"kubectl apply failed: {e.stderr}")

    # 查询 Service 的 nodePort
    try:
        svc = core_v1_api.read_namespaced_service(f"{spec.name}-svc", namespace)
        node_port = svc.spec.ports[0].node_port
    except ApiException as e:
        raise HTTPException(500, f"read service failed: {e}")

    return {"service": f"{spec.name}-svc", "nodePort": node_port}

@router.get("/namespaces/{namespace}/databases/{name}", response_model=dict)
def get_database(namespace: str, name: str):
    try:
        apps_v1 = client.AppsV1Api()
        sts = apps_v1.read_namespaced_stateful_set(name=name, namespace=namespace)
        return {
            "name": sts.metadata.name,
            "namespace": sts.metadata.namespace,
            "replicas": sts.spec.replicas,
            "ready_replicas": sts.status.ready_replicas,
            "labels": sts.metadata.labels,
            "image": sts.spec.template.spec.containers[0].image,
            "container_port": sts.spec.template.spec.containers[0].ports[0].container_port
        }
    except client.rest.ApiException as e:
        if e.status == 404:
            raise HTTPException(404, f"StatefulSet {name} not found in namespace {namespace}")
        else:
            raise HTTPException(500, f"Error retrieving StatefulSet: {e}")
