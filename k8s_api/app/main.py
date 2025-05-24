import uvicorn
from fastapi import FastAPI
from config import load_kube_config
from routers import webapps
from routers import databases
from routers import jobs
from fastapi.middleware.cors import CORSMiddleware

# ---------- 初始化 K8s 配置 ----------
load_kube_config()

# ---------- FastAPI 应用 ----------
app = FastAPI(
    title="Cluster Control API (K8s Edition)",
    version="v1alpha1"
)

# 若有前端跨域需求：
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 挂载路由 ----------
app.include_router(jobs.router)
app.include_router(webapps.router)
app.include_router(databases.router)

# ---------- 启动 Uvicorn ----------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=65516,
        workers=4,
        log_level="info"
    )
