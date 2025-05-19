from fastapi import APIRouter, HTTPException, BackgroundTasks, status
from ..models import JobSpec
import uuid
from ..config import load_k8s_config
from kubernetes.client import ApiException

# Initialize k8s client
_, batch_v1, _ = load_k8s_config()
router = APIRouter(prefix="/v2/jobs", tags=["jobs"])

# In-memory store for job metadata demonstration
_job_store: dict[str, JobSpec] = {}

@router.get("/", response_model=list[JobSpec], name="v2_jobs_list")
def list_jobs():
    """List all created job specs"""
    return list(_job_store.values())

@router.get("/{namespace}/{name}", response_model=JobSpec, name="v2_jobs_read")
def read_job(namespace: str, name: str):
    """Retrieve a specific job spec"""
    key = f"{namespace}/{name}"
    spec = _job_store.get(key)
    if not spec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return spec

@router.post("/{namespace}/{name}", response_model=dict, status_code=status.HTTP_201_CREATED, name="v2_jobs_create")
def create_job(namespace: str, name: str, spec: JobSpec, bg_tasks: BackgroundTasks):
    """Create and launch a Kubernetes Job"""
    key = f"{namespace}/{name}"
    if key in _job_store:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job already exists")
    # build manifest
    job_name = name
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": namespace},
        "spec": {
            "template": {"spec": {"containers": [{
                "name": job_name,
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
    # store spec
    spec.namespace = namespace
    _job_store[key] = spec
    # Todo: add background monitor task
    return {"name": job_name, "namespace": namespace, "status": "Created"}

@router.delete("/{namespace}/{name}", status_code=status.HTTP_204_NO_CONTENT, name="v2_jobs_delete")
def delete_job(namespace: str, name: str):
    """Delete a Kubernetes Job and its record"""
    key = f"{namespace}/{name}"
    if key not in _job_store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    try:
        batch_v1.delete_namespaced_job(name=name, namespace=namespace, propagation_policy='Foreground')
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=e.reason)
    del _job_store[key]
    return