import requests
import logging
from .device_database import get_bench_status, update_bench_status

PROMETHEUS_URL = "http://<prometheus_host>:9090/api/v1/query"  # 替换为你的Prometheus地址
MODULE = "icmp"
TARGET_IP = "192.168.195.3"

def fetch_probe_success(device: str) -> int:
    """从 Prometheus 查询 probe_success 值，返回 0 或 1"""
    query = f'probe_success{{device="{device}",module="{MODULE}",target="{TARGET_IP}"}}'
    try:
        resp = requests.get(PROMETHEUS_URL, params={"query": query}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        if not results:
            raise ValueError(f"No data for device={device}")
        value = results[0]["value"][1]
        return int(float(value))
    except Exception as e:
        logging.error(f"fetch_probe_success error: {e}")
        raise

def sync_bench_status(device: str) -> dict:
    """
    1. 获取最新 probe_success
    2. 读取 test_bench.bench_status
    3. 不一致时更新，并返回变化前后值
    """
    try:
        probe = fetch_probe_success(device)
        new_status = "online" if probe == 1 else "offline"
    except Exception as e:
        return {"device": device, "error": str(e)}

    old_status = get_bench_status(device)
    if old_status != new_status:
        update_bench_status(device, new_status)
        return {"device": device, "old": old_status, "new": new_status, "action": "updated"}
    else:
        return {"device": device, "old": old_status, "new": new_status, "action": "unchanged"}
