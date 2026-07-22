import sys
import subprocess
import tempfile
from ant_agent.tools import BaseTool, register_tool

@register_tool
class PythonReplTool(BaseTool):
    name = "python_repl"
    description = (
        "Run Python code to calculate or test logic. Parameter: Python code content. "
        "Note: Do not use this tool for file searching or traversing directories. "
        "Any file access in the script must be strictly restricted to the current working directory."
    )

    def execute(self, parameter: str) -> str:
        code = parameter.strip()
        # Clean markdown code fences if model output them
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()

        # Check for unresolved knowledge gaps
        import re
        gaps = re.findall(r'__GAP::\[?([^\]\n]+)\]?__', code)
        if gaps:
            return f"Error: Code execution blocked due to unresolved Knowledge Gaps: {gaps}. You must resolve these gaps before executing."

        try:
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as temp:
                temp.write(code)
                temp_path = temp.name

            # Run Python code in a subprocess using same python executable
            result = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=15.0
            )

            # Cleanup
            try:
                import os
                os.unlink(temp_path)
            except Exception:
                pass

            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            if not output:
                output = f"Execution finished with exit code {result.returncode} (No output)."
            return output
        except subprocess.TimeoutExpired:
            return "Error: Timeout expired (15 seconds limit)."
        except Exception as e:
            return f"Error executing Python code: {e}"
