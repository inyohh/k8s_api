from kubernetes import config, client

def load_k8s_config():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.BatchV1Api(), client.AppsV1Api()