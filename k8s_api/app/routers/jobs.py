from fastapi import APIRouter, HTTPException, Query, Path, Form
from pydantic import BaseModel, Field
from typing import List, Optional
from kubernetes import client
from kubernetes.client.rest import ApiException

router = APIRouter(prefix="/v1alpha1", tags=["Jobs"])

# ---------- Pydantic 模型定义 ----------

class JobInfo(BaseModel):
    name: str
    namespace: str
    queue: Optional[str]
    status: str

class JobListResponse(BaseModel):
    jobs: List[JobInfo]

# ---------- 辅助函数 ----------

def get_batch_v1_api() -> client.BatchV1Api:
    return client.BatchV1Api()

# ---------- 路由实现 ----------

@router.get("/jobs/", response_model=JobListResponse)
def v1alpha1_jobs_list(
    queue: str = Query(..., min_length=1),
    namespace: str = Query(..., min_length=1),
):
    """
    GET /v1alpha1/jobs/?queue={queue}&namespace={namespace}
    按 queue 标签和 namespace 过滤所有 Job
    """
    api = get_batch_v1_api()
    try:
        jobs = api.list_namespaced_job(
            namespace=namespace,
            label_selector=f"queue={queue}"
        ).items
    except ApiException as e:
        raise HTTPException(status_code=500, detail=e.reason)

    result = []
    for j in jobs:
        status = "Unknown"
        if j.status.active:
            status = "Active"
        elif j.status.succeeded:
            status = "Succeeded"
        elif j.status.failed:
            status = "Failed"
        result.append(JobInfo(
            name=j.metadata.name,
            namespace=j.metadata.namespace,
            queue=j.metadata.labels.get("queue"),
            status=status
        ))
    return JobListResponse(jobs=result)


@router.post(
    "/namespaces/{namespace}/jobs",
    summary="在指定命名空间下创建新作业",
)
def v1alpha1_namespaces_jobs_create(
    namespace: str = Path(..., min_length=1),
    name: str = Form(..., min_length=1),
    image: str = Form(...),
    command: Optional[str] = Form(None),  # 修改为可选
    cpu: str = Form(...),
    mem: str = Form(..., description="Memory in GiB"),
    env: Optional[List[str]] = Form(None, description="环境变量，list of KEY=VAL"),
    device_type: Optional[str] = Form(None),
    device_name: Optional[str] = Form(None),
    device_label: Optional[str] = Form(None),
    queue: Optional[str] = Form(None),
    mount: Optional[str] = Form(None, description="Mount 信息，例如 hostPath:containerPath"),
    group: Optional[str] = Form(None, description="资源组筛选项，以/开头，多组逗号分隔"),
    deploy_monitor: Optional[int] = Form(0, ge=0, le=1),
):
    """
    POST /v1alpha1/namespaces/{namespace}/jobs
    """
    api = get_batch_v1_api()

    # 构造 container
    container_args = dict(
        name=name,
        image=image,
        env=[
            client.V1EnvVar(name=kv.split("=",1)[0], value=kv.split("=",1)[1])
            for kv in (env or [])
            if "=" in kv
        ],
        resources=client.V1ResourceRequirements(
            requests={"cpu": cpu, "memory": mem},
            limits={"cpu": cpu, "memory": mem}
        )
    )
    if command:
        container_args["command"] = command.split()

    container = client.V1Container(**container_args)

    # 挂载
    volume_mounts, volumes = [], []
    if mount:
        host_path, mount_path = mount.split(":",1)
        volumes.append(client.V1Volume(
            name="vol0",
            host_path=client.V1HostPathVolumeSource(path=host_path)
        ))
        volume_mounts.append(client.V1VolumeMount(
            name="vol0", mount_path=mount_path
        ))
        container.volume_mounts = volume_mounts

    # Pod 模板
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={
            "job-name": name,
            **({"queue": queue} if queue else {}),
            **({"device-label": device_label} if device_label else {}),
            **({"group": group} if group else {}),
        }),
        spec=client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=volumes
        )
    )

    job_spec = client.V1JobSpec(
        template=template,
        backoff_limit=4
    )

    body = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels={
            **({"queue": queue} if queue else {}),
            **({"device-type": device_type} if device_type else {}),
        }),
        spec=job_spec
    )

    try:
        api.create_namespaced_job(namespace=namespace, body=body)
    except ApiException as e:
        raise HTTPException(status_code=500, detail=e.reason)
    return {"message": "Job created", "name": name, "namespace": namespace}


@router.get(
    "/namespaces/{namespace}/jobs/{name}",
    response_model=JobInfo,
    summary="检索指定命名空间下特定作业信息",
)
def v1alpha1_namespaces_jobs_read(
    namespace: str = Path(..., min_length=1),
    name: str = Path(..., min_length=1),
):
    api = get_batch_v1_api()
    try:
        j = api.read_namespaced_job(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(404, "Job not found")
        raise HTTPException(500, e.reason)
    status = "Unknown"
    if j.status.active:
        status = "Active"
    elif j.status.succeeded:
        status = "Succeeded"
    elif j.status.failed:
        status = "Failed"
    return JobInfo(
        name=j.metadata.name,
        namespace=j.metadata.namespace,
        queue=j.metadata.labels.get("queue"),
        status=status
    )


@router.delete(
    "/namespaces/{namespace}/jobs/{name}",
    summary="删除指定作业",
)
def v1alpha1_namespaces_jobs_delete(
    namespace: str = Path(..., min_length=1),
    name: str = Path(..., min_length=1),
):
    api = get_batch_v1_api()
    try:
        api.delete_namespaced_job(
            name=name,
            namespace=namespace,
            propagation_policy="Foreground"
        )
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(404, "Job not found")
        raise HTTPException(500, e.reason)
    return {"message": "Job deleted", "name": name}
