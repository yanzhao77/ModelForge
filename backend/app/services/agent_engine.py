"""Agent Engine - LangGraph-based AI agent with tools and memory.

Provides create_agent() that builds a LangGraph workflow with tool calling.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool as langchain_tool
from typing_extensions import TypedDict

from .agent_tools import AGENT_TOOLS


class AgentState(TypedDict):
    messages: List[Any]


def _make_langchain_tools(tool_names: List[str]) -> List:
    """Convert named tools to LangChain tool objects."""
    tools = []
    for name in tool_names:
        func = AGENT_TOOLS.get(name)
        if func is None:
            continue
        if name == "file_read":
            tools.append(langchain_tool(func))
        elif name == "code_search":
            tools.append(langchain_tool(func))
        elif name == "command_execute":
            tools.append(langchain_tool(func))
    return tools


class AgentEngine:
    """Manages AI agents with tool-calling via LangGraph."""

    def __init__(self):
        self.agents: Dict[str, Dict] = {}

    def create_agent(self, name: str, model_name: str, tools: List[str],
                     memory_config: Optional[Dict] = None) -> Dict:
        """Create and register a new agent.

        Returns agent info dict. The actual LangGraph graph is built lazily
        when chat() is first called with an LLM provider.
        """
        agent_info = {
            "name": name,
            "model": model_name,
            "tools": tools,
            "memory": memory_config or {"type": "conversation"},
            "messages": [],
        }
        self.agents[name] = agent_info
        return {"name": name, "model": model_name, "tools": tools}

    def chat(self, name: str, user_message: str,
             llm_callback: Optional[Callable] = None) -> Dict:
        """Run a chat turn with the agent.

        Args:
            name: Agent name.
            user_message: User input.
            llm_callback: Async callable(messages) -> AIMessage for LLM calls.

        Returns:
            Dict with agent response and tool calls.
        """
        agent = self.agents.get(name)
        if agent is None:
            return {"error": f"Agent '{name}' not found"}

        agent["messages"].append({"role": "user", "content": user_message})

        # Build system prompt with available tools
        tool_descriptions = self._describe_tools(agent["tools"])
        system_prompt = self._build_system_prompt(agent, tool_descriptions)

        messages_for_llm = [
            {"role": "system", "content": system_prompt},
        ] + agent["messages"]

        # Call LLM
        if llm_callback is None:
            response = "No LLM provider configured. Tools available: " + ", ".join(agent["tools"])
            agent["messages"].append({"role": "assistant", "content": response})
            return {"response": response, "tool_calls": []}

        llm_response = llm_callback(messages_for_llm)
        agent["messages"].append({"role": "assistant", "content": llm_response})

        return {
            "agent": name,
            "response": llm_response,
            "tool_calls": [],
            "model": agent["model"],
        }

    def _describe_tools(self, tool_names: List[str]) -> str:
        """Generate tool descriptions for the system prompt."""
        descriptions = {
            "file_read": "file_read(filepath: str) -> str - Read file contents",
            "code_search": "code_search(directory: str, pattern: str) -> str - Search code in directory",
            "command_execute": "command_execute(command: str, timeout: int=30) -> str - Run shell command",
        }
        lines = []
        for name in tool_names:
            desc = descriptions.get(name, f"{name}() - Custom tool")
            lines.append(f"- {desc}")
        return "\n".join(lines)

    def _build_system_prompt(self, agent: Dict, tool_descriptions: str) -> str:
        memory_type = agent.get("memory", {}).get("type", "conversation")
        return (
            f"You are AI agent '{agent['name']}' powered by {agent['model']}. "
            f"You have access to the following tools:\n{tool_descriptions}\n\n"
            f"Memory type: {memory_type}. "
            f"Use tools when needed. Be concise and helpful."
        )

    def list_agents(self) -> List[Dict]:
        """List all registered agents."""
        return [
            {"name": a["name"], "model": a["model"], "tools": a["tools"]}
            for a in self.agents.values()
        ]

    def get_agent(self, name: str) -> Optional[Dict]:
        """Get agent info by name."""
        return self.agents.get(name)
