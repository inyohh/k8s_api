from fastapi import APIRouter, HTTPException, status, Query
from typing import List
from ..models import BatchDeploymentSpec
from kubernetes.client import ApiException
from ..config import load_k8s_config

# Initialize k8s client
_, _, apps_v1 = load_k8s_config()
router = APIRouter(prefix="/v2/batch_deployments", tags=["batch_deployments"])

@router.get("/", response_model=List[BatchDeploymentSpec], name="v2_batch_deployments_list")
def list_batch_deployments(
    namespace: str = Query(..., min_length=1, description="Target Kubernetes namespace")
):
    """List all Deployments as BatchDeployments in namespace"""
    try:
        resp = apps_v1.list_namespaced_deployment(namespace=namespace)
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=e.reason)
    items: List[BatchDeploymentSpec] = []
    for d in resp.items:
        c = d.spec.template.spec.containers[0]
        items.append(BatchDeploymentSpec(
            name=d.metadata.name,
            namespace=namespace,
            image=c.image,
            replicas=d.spec.replicas,
            env={env.name: env.value for env in (c.env or [])}
        ))
    return items

@router.get("/{namespace}/{name}", response_model=BatchDeploymentSpec, name="v2_batch_deployments_read")
def read_batch_deployment(
    namespace: str,
    name: str
):
    """Read a specific BatchDeployment (Deployment)"""
    try:
        d = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BatchDeployment not found")
        raise HTTPException(status_code=e.status, detail=e.reason)
    c = d.spec.template.spec.containers[0]
    return BatchDeploymentSpec(
        name=name,
        namespace=namespace,
        image=c.image,
        replicas=d.spec.replicas,
        env={env.name: env.value for env in (c.env or [])}
    )

@router.post("/", response_model=BatchDeploymentSpec, status_code=status.HTTP_201_CREATED, name="v2_batch_deployments_create")
def create_batch_deployment(
    spec: BatchDeploymentSpec
):
    """Create or update a BatchDeployment (Deployment)"""
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
    except ApiException as e:
        if e.status == 404:
            apps_v1.create_namespaced_deployment(body=manifest, namespace=spec.namespace)
        else:
            raise HTTPException(status_code=e.status, detail=e.reason)
    return spec

@router.delete("/{namespace}/{name}", status_code=status.HTTP_204_NO_CONTENT, name="v2_batch_deployments_delete")
def delete_batch_deployment(
    namespace: str,
    name: str
):
    """Delete a BatchDeployment (Deployment)"""
    try:
        apps_v1.delete_namespaced_deployment(name=name, namespace=namespace, propagation_policy='Foreground')
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BatchDeployment not found")
        raise HTTPException(status_code=e.status, detail=e.reason)
    return
