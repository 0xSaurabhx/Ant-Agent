import os
import glob
import subprocess
from pathlib import Path
from ant_agent.tools import BaseTool, register_tool

def get_workspace() -> Path:
    # Default to current working directory or specific path
    return Path(os.getcwd()).resolve()

def safe_path(relative_path: str) -> Path:
    workspace = get_workspace()
    # Resolve the path relative to workspace
    target = Path(workspace / relative_path).resolve()
    # Ensure target path is inside workspace
    if not target.is_relative_to(workspace):
        raise ValueError(f"Path {relative_path} is outside workspace!")
    return target

@register_tool
class FilesystemReadTool(BaseTool):
    name = "filesystem_read"
    description = "Read file contents. Param: relative file path."

    def execute(self, parameter: str) -> str:
        try:
            path = safe_path(parameter.strip())
            if not path.is_file():
                return f"Error: {parameter} is not a file."
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

@register_tool
class FilesystemWriteTool(BaseTool):
    name = "filesystem_write"
    description = "Write whole file. Format: relative_path\\n=== CONTENT ===\\nfile_content"

    def execute(self, parameter: str) -> str:
        try:
            parts = parameter.split("=== CONTENT ===", 1)
            if len(parts) < 2:
                return "Error: format must be relative_path\\n=== CONTENT ===\\nfile_content"
            
            rel_path = parts[0].strip()
            content = parts[1].lstrip("\n")
            path = safe_path(rel_path)
            
            # Create directories if they do not exist
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {rel_path} ({len(content)} chars)"
        except Exception as e:
            return f"Error writing file: {e}"

@register_tool
class FilesystemEditTool(BaseTool):
    name = "filesystem_edit"
    description = "Edit file using Search/Replace. Format: relative_path\\n=== SEARCH ===\\nold_text\\n=== REPLACE ===\\nnew_text"

    def execute(self, parameter: str) -> str:
        try:
            lines = parameter.splitlines()
            if not lines:
                return "Error: empty input"
            
            rel_path = lines[0].strip()
            rest = "\n".join(lines[1:])
            
            parts = rest.split("=== REPLACE ===")
            if len(parts) < 2:
                return "Error: missing === REPLACE ==="
            
            search_part = parts[0]
            replace_part = parts[1]
            
            search_parts = search_part.split("=== SEARCH ===")
            if len(search_parts) < 2:
                return "Error: missing === SEARCH ==="
            
            search_text = search_parts[1].strip("\r\n")
            replace_text = replace_part.strip("\r\n")
            
            path = safe_path(rel_path)
            if not path.is_file():
                return f"Error: {rel_path} is not a file."
            
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                
            if search_text not in content:
                return f"Error: search text not found in {rel_path}"
            
            # Perform replacement
            new_content = content.replace(search_text, replace_text, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
                
            return f"Successfully edited {rel_path}"
        except Exception as e:
            return f"Error editing file: {e}"

@register_tool
class FilesystemDeleteTool(BaseTool):
    name = "filesystem_delete"
    description = "Delete a file. Param: relative path."

    def execute(self, parameter: str) -> str:
        try:
            path = safe_path(parameter.strip())
            if not path.exists():
                return f"Error: {parameter} does not exist."
            if path.is_file():
                path.unlink()
                return f"Successfully deleted file {parameter}"
            elif path.is_dir():
                # For safety, require manual or prevent dir deletion without check
                return "Error: directory deletion not allowed via this tool directly. Delete files individually."
            return "Error: Unknown type."
        except Exception as e:
            return f"Error deleting: {e}"

@register_tool
class GrepSearchTool(BaseTool):
    name = "grep_search"
    description = "Search text pattern in files. Param: pattern to search."

    def execute(self, parameter: str) -> str:
        try:
            pattern = parameter.strip().lower()
            workspace = get_workspace()
            matches = []
            # Walk directory
            for root, dirs, files in os.walk(workspace):
                # Skip venv/hidden dirs
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "venv" and d != ".venv"]
                for file in files:
                    file_path = Path(root) / file
                    try:
                        with open(file_path, "r", errors="ignore", encoding="utf-8") as f:
                            for i, line in enumerate(f, 1):
                                if pattern in line.lower():
                                    rel = file_path.relative_to(workspace)
                                    matches.append(f"{rel}:{i}: {line.strip()}")
                                    if len(matches) >= 50: # Limit results
                                        return "\n".join(matches) + "\n(Truncated to 50 results)"
                    except Exception:
                        pass
            if not matches:
                return "No matches found."
            return "\n".join(matches)
        except Exception as e:
            return f"Grep search failed: {e}"

@register_tool
class CodeRunnerWithTestsTool(BaseTool):
    name = "code_runner_with_tests"
    description = "Run tests/code using command. Param: test command (e.g. 'pytest' or 'go test ./...')."

    def execute(self, parameter: str) -> str:
        try:
            # Only run commands inside workspace
            cmd = parameter.strip()
            # Run test safely
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(get_workspace()),
                capture_output=True,
                text=True,
                timeout=30.0
            )
            output = f"Exit code: {result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            return output
        except Exception as e:
            return f"Execution failed: {e}"
