from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class Metadata(BaseModel):
    name: str = Field(..., min_length=1)
    namespace: str = Field(..., min_length=1)

class JobSpec(BaseModel):
    namespace: str
    image: str
    command: Optional[List[str]] = None
    env: Dict[str, str] = Field(default_factory=dict)
    cpu: Optional[str] = None
    memory: Optional[str] = None

class BatchJob(Metadata, JobSpec):
    queue: str = Field(..., min_length=1)

class DeploymentRequest(Metadata, JobSpec):
    replicas: int = Field(1)
    strategy: str = Field("RollingUpdate")

class BatchDeploymentSpec(Metadata):
    image: str
    replicas: int = Field(1)
    env: Dict[str, str] = Field(default_factory=dict)