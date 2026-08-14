"""Agent Engine - LangGraph-based AI agent with tool calling and memory.

Builds a real LangGraph StateGraph: agent(node) -> tools(node) -> agent ...
until the LLM stops requesting tool calls. An llm_callback shim keeps the
simple test path working without a live LLM.
"""
from typing import Annotated, Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as langchain_tool

from .agent_tools import AGENT_TOOLS


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


class _CallbackLLM:
    """Duck-typed LLM that adapts a plain callable to the graph interface."""

    def __init__(self, callback: Callable):
        self._callback = callback

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        plain = [{"role": m.type, "content": m.content} for m in messages]
        text = self._callback(plain) or ""
        return AIMessage(content=text)


def _make_langchain_tools(tool_names: List[str]) -> List:
    """Convert named tools to LangChain tool objects."""
    tools = []
    for name in tool_names or []:
        func = AGENT_TOOLS.get(name)
        if func is not None:
            tools.append(langchain_tool(func))
    return tools


class AgentEngine:
    """Manages AI agents with tool-calling via LangGraph."""

    def __init__(self):
        self.agents: Dict[str, Dict] = {}

    def create_agent(
        self, name: str, model_name: str, tools: Optional[List[str]] = None,
        memory_config: Optional[Dict] = None, system_prompt: Optional[str] = None,
    ) -> Dict:
        """Create and register a new agent."""
        agent_info = {
            "name": name,
            "model": model_name,
            "tools": tools or [],
            "memory": memory_config or {"type": "conversation"},
            "system_prompt": system_prompt,
            "messages": [],
        }
        self.agents[name] = agent_info
        return {"name": name, "model": model_name, "tools": tools or []}

    def chat(
        self, name: str, user_message: str,
        llm_callback: Optional[Callable] = None, llm: Any = None,
    ) -> Dict:
        """Run a chat turn with the agent.

        Pass either a LangChain-compatible `llm` (real deployment) or the
        legacy `llm_callback` shim (tests / simple setups). With neither, a
        static response listing available tools is returned.
        """
        agent = self.agents.get(name)
        if agent is None:
            return {"error": f"Agent '{name}' not found"}

        model = llm or (_CallbackLLM(llm_callback) if llm_callback else None)
        if model is None:
            response = "No LLM provider configured. Tools available: " + ", ".join(agent["tools"] or []);
            agent["messages"].append(HumanMessage(content=user_message));
            agent["messages"].append(AIMessage(content=response));
            return {"response": response, "tool_calls": []}

        try:
            graph = self._build_graph(agent, model)
        except Exception as e:
            return {"response": f"Agent graph build failed: {e}", "tool_calls": []}

        state = {"messages": agent["messages"] + [HumanMessage(content=user_message)]}
        result_state = graph.invoke(state)
        agent["messages"] = result_state["messages"]
        last = result_state["messages"][-1]
        content = last.content if hasattr(last, "content") else str(last)
        return {
            "agent": name,
            "response": content,
            "tool_calls": getattr(last, "tool_calls", []) or [],
            "model": agent["model"],
        }

    def _build_graph(self, agent: Dict, llm: Any):
        """Build the LangGraph StateGraph with agent + tool nodes."""
        tools = _make_langchain_tools(agent["tools"])
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        tool_node = ToolNode(tools) if tools else None

        def call_model(state: AgentState):
            messages = state["messages"]
            system = agent.get("system_prompt")
            if system:
                from langchain_core.messages import SystemMessage
                messages = [SystemMessage(content=system)] + list(messages)
            response = llm_with_tools.invoke(messages)
            return {"messages": [response]}

        def should_continue(state: AgentState) -> str:
            last = state["messages"][-1]
            return "tools" if getattr(last, "tool_calls", None) else END

        graph = StateGraph(AgentState)
        graph.add_node("agent", call_model)
        if tool_node is not None:
            graph.add_node("tools", tool_node)
        graph.set_entry_point("agent")
        if tool_node is not None:
            graph.add_conditional_edges(
                "agent", should_continue, {"tools": "tools", END: END})
            graph.add_edge("tools", "agent")
        else:
            graph.add_conditional_edges("agent", should_continue, {END: END})
        return graph.compile()

    def list_agents(self) -> List[Dict]:
        return [
            {"name": a["name"], "model": a["model"], "tools": a["tools"]}
            for a in self.agents.values()
        ]

    def get_agent(self, name: str) -> Optional[Dict]:
        return self.agents.get(name)

    def delete_agent(self, name: str) -> bool:
        return self.agents.pop(name, None) is not None


_engine = None

def get_engine() -> AgentEngine:
    global _engine
    if _engine is None:
        _engine = AgentEngine()
    return _engine