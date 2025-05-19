from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.models import BatchDeploymentSpec
from app.config import load_k8s_config
from typing import Dict, List
from kubernetes.client.rest import ApiException
import uuid

_, _, apps_v1 = load_k8s_config()
router = APIRouter(prefix="/v2/batch_deployments", tags=["batch_deployments"])
_store: Dict[str, BatchDeploymentSpec] = {}

@router.get("/", response_model=List[BatchDeploymentSpec], name="v2_batch_deployments_list")
def list_batch_deployments():
    return list(_store.values())

@router.get("/{namespace}/{name}", response_model=BatchDeploymentSpec, name="v2_batch_deployments_read")
def read_batch_deployment(namespace: str, name: str):
    key = f"{namespace}/{name}"
    spec = _store.get(key)
    if not spec:
        raise HTTPException(status_code=404, detail="BatchDeployment not found")
    return spec

@router.post("/", response_model=BatchDeploymentSpec, status_code=201, name="v2_batch_deployments_create")
def create_batch_deployment(spec: BatchDeploymentSpec, bg_tasks: BackgroundTasks):
    key = f"{spec.namespace}/{spec.name}"
    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": spec.name, "namespace": spec.namespace},
        "spec": {
            "replicas": spec.replicas,
            "selector": {"matchLabels": {"app": spec.name}},
            "template": {"metadata": {"labels": {"app": spec.name}},
                         "spec": {"containers": [{
                "name": spec.name,
                "image": spec.image,
                "env": [{"name": k, "value": v} for k, v in spec.env.items()]
            }]}}
        }
    }
    try:
        apps_v1.replace_namespaced_deployment(name=spec.name, namespace=spec.namespace, body=manifest)
    except ApiException:
        apps_v1.create_namespaced_deployment(body=manifest, namespace=spec.namespace)
    bg_tasks.add_task(lambda ns, nm: None, spec.namespace, spec.name)
    _store[key] = spec
    return spec

@router.delete("/{namespace}/{name}", status_code=204, name="v2_batch_deployments_delete")
def delete_batch_deployment(namespace: str, name: str):
    key = f"{namespace}/{name}"
    try:
        apps_v1.delete_namespaced_deployment(name=name, namespace=namespace, propagation_policy='Foreground')
    except Exception:
        pass
    if key in _store:
        del _store[key]
    return