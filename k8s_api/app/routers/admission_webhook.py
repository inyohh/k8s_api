from fastapi import APIRouter, Request
from pydantic import BaseModel
from kubernetes import client, config

router = APIRouter(prefix="/admission", tags=["AdmissionWebhook"])

NODE_CAPACITY = {
    "cpu": 32.0,
    "memory": 64.0,
    "storage": 1024.0
}

def parse_cpu(cpu_str: str) -> float:
    if cpu_str.endswith('m'):
        return float(cpu_str[:-1]) / 1000.0
    else:
        return float(cpu_str)

def parse_memory(mem_str: str) -> float:
    mem_str = mem_str.strip()
    units = {"Ki": 1 / 1024 / 1024, "Mi": 1 / 1024, "Gi": 1, "Ti": 1024}
    for unit in units:
        if mem_str.endswith(unit):
            val = float(mem_str[:-len(unit)])
            return val * units[unit]
    val = float(mem_str)
    return val / 1024 / 1024 / 1024

def parse_storage(stor_str: str) -> float:
    return parse_memory(stor_str)

def get_node_allocations():
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    v1 = client.CoreV1Api()
    nodes = v1.list_node().items
    # 只保留非控制平面节点
    node_names = [
        node.metadata.name
        for node in nodes
        if "node-role.kubernetes.io/control-plane" not in node.metadata.labels
        and "node-role.kubernetes.io/master" not in node.metadata.labels
    ]
    allocations = {n: {"cpu": 0.0, "memory": 0.0, "storage": 0.0} for n in node_names}
    pods = v1.list_pod_for_all_namespaces().items
    for pod in pods:
        if pod.status.phase not in ("Running", "Pending"):
            continue
        node_name = pod.spec.node_name
        if not node_name or node_name not in allocations:
            continue
        for c in pod.spec.containers:
            res = c.resources.requests
            if not res:
                continue
            cpu = parse_cpu(res.get("cpu", "0"))
            memory = parse_memory(res.get("memory", "0"))
            storage = 0.0
            allocations[node_name]["cpu"] += cpu
            allocations[node_name]["memory"] += memory
            allocations[node_name]["storage"] += storage
    return allocations

def can_schedule(allocations, req_cpu, req_mem, req_stor):
    for node, used in allocations.items():
        free_cpu = NODE_CAPACITY["cpu"] - used["cpu"]
        free_mem = NODE_CAPACITY["memory"] - used["memory"]
        free_stor = NODE_CAPACITY["storage"] - used["storage"]
        if free_cpu >= req_cpu and free_mem >= req_mem and free_stor >= req_stor:
            if req_cpu <= 4 and req_mem <= 10 and req_stor <= 120:
                return True
    return False

class AdmissionReview(BaseModel):
    request: dict

@router.post("/validate")
async def validate(request: Request):
    body = await request.json()
    admission = AdmissionReview(**body)
    uid = admission.request.get("uid")
    pod_spec = admission.request.get("object", {}).get("spec", {})
    containers = pod_spec.get("containers", [])
    total_cpu = 0.0
    total_mem = 0.0
    total_stor = 0.0
    for c in containers:
        reqs = c.get("resources", {}).get("requests", {})
        total_cpu += parse_cpu(reqs.get("cpu", "0"))
        total_mem += parse_memory(reqs.get("memory", "0"))
    allocations = get_node_allocations()
    allowed = can_schedule(allocations, total_cpu, total_mem, total_stor)
    response = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": allowed,
        }
    }
    if not allowed:
        response["response"]["status"] = {
            "code": 403,
            "message": (
                f"资源不足，集群所有节点均无法满足请求 "
                f"cpu={total_cpu} core, memory={total_mem} GiB"
            )
        }
    return response
