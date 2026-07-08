"""Agent API routes."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentCreateRequest(BaseModel):
    name: str
    model: str
    tools: List[str] = []
    memory: Optional[dict] = None


class AgentChatRequest(BaseModel):
    message: str


_agent_engine = None


def set_agent_engine(engine):
    global _agent_engine
    _agent_engine = engine


@router.post("/create")
async def create_agent(req: AgentCreateRequest):
    """Create a new AI agent."""
    if _agent_engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not initialized")
    return _agent_engine.create_agent(
        name=req.name,
        model_name=req.model,
        tools=req.tools,
        memory_config=req.memory,
    )


@router.post("/{name}/chat")
async def agent_chat(name: str, req: AgentChatRequest):
    """Send a message to an agent."""
    if _agent_engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not initialized")
    result = _agent_engine.chat(name, req.message, llm_callback=None)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/list")
async def list_agents():
    """List all registered agents."""
    if _agent_engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not initialized")
    return _agent_engine.list_agents()
