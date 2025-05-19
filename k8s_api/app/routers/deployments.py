from fastapi import APIRouter, HTTPException, status
from typing import List
from ..models import DeploymentRequest
from kubernetes.client import ApiException
from ..config import load_k8s_config

# 初始化 K8s 客户端
_, _, apps_v1 = load_k8s_config()

router = APIRouter(prefix="/v2/deployments", tags=["deployments"])

@router.get("/", response_model=List[DeploymentRequest], name="v2_deployments_list")
def list_deployments(namespace: str):
    """
    列出指定命名空间下所有 Deployment
    """
    try:
        resp = apps_v1.list_namespaced_deployment(namespace=namespace)
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=e.reason)

    results = []
    for item in resp.items:
        # 将 K8s 原生对象转换为我们的 Pydantic 模型
        dr = DeploymentRequest(
            name=item.metadata.name,
            namespace=namespace,
            image=item.spec.template.spec.containers[0].image,
            command=item.spec.template.spec.containers[0].command or None,
            env={e.name: e.value for e in (item.spec.template.spec.containers[0].env or [])},
            cpu=item.spec.template.spec.containers[0].resources.limits.get("cpu") if item.spec.template.spec.containers[0].resources and item.spec.template.spec.containers[0].resources.limits else None,
            memory=item.spec.template.spec.containers[0].resources.limits.get("memory") if item.spec.template.spec.containers[0].resources and item.spec.template.spec.containers[0].resources.limits else None,
            replicas=resp.items[0].spec.replicas,
            strategy=resp.items[0].spec.strategy.type if resp.items[0].spec.strategy else None
        )
        results.append(dr)
    return results

@router.get("/{namespace}/{name}", response_model=DeploymentRequest, name="v2_deployments_read")
def read_deployment(namespace: str, name: str):
    """
    获取某个 Deployment 的详细信息
    """
    try:
        item = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
        else:
            raise HTTPException(status_code=e.status, detail=e.reason)

    container = item.spec.template.spec.containers[0]
    return DeploymentRequest(
        name=name,
        namespace=namespace,
        image=container.image,
        command=container.command or None,
        env={e.name: e.value for e in (container.env or [])},
        cpu=container.resources.limits.get("cpu") if container.resources and container.resources.limits else None,
        memory=container.resources.limits.get("memory") if container.resources and container.resources.limits else None,
        replicas=item.spec.replicas,
        strategy=item.spec.strategy.type if item.spec.strategy else None
    )

@router.post("/{namespace}/{name}", response_model=DeploymentRequest, status_code=status.HTTP_201_CREATED, name="v2_deployments_create")
def create_deployment(namespace: str, name: str, spec: DeploymentRequest):
    """
    创建或更新 Deployment
    """
    # 构建 manifest
    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "replicas": spec.replicas,
            "strategy": {"type": spec.strategy},
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "containers": [{
                        "name": name,
                        "image": spec.image,
                        **({"command": spec.command} if spec.command else {}),
                        "env": [{"name": k, "value": v} for k, v in spec.env.items()],
                        **({"resources": {"limits": {"cpu": spec.cpu, "memory": spec.memory}}} if spec.cpu or spec.memory else {})
                    }]
                }
            }
        }
    }
    try:
        # 尝试更新，若不存在则创建
        apps_v1.replace_namespaced_deployment(name=name, namespace=namespace, body=manifest)
    except ApiException as e:
        if e.status == 404:
            apps_v1.create_namespaced_deployment(body=manifest, namespace=namespace)
        else:
            raise HTTPException(status_code=e.status, detail=e.reason)

    # 返回最新 spec
    return spec

@router.delete("/{namespace}/{name}", status_code=status.HTTP_204_NO_CONTENT, name="v2_deployments_delete")
def delete_deployment(namespace: str, name: str):
    """
    删除指定 Deployment
    """
    try:
        apps_v1.delete_namespaced_deployment(name=name, namespace=namespace, propagation_policy="Foreground")
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
        else:
            raise HTTPException(status_code=e.status, detail=e.reason)
    return
