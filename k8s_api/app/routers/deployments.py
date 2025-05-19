from fastapi import APIRouter, HTTPException
from app.models import DeploymentRequest
from app.config import load_k8s_config
from typing import Dict, List
from kubernetes.client.rest import ApiException

_, _, apps_v1 = load_k8s_config()
router = APIRouter(prefix="/v2/deployments", tags=["deployments"])
_store: Dict[str, DeploymentRequest] = {}

@router.get("/", response_model=List[DeploymentRequest], name="v2_deployments_list")
def list_deployments():
    return list(_store.values())

@router.get("/{namespace}/{name}", response_model=DeploymentRequest, name="v2_deployments_read")
def read_deployment(namespace: str, name: str):
    key = f"{namespace}/{name}"
    spec = _store.get(key)
    if not spec:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return spec

@router.post("/{namespace}/{name}", response_model=DeploymentRequest, status_code=201, name="v2_deployments_create")
def create_deployment(namespace: str, name: str, spec: DeploymentRequest):
    key = f"{namespace}/{name}"
    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "replicas": spec.replicas,
            "strategy": {"type": spec.strategy},
            "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": {"app": name}},
                         "spec": {"containers": [{
                "name": name,
                "image": spec.image,
                **({"command": spec.command} if spec.command else {}),
                "env": [{"name": k, "value": v} for k, v in spec.env.items()],
                **({"resources": {"limits": {"cpu": spec.cpu, "memory": spec.memory}}} if spec.cpu or spec.memory else {})
            }]}}
        }
    }
    try:
        apps_v1.replace_namespaced_deployment(name=name, namespace=namespace, body=manifest)
    except ApiException as e:
        if e.status == 404:
            apps_v1.create_namespaced_deployment(body=manifest, namespace=namespace)
        else:
            raise HTTPException(status_code=e.status, detail=e.body)
    spec.namespace, spec.name = namespace, name
    _store[key] = spec
    return spec

@router.delete("/{namespace}/{name}", status_code=204, name="v2_deployments_delete")
def delete_deployment(namespace: str, name: str):
    key = f"{namespace}/{name}"
    try:
        apps_v1.delete_namespaced_deployment(name=name, namespace=namespace, propagation_policy='Foreground')
    except Exception:
        pass
    if key in _store:
        del _store[key]
    return