from kubernetes import config as k8s_config

def load_kube_config():
    """
    优先加载集群内配置，失败则回退到本地 ~./kube/config
    """
    try:
        k8s_config.load_incluster_config()
    except:
        k8s_config.load_kube_config()

# Kubernetes API 对象，可选：如需直接用 client 创建/查询 Service
from kubernetes import client
load_kube_config()
core_v1_api = client.CoreV1Api()
