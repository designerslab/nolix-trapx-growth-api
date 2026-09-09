from typing import Literal
from pydantic import BaseModel, Field

class AgentCapability(BaseModel):
    name: str
    description: str
    mode: Literal["read","write","review","publish"]
    requires_human_approval: bool = False

class AgentDefinition(BaseModel):
    key: str
    name: str
    description: str
    brands: list[str] = Field(default_factory=list)
    capabilities: list[AgentCapability] = Field(default_factory=list)
    enabled: bool = True
