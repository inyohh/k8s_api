from fastapi import APIRouter, HTTPException, status, Query
from typing import List
from ..models import JobSpec
from kubernetes.client import ApiException
from ..config import load_k8s_config

# Initialize k8s client
_, batch_v1, _ = load_k8s_config()
router = APIRouter(prefix="/v2/jobs", tags=["jobs"])

@router.get("/", response_model=List[JobSpec], name="v2_jobs_list")
def list_jobs(
    namespace: str = Query(..., min_length=1, description="Target Kubernetes namespace")
):
    """List all Jobs in a given namespace"""
    try:
        resp = batch_v1.list_namespaced_job(namespace=namespace)
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=e.reason)
    jobs: List[JobSpec] = []
    for j in resp.items:
        c = j.spec.template.spec.containers[0]
        jobs.append(JobSpec(
            namespace=namespace,
            image=c.image,
            command=c.command,
            env={env.name: env.value for env in (c.env or [])},
            cpu=c.resources.limits.get("cpu") if c.resources and c.resources.limits else None,
            memory=c.resources.limits.get("memory") if c.resources and c.resources.limits else None
        ))
    return jobs

@router.get("/{namespace}/{name}", response_model=JobSpec, name="v2_jobs_read")
def read_job(
    namespace: str,
    name: str
):
    """Read a specific Job"""
    try:
        j = batch_v1.read_namespaced_job(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        raise HTTPException(status_code=e.status, detail=e.reason)
    c = j.spec.template.spec.containers[0]
    return JobSpec(
        namespace=namespace,
        image=c.image,
        command=c.command,
        env={env.name: env.value for env in (c.env or [])},
        cpu=c.resources.limits.get("cpu") if c.resources and c.resources.limits else None,
        memory=c.resources.limits.get("memory") if c.resources and c.resources.limits else None
    )

@router.post("/{namespace}/{name}", response_model=JobSpec, status_code=status.HTTP_201_CREATED, name="v2_jobs_create")
def create_job(
    namespace: str,
    name: str,
    spec: JobSpec
):
    """Create a new Job"""
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "template": {"spec": {"containers": [{
                "name": name,
                "image": spec.image,
                **({"command": spec.command} if spec.command else {}),
                "env": [{"name": k, "value": v} for k, v in spec.env.items()],
                **({"resources": {"limits": {"cpu": spec.cpu, "memory": spec.memory}}} if spec.cpu or spec.memory else {})
            }], "restartPolicy": "Never"}},
            "backoffLimit": 1
        }
    }
    try:
        batch_v1.create_namespaced_job(body=manifest, namespace=namespace)
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=e.reason)
    return spec

@router.delete("/{namespace}/{name}", status_code=status.HTTP_204_NO_CONTENT, name="v2_jobs_delete")
def delete_job(
    namespace: str,
    name: str
):
    """Delete a Job"""
    try:
        batch_v1.delete_namespaced_job(name=name, namespace=namespace, propagation_policy='Foreground')
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        raise HTTPException(status_code=e.status, detail=e.reason)
    return