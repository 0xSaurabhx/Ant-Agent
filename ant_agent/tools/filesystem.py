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

def get_ast_nodes(file_path: Path) -> str:
    import ast
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
        tree = ast.parse(code)
        
        outline = []
        
        def walk_node(node, indent=""):
            if isinstance(node, ast.ClassDef):
                outline.append(f"{indent}- class {node.name} (line {node.lineno})")
                new_indent = indent + "  "
                for child in node.body:
                    walk_node(child, new_indent)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                outline.append(f"{indent}- {prefix} {node.name} (line {node.lineno})")
            else:
                if hasattr(node, 'body') and isinstance(node.body, list):
                    for child in node.body:
                        walk_node(child, indent)
                        
        walk_node(tree)
        return "\n".join(outline)
    except Exception as e:
        return f"  [Parsing Error: {e}]"

def get_regex_nodes(file_path: Path) -> str:
    import re
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        
        outline = []
        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()
            go_func_match = re.match(r"^func\s+([A-Za-z0-9_]+|(?:\([^\)]+\))\s+[A-Za-z0-9_]+)\s*\(", line_stripped)
            if go_func_match:
                outline.append(f"- func {go_func_match.group(1)} (line {i})")
                continue
                
            class_match = re.match(r"^class\s+([A-Za-z0-9_]+)", line_stripped)
            if class_match:
                outline.append(f"- class {class_match.group(1)} (line {i})")
                continue
                
            func_match = re.match(r"^function\s+([A-Za-z0-9_]+)?\s*\(", line_stripped)
            if func_match:
                name = func_match.group(1) or "anonymous"
                outline.append(f"- function {name} (line {i})")
                continue
                
            rs_func_match = re.match(r"^(?:pub\s+)?fn\s+([A-Za-z0-9_]+)", line_stripped)
            if rs_func_match:
                outline.append(f"- fn {rs_func_match.group(1)} (line {i})")
                continue
        return "\n".join(outline)
    except Exception as e:
        return f"  [Regex Parsing Error: {e}]"

