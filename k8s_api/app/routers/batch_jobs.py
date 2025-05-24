from fastapi import APIRouter, HTTPException, status, Form
from typing import List, Optional
from kubernetes.client import ApiException
from ..models import BatchJob
from ..config import load_k8s_config

# Initialize k8s client
_, batch_v1, _ = load_k8s_config()
router = APIRouter(prefix="/v2/batch_jobs", tags=["batch_jobs"])

@router.get("/{namespace}", response_model=List[BatchJob], name="v2_batch_jobs_list")
def list_batch_jobs(namespace: str):
    """List all distributed batch jobs in a namespace"""
    try:
        resp = batch_v1.list_namespaced_job(namespace=namespace)
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=e.reason)
    jobs = []
    for j in resp.items:
        # extract parameters stored in annotations
        meta = j.metadata.annotations or {}
        spec = j.spec.template.spec
        jobs.append(
            BatchJob(
                name=j.metadata.name,
                namespace=namespace,
                queue=meta.get('queue',''),
                image=spec.containers[0].image,
                command=spec.containers[0].command,
                env={e.name: e.value for e in (spec.containers[0].env or [])},
                cpu=spec.containers[0].resources.limits.get('cpu') if spec.containers[0].resources and spec.containers[0].resources.limits else None,
                memory=spec.containers[0].resources.limits.get('memory') if spec.containers[0].resources and spec.containers[0].resources.limits else None
            )
        )
    return jobs

@router.get("/{namespace}/{name}", response_model=BatchJob, name="v2_batch_jobs_read")
def read_batch_job(namespace: str, name: str):
    """Get a specific distributed batch job"""
    try:
        j = batch_v1.read_namespaced_job(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BatchJob not found")
        raise HTTPException(status_code=e.status, detail=e.reason)
    meta = j.metadata.annotations or {}
    spec = j.spec.template.spec
    return BatchJob(
        name=name,
        namespace=namespace,
        queue=meta.get('queue',''),
        image=spec.containers[0].image,
        command=spec.containers[0].command,
        env={e.name: e.value for e in (spec.containers[0].env or [])},
        cpu=spec.containers[0].resources.limits.get('cpu') if spec.containers[0].resources and spec.containers[0].resources.limits else None,
        memory=spec.containers[0].resources.limits.get('memory') if spec.containers[0].resources and spec.containers[0].resources.limits else None
    )

@router.post("/{namespace}/{name}", status_code=status.HTTP_201_CREATED, name="v2_batch_jobs_create")
def create_batch_job(
    namespace: str,
    name: str,
    min_available: int = Form(..., description="Pod minimum availability"),
    command: str = Form(..., description="Command to run in container"),
    image: str = Form(..., description="Container image to use"),
    task_name: str = Form(..., description="Task name"),
    cpu: str = Form("1", description="CPU requests"),
    mem: str = Form("1Gi", description="Memory requests"),
    task_replicas: int = Form(1, description="Number of parallel pods"),
    queue: Optional[str] = Form(None, description="Queue name"),
    node_selector: Optional[str] = Form(None, description="Node selector label"),
    dataset: Optional[str] = Form(None, description="Dataset volume name"),
    mount: Optional[str] = Form(None, description="Mount path inside container")
):
    """Create a distributed batch job as a K8s Job with parallelism"""
    # build job manifest
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "annotations": {
                "queue": queue or '',
                "task_name": task_name
            }
        },
        "spec": {
            "parallelism": task_replicas,
            "completions": task_replicas,
            "template": {
                "spec": {
                    "minReadySeconds": min_available,
                    "containers": [{
                        "name": name,
                        "image": image,
                        "command": ["/bin/sh", "-c", command],
                        "resources": {"requests": {"cpu": cpu, "memory": mem}},
                        **({"volumeMounts": [{"name": dataset, "mountPath": mount}]} if dataset and mount else {})
                    }],
                    **({"nodeSelector": {key: "" for key in [node_selector]}} if node_selector else {}),
                    **({"volumes": [{"name": dataset, "persistentVolumeClaim": {"claimName": dataset}}]} if dataset else {}),
                    "restartPolicy": "OnFailure"
                }
            }
        }
    }
    try:
        batch_v1.create_namespaced_job(body=manifest, namespace=namespace)
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=e.reason)
    return {"name": name, "namespace": namespace, "status": "Created"}

@router.delete("/{namespace}/{name}", status_code=status.HTTP_204_NO_CONTENT, name="v2_batch_jobs_delete")
def delete_batch_job(namespace: str, name: str):
    """Delete a distributed batch job"""
    try:
        batch_v1.delete_namespaced_job(name=name, namespace=namespace, propagation_policy='Foreground')
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BatchJob not found")
        raise HTTPException(status_code=e.status, detail=e.reason)
    return
