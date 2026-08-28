"""Agent tools: file_read, code_search, command_execute, web_search, knowledge_search."""
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from core.agent_file_access import (
    AgentFileAccessError,
    read_agent_file,
    resolve_agent_directory,
    resolve_readable_agent_file,
)
from core.config import settings


def _context_user_id(context: Any | None) -> int | None:
    """Extract the authenticated Run owner without trusting tool arguments."""
    user_id = getattr(context, "user_id", None)
    return user_id if isinstance(user_id, int) else None


def tool_file_read(filepath: str, context: Any | None = None) -> str:
    """Read a non-sensitive file only from the invoking user's workspace."""
    return read_agent_file(filepath, _context_user_id(context))


def tool_code_search(directory: str, pattern: str, context: Any | None = None) -> str:
    """Search code files within the invoking user's contained workspace."""
    if not pattern or not pattern.strip():
        raise AgentFileAccessError("SEARCH_PATTERN_REQUIRED")
    workspace, root_directory = resolve_agent_directory(directory, _context_user_id(context))
    results: list[str] = []
    code_extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h"}
    scanned = 0
    for root, dirs, files in os.walk(root_directory, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not (Path(root) / d).is_symlink()]
        for filename in files:
            if scanned >= 1_000:
                return "\n".join(results) + "\n... (scan limit reached)"
            candidate = Path(root) / filename
            if candidate.suffix.lower() not in code_extensions:
                continue
            try:
                safe_file = resolve_readable_agent_file(str(candidate), _context_user_id(context))
            except AgentFileAccessError:
                continue
            scanned += 1
            try:
                with safe_file.open("r", encoding="utf-8", errors="replace") as handle:
                    for lineno, line in enumerate(handle, 1):
                        if pattern.casefold() in line.casefold():
                            relative_path = safe_file.relative_to(workspace)
                            results.append(f"{relative_path}:{lineno}: {line.strip()[:120]}")
                            if len(results) >= 20:
                                return "\n".join(results) + "\n... (max results)"
            except OSError:
                continue
    if not results:
        return "No matches found in the permitted workspace."
    return "\n".join(results)


def tool_command_execute(command: str, timeout: int = 30) -> str:
    """Run an allowlisted diagnostic command without invoking a shell."""
    if not settings.tools.command_execution_enabled:
        return "Command execution is disabled by server configuration."
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return f"Invalid command syntax: {exc}"
    allowed_commands = {
        ("pwd",),
        ("ls",),
        ("git", "status", "--short"),
        ("git", "diff", "--stat"),
        ("git", "log", "-1", "--oneline"),
    }
    if tuple(args) not in allowed_commands:
        return "Command is not in the server allowlist."
    try:
        result = subprocess.run(
            args, shell=False, capture_output=True, text=True,
            timeout=max(1, min(int(timeout), 30)),
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if len(output) > 3000:
            output = output[:3000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as exc:
        return f"Error executing command: {exc}"

def tool_web_search(query: str) -> str:
    """Search the web (DuckDuckGo) and return formatted results."""
    from services.searcher import cached_search, format_search_context
    results = cached_search(query)
    if not results:
        return "No web results found."
    return format_search_context(results)


def tool_knowledge_search(query: str, top_k: int = 3) -> str:
    """Query the knowledge base and return matching chunks."""
    from services.knowledge_base import get_global_kb
    kb = get_global_kb()
    result = kb.query(query, top_k=top_k)
    if not result.get("results"):
        return "No knowledge base results."
    lines = []
    for r in result["results"]:
        lines.append(f"- [{r.get('source', '?')}] {r.get('text', '')}")
    return "\n".join(lines)


AGENT_TOOLS = {
    "file_read": tool_file_read,
    "code_search": tool_code_search,
    "command_execute": tool_command_execute,
    "web_search": tool_web_search,
    "knowledge_search": tool_knowledge_search,
}