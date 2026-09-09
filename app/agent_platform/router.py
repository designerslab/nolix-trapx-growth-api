from fastapi import APIRouter, Depends, HTTPException
from app.security import require_api_key
from app.agent_platform.models import AgentDefinition
from app.agent_platform.registry import get_agent, list_agents

router = APIRouter()

@router.get("/v1/agents", response_model=list[AgentDefinition], dependencies=[Depends(require_api_key)], tags=["agents"])
async def list_registered_agents():
    return list_agents()

@router.get("/v1/agents/{agent_key}", response_model=AgentDefinition, dependencies=[Depends(require_api_key)], tags=["agents"])
async def get_registered_agent(agent_key: str):
    agent = get_agent(agent_key)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent
