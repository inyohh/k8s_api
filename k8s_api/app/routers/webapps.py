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

router = APIRouter(prefix="/v1alpha1", tags=["Apps"])

# 接口模型
class AppDeploySpec(BaseModel):
    name: str = Field(..., min_length=1)
    namespace: str = Field(..., min_length=1)
    image: str
    replicas: int = 1
    container_port: int = 80
    service_port: int = 80
    node_port: int | None = None
    req_cpu: str = "2"
    req_mem: str = "4Gi"
    limit_cpu: str = "4"
    limit_mem: str = "8Gi"
    env: dict[str,str] = {}

    class Config:
        schema_extra = {
            "example": {
                "name": "my-webapp",
                "namespace": "test-ns",
                "image": "nginx:latest",
                "replicas": 2,
                "container_port": 80,
                "service_port": 80,
                "node_port": 30080,
                "req_cpu": "500m",
                "req_mem": "512Mi",
                "limit_cpu": "1",
                "limit_mem": "1Gi",
                "env": {
                    "ENV": "prod"
                }
            }
        }

# Jinja2 环境
env = Environment(loader=FileSystemLoader("templates"))

@router.post("/namespaces/{namespace}/apps", response_model=dict)
def create_app(namespace: str, spec: AppDeploySpec):
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

    tmpl = env.get_template("deployment.yaml.j2")
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

@router.get("/namespaces/{namespace}/apps/{name}", response_model=dict)
def get_app(namespace: str, name: str):
    try:
        apps_v1 = client.AppsV1Api()
        deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        return {
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "replicas": deployment.spec.replicas,
            "available_replicas": deployment.status.available_replicas,
            "labels": deployment.metadata.labels,
            "image": deployment.spec.template.spec.containers[0].image,
            "container_port": deployment.spec.template.spec.containers[0].ports[0].container_port
        }
    except client.rest.ApiException as e:
        if e.status == 404:
            raise HTTPException(404, f"Deployment {name} not found in namespace {namespace}")
        else:
            raise HTTPException(500, f"Error retrieving deployment: {e}")