@register_tool
class GenerateRepoMapTool(BaseTool):
    name = "generate_repo_map"
    description = "Generate a lightweight text map of the entire project structure (classes, functions, line numbers) for code navigation."

    def execute(self, parameter: str) -> str:
        import json
        from collections import defaultdict
        try:
            workspace = get_workspace()
            exclude_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".ant_agent"}
            include_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".c", ".cpp", ".h", ".java", ".rb", ".php", ".cs"}
            
            # Try running universal-ctags
            try:
                cmd = ["ctags", "-R", "-f", "-", "--fields=+n", "--output-format=json"]
                for ex in exclude_dirs:
                    cmd.append(f"--exclude={ex}")
                cmd.append(".")
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(workspace),
                    timeout=10.0
                )
                
                if result.returncode == 0:
                    file_symbols = defaultdict(list)
                    for line in result.stdout.splitlines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if data.get("_type") == "tag":
                                path = data.get("path")
                                if path and not any(part.startswith(".") for part in Path(path).parts):
                                    kind = data.get("kind")
                                    if kind in {"class", "function", "member", "method"}:
                                        file_symbols[path].append(data)
                        except Exception:
                            pass
                    
                    if file_symbols:
                        repo_map = []
                        for path in sorted(file_symbols.keys()):
                            if Path(path).suffix.lower() not in include_exts:
                                continue
                                
                            repo_map.append(f"### {path}")
                            symbols = file_symbols[path]
                            symbols.sort(key=lambda x: x.get("line", 0))
                            
                            classes = {s["name"]: s for s in symbols if s["kind"] == "class"}
                            printed_tags = set()
                            file_map = []
                            
                            for s in symbols:
                                tag_key = (s["name"], s.get("line"))
                                if tag_key in printed_tags:
                                    continue
                                    
                                scope = s.get("scope")
                                scope_kind = s.get("scopeKind")
                                
                                if scope and scope_kind == "class" and scope in classes:
                                    continue
                                    
                                if s["kind"] == "class":
                                    file_map.append(f"- class {s['name']} (line {s.get('line')})")
                                    printed_tags.add(tag_key)
                                    class_members = [
                                        m for m in symbols 
                                        if m.get("scope") == s["name"] and m.get("scopeKind") == "class"
                                    ]
                                    class_members.sort(key=lambda x: x.get("line", 0))
                                    for m in class_members:
                                        m_key = (m["name"], m.get("line"))
                                        file_map.append(f"  - def {m['name']} (line {m.get('line')})")
                                        printed_tags.add(m_key)
                                elif s["kind"] in {"function", "member", "method"}:
                                    if path.endswith(".py"):
                                        prefix = "def"
                                    elif path.endswith(".go"):
                                        prefix = "func"
                                    elif path.endswith((".js", ".ts", ".jsx", ".tsx")):
                                        prefix = "function"
                                    else:
                                        prefix = "fn"
                                    file_map.append(f"- {prefix} {s['name']} (line {s.get('line')})")
                                    printed_tags.add(tag_key)
                                    
                            if file_map:
                                repo_map.append("\n".join(f"  {line}" for line in file_map))
                                repo_map.append("")
                        
                        if repo_map:
                            return "\n".join(repo_map)
            except Exception:
                pass
            
            # Fallback to pure-python parser
            repo_map = []
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
                for file in sorted(files):
                    file_path = Path(root) / file
                    ext = file_path.suffix.lower()
                    if ext not in include_exts:
                        continue
                        
                    rel_path = file_path.relative_to(workspace)
                    repo_map.append(f"### {rel_path}")
                    
                    if ext == ".py":
                        outline = get_ast_nodes(file_path)
                    else:
                        outline = get_regex_nodes(file_path)
                        
                    if outline:
                        indented = "\n".join(f"  {line}" for line in outline.splitlines())
                        repo_map.append(indented)
                    else:
                        repo_map.append("  (No classes or functions detected)")
                    repo_map.append("")
            
            if not repo_map:
                return "No source files found in the workspace."
            return "\n".join(repo_map)
            
        except Exception as e:
            return f"Error generating repo map: {e}"

@register_tool
class ReadFileLinesTool(BaseTool):
    name = "read_file_lines"
    description = "Read specific lines of a file. Parameter format: relative_path:start_line-end_line (e.g. 'src/main.py:10-50')."

    def execute(self, parameter: str) -> str:
        try:
            parameter = parameter.strip()
            if ":" not in parameter:
                return "Error: parameter format must be relative_path:start_line-end_line (e.g. 'src/main.py:10-50')."
            
            parts = parameter.rsplit(":", 1)
            rel_path = parts[0].strip()
            range_str = parts[1].strip()
            
            if "-" not in range_str:
                return "Error: line range must be separated by a dash (e.g. '10-50')."
            
            start_str, end_str = range_str.split("-", 1)
            start_line = int(start_str.strip())
            end_line = int(end_str.strip())
            
            if start_line <= 0 or end_line <= 0:
                return "Error: line numbers must be positive integers starting from 1."
            if start_line > end_line:
                return "Error: start_line must be less than or equal to end_line."
            
            if end_line - start_line + 1 > 50:
                return "Error: You can read at most 50 lines at a time to prevent context bloat. Please specify a range of 50 lines or less."
            
            path = safe_path(rel_path)
            if not path.is_file():
                return f"Error: {rel_path} is not a file."
            
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                
            total_lines = len(lines)
            if start_line > total_lines:
                return f"Error: start_line ({start_line}) exceeds total lines in file ({total_lines})."
            
            actual_end = min(end_line, total_lines)
            selected_lines = lines[start_line - 1 : actual_end]
            
            output_lines = []
            for i, line in enumerate(selected_lines, start=start_line):
                output_lines.append(f"{i}: {line}")
                
            return "".join(output_lines)
        except ValueError:
            return "Error: invalid line numbers. Must be integers."
        except Exception as e:
            return f"Error reading file lines: {e}"
