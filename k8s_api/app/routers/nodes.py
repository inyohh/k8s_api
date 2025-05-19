from fastapi import APIRouter, HTTPException
from app.config import load_k8s_config
from typing import List

core_v1, _, _ = load_k8s_config()
router = APIRouter(prefix="/v2/nodes", tags=["nodes"])

@router.get("/", response_model=List[str], name="v2_nodes_list")
def list_nodes():
    try:
        nodes = core_v1.list_node()
        return [n.metadata.name for n in nodes.items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))