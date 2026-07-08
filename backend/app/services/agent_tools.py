"""Agent tools: file_read, code_search, command_execute."""
import os
import subprocess
from typing import List


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
    """Execute a shell command and return output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=os.getcwd(),
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if len(output) > 3000:
            output = output[:3000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {e}"


AGENT_TOOLS = {
    "file_read": tool_file_read,
    "code_search": tool_code_search,
    "command_execute": tool_command_execute,
}
