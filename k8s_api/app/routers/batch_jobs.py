from fastapi import APIRouter, HTTPException
from ..models import BatchJob
from typing import List, Dict

router = APIRouter(prefix="/v2/batch_jobs", tags=["batch_jobs"])
_store: Dict[str, BatchJob] = {}

@router.get("/", response_model=List[BatchJob], name="v2_batch_jobs_list")
def list_batch_jobs(queue: str = None, namespace: str = None):
    results = []
    for job in _store.values():
        if queue and job.queue != queue:
            continue
        if namespace and job.namespace != namespace:
            continue
        results.append(job)
    return results

@router.get("/{namespace}/{name}", response_model=BatchJob, name="v2_batch_jobs_read")
def read_batch_job(namespace: str, name: str):
    key = f"{namespace}/{name}"
    if key not in _store:
        raise HTTPException(status_code=404, detail="BatchJob not found")
    return _store[key]

@router.post("/{namespace}/{name}", response_model=BatchJob, status_code=201, name="v2_batch_jobs_create")
def create_batch_job(namespace: str, name: str, spec: BatchJob):
    key = f"{namespace}/{name}"
    spec.namespace = namespace
    spec.name = name
    _store[key] = spec
    return spec

@router.delete("/{namespace}/{name}", status_code=204, name="v2_batch_jobs_delete")
def delete_batch_job(namespace: str, name: str):
    key = f"{namespace}/{name}"
    if key not in _store:
        raise HTTPException(status_code=404, detail="BatchJob not found")
    del _store[key]