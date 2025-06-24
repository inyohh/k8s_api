from fastapi import APIRouter, Request
from kubernetes import client, config

router = APIRouter(prefix="/admission", tags=["AdmissionWebhook"])

def parse_cpu(cpu_str):
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1]) / 1000
    return float(cpu_str)

def parse_mem(mem_str):
    if mem_str.endswith("Ki"):
        return int(mem_str[:-2]) / 1024 / 1024
    if mem_str.endswith("Mi"):
        return int(mem_str[:-2]) / 1024
    if mem_str.endswith("Gi"):
        return int(mem_str[:-2])
    return float(mem_str)

def parse_storage(storage_str):
    return parse_mem(storage_str)

@router.post("/validate")
async def validate_pod(request: Request):
    body = await request.json()
    pod = body["request"]["object"]

    containers = pod["spec"]["containers"]
    req_cpu = 0
    req_mem = 0
    req_storage = 0
    for c in containers:
        resources = c.get("resources", {})
        requests = resources.get("requests", {})
        req_cpu += parse_cpu(requests.get("cpu", "0"))
        req_mem += parse_mem(requests.get("memory", "0"))
        req_storage += parse_storage(requests.get("ephemeral-storage", "0"))

    config.load_incluster_config()
    v1 = client.CoreV1Api()
    nodes = v1.list_node().items

    can_schedule = False
    for node in nodes:
        if "node-role.kubernetes.io/control-plane" in node.metadata.labels:
            continue
        alloc = node.status.allocatable
        node_cpu = parse_cpu(alloc["cpu"])
        node_mem = parse_mem(alloc["memory"])
        node_storage = parse_storage(alloc.get("ephemeral-storage", "0"))
        if node_cpu >= req_cpu and node_mem >= req_mem and node_storage >= req_storage:
            can_schedule = True
            break

    allowed = can_schedule
    result = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": body["request"]["uid"],
            "allowed": allowed,
            "status": {
                "message": "资源不足，无法调度" if not allowed else "允许调度"
            }
        }
    }
    return result