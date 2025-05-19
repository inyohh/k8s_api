import sys
import os
# Ensure project root on path for absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from app.routers.jobs import router as jobs_router
from app.routers.batch_jobs import router as batch_jobs_router
from app.routers.deployments import router as deployments_router
from app.routers.batch_deployments import router as batch_deployments_router
from app.routers.nodes import router as nodes_router

# Create FastAPI app
def create_app() -> FastAPI:
    k8s_api = FastAPI(title="K8s API", version="v2")
    k8s_api.include_router(jobs_router)
    k8s_api.include_router(batch_jobs_router)
    k8s_api.include_router(deployments_router)
    k8s_api.include_router(batch_deployments_router)
    k8s_api.include_router(nodes_router)
    return k8s_api

k8s_api = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:k8s_api", host="0.0.0.0", port=8000, reload=True)
