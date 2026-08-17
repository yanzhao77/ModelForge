"""Agent tools: file_read, code_search, command_execute, web_search, knowledge_search."""
import os
import shlex
import subprocess
from pathlib import Path
from core.config import settings


def tool_file_read(filepath: str) -> str:
    """Read the contents of a file."""
    if not os.path.exists(filepath):
        return f"Error: File not found: {filepath}"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 5000:
            content = content[:5000] + "\n... (truncated)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def tool_code_search(directory: str, pattern: str) -> str:
    """Search for a pattern in code files within a directory."""
    if not os.path.isdir(directory):
        return f"Error: Directory not found: {directory}"
    results = []
    code_extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h"}
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in code_extensions:
                    continue
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, 1):
                            if pattern.lower() in line.lower():
                                results.append(f"{filepath}:{lineno}: {line.strip()[:120]}")
                                if len(results) >= 20:
                                    return "\n".join(results) + "\n... (max results)"
                except Exception:
                    continue
    except Exception as e:
        return f"Error during search: {e}"
    if not results:
        return f"No matches found for '{pattern}' in {directory}"
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