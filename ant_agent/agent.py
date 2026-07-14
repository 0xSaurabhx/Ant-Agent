import re
import json
import uuid
import openai
from pathlib import Path
from datetime import datetime
from colorama import Fore, Style
from rich.console import Console
from rich.panel import Panel
from ant_agent import tools
from ant_agent.memory import SimpleVectorDB

# Import tools modules to ensure they are registered
import ant_agent.tools.core
import ant_agent.tools.filesystem
import ant_agent.tools.python_repl
import ant_agent.tools.web

class AntAgent:
    def __init__(self, config, session_id=None):
        self.config = config
        workspace_dir = Path.cwd()
        workspace_memory_file = workspace_dir / ".ant_agent" / "memory.json"
        
        # Support setting custom paths for test isolation
        global_memory_file = config.get("global_memory_file")
        self.global_db = SimpleVectorDB(config, memory_file=global_memory_file)
        self.workspace_db = SimpleVectorDB(config, memory_file=workspace_memory_file)
        self.db = self.workspace_db  # Default reference for test compatibility
        self.history = []
        self.console = Console()
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        
        # Session file setup
        self.sessions_dir = workspace_dir / ".ant_agent" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        if session_id:
            self.session_id = session_id
        else:
            self.session_id = uuid.uuid4().hex
            
        self.session_file = self.sessions_dir / f"{self.session_id}.json"
        self.load_session()
        self.init_client()

    def load_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, "r") as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
                    self.session_prompt_tokens = data.get("session_prompt_tokens", 0)
                    self.session_completion_tokens = data.get("session_completion_tokens", 0)
            except Exception:
                self.history = []
                self.session_prompt_tokens = 0
                self.session_completion_tokens = 0
        else:
            self.history = []
            self.session_prompt_tokens = 0
            self.session_completion_tokens = 0

    def save_session(self):
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            # Sanitize history for JSON serialization
            serialized_history = []
            for msg in self.history:
                new_msg = {"role": msg["role"]}
                if "content" in msg:
                    new_msg["content"] = msg["content"]
                if "name" in msg:
                    new_msg["name"] = msg["name"]
                if "tool_call_id" in msg:
                    new_msg["tool_call_id"] = msg["tool_call_id"]
                if "tool_calls" in msg and msg["tool_calls"]:
                    serialized_tcs = []
                    for tc in msg["tool_calls"]:
                        tc_dict = {
                            "id": getattr(tc, "id", None),
                            "type": "type",
                            "function": {
                                "name": getattr(tc.function, "name", ""),
                                "arguments": getattr(tc.function, "arguments", "")
                            }
                        }
                        serialized_tcs.append(tc_dict)
                    new_msg["tool_calls"] = serialized_tcs
                serialized_history.append(new_msg)

            with open(self.session_file, "w") as f:
                json.dump({
                    "uuid": self.session_id,
                    "history": serialized_history,
                    "session_prompt_tokens": self.session_prompt_tokens,
                    "session_completion_tokens": self.session_completion_tokens,
                    "timestamp": datetime.now().isoformat()
                }, f, indent=4)
        except Exception as e:
            self.console.print(f"[bold red][-] Failed to save session: {e}[/bold red]")

    def clear_session(self):
        self.history = []
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.save_session()

    def wipe_all_sessions(self):
        self.history = []
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        if self.sessions_dir.exists():
            for p in self.sessions_dir.glob("*.json"):
                try:
                    p.unlink()
                except Exception:
                    pass

    def init_client(self):
        self.client = openai.OpenAI(
            base_url=self.config["llm_base_url"],
            api_key=self.config["llm_api_key"]
        )

    def get_tool_schemas(self):
        schemas = []
        for tname in self.config["active_tools"]:
            try:
                t_inst = tools.get_tool(tname, self)
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tname,
                        "description": t_inst.description,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "parameter": {
                                    "type": "string",
                                    "description": "The input parameter/argument for the tool"
                                }
                            },
                            "required": ["parameter"]
                        }
                    }
                })
            except Exception:
                pass
        return schemas

    def get_system_prompt(self) -> str:
        base_prompt = self.config["system_prompt"]
        available_tools = []
        for tname in self.config["active_tools"]:
            try:
                t_inst = tools.get_tool(tname, self)
                available_tools.append(f"- {tname}: {t_inst.description}")
            except Exception:
                pass
        tools_str = "\n".join(available_tools)
        return f"{base_prompt}\n\nAVAILABLE TOOLS:\n{tools_str}"

    def query_llm(self, prompt: str, system_override: str = None) -> str:
        messages = []
        sys_prompt = system_override if system_override else self.get_system_prompt()
        messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.config["llm_model"],
            messages=messages,
            temperature=0.0,
            max_tokens=1000
        )
        return response.choices[0].message.content

    def parse_tool_call(self, text: str):
        # Find the function name (support <function=name> and <function name=name>)
        fn_match = re.search(r"<function(?: name)?=[\"\']?([\w_]+)[\"\']?>", text, re.IGNORECASE)
        if not fn_match:
            return None, None
            
        tool_name = fn_match.group(1).strip()
        
        # Find the content up to the closing </function> tag
        start_idx = fn_match.end()
        end_match = re.search(r"</function>", text[start_idx:], re.IGNORECASE)
        if not end_match:
            return None, None
            
        content = text[start_idx:start_idx + end_match.start()].strip()
        
        # Strip all XML tags from the parameter content to handle any tag name variations (like <parameter>, <paramParameter>, </Parameter>)
        content = re.sub(r"<[^>]+>", "", content).strip()
        
        return tool_name, content

    def run_cycle(self, user_input: str, verbose: bool = True, status_callback=None):
        # 1. Store user input in history
        self.history.append({"role": "user", "content": user_input})
        self.save_session()
        
        # Limit loop to 15 iterations to prevent runaways
        max_iterations = 15
        for i in range(max_iterations):
            # Build messages: Include a dedicated system role message at turn 0, and dynamic env details on the first user message
            messages = []
            messages.append({"role": "system", "content": self.get_system_prompt()})
            
            has_prepended = False
            for msg in self.history:
                if msg["role"] == "user" and not has_prepended:
                    current_time_str = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
                    combined_content = f"Environment Details:\n- Current Time: {current_time_str}\n\nUser Query: {msg['content']}"
                    messages.append({"role": "user", "content": combined_content})
                    has_prepended = True
                else:
                    api_msg = {"role": msg["role"]}
                    if "content" in msg:
                        api_msg["content"] = msg["content"]
                    if "tool_calls" in msg:
                        api_msg["tool_calls"] = msg["tool_calls"]
                    if "tool_call_id" in msg:
                        api_msg["tool_call_id"] = msg["tool_call_id"]
                    if "name" in msg:
                        api_msg["name"] = msg["name"]
                    messages.append(api_msg)
 

            if status_callback:
                status_callback("update", f"[bold blue]Thinking (turn {i+1})...[/bold blue]")

            try:
                kwargs = {
                    "model": self.config["llm_model"],
                    "messages": messages,
                    "temperature": 0.0
                }
                if self.config.get("tool_calling_method") == "native":
                    tool_schemas = self.get_tool_schemas()
                    if tool_schemas:
                        kwargs["tools"] = tool_schemas
                
                response = self.client.chat.completions.create(**kwargs)
                if hasattr(response, "usage") and response.usage:
                    self.session_prompt_tokens += getattr(response.usage, "prompt_tokens", 0)
                    self.session_completion_tokens += getattr(response.usage, "completion_tokens", 0)
                    self.save_session()
            except Exception as e:
                self.console.print(f"[bold red][-] LLM Error: {e}[/bold red]")
                return "Failed to query the LLM model. Check base URL / model name configuration."

            assistant_message = response.choices[0].message
            assistant_text = assistant_message.content or ""

            # Extract thoughts inside <think>...</think>
            thoughts = ""
            think_match = re.search(r"<think>(.*?)</think>", assistant_text, re.DOTALL | re.IGNORECASE)
            if think_match:
                thoughts = think_match.group(1).strip()
                # Strip thoughts from the clean response text
                assistant_text = re.sub(r"<think>.*?</think>", "", assistant_text, flags=re.DOTALL | re.IGNORECASE).strip()

            if status_callback:
                status_callback("print", f"[bold green][DONE][/bold green] Thinking (turn {i+1})...")
                if thoughts:
                    status_callback("thought", thoughts)
            
            # Append assistant response to history
            history_msg = {"role": "assistant", "content": assistant_text}
            if assistant_message.tool_calls:
                history_msg["tool_calls"] = assistant_message.tool_calls
            self.history.append(history_msg)
            self.save_session()
 
            # Check if assistant made a tool call (either native or XML depending on config)
            tool_calls_to_process = []
            if self.config.get("tool_calling_method") == "native" and assistant_message.tool_calls:
                tool_calls_to_process = assistant_message.tool_calls
            else:
                # Fallback to XML parsing
                xml_name, xml_param = self.parse_tool_call(assistant_text)
                if xml_name:
                    # Mock a tool call object to reuse the execution logic
                    class MockFunction:
                        def __init__(self, name, param):
                            self.name = name
                            self.arguments = json.dumps({"parameter": param})
                    class MockToolCall:
                        def __init__(self, name, param):
                            self.id = "mock_xml_id"
                            self.function = MockFunction(name, param)
                    tool_calls_to_process = [MockToolCall(xml_name, xml_param)]
 
            if tool_calls_to_process:
                for tool_call in tool_calls_to_process:
                    tool_name = tool_call.function.name
                    # Extract parameter
                    try:
                        args = json.loads(tool_call.function.arguments)
                        tool_param = args.get("parameter", "")
                    except Exception:
                        tool_param = tool_call.function.arguments
 
                    if verbose:
                        param_display = tool_param if len(tool_param) < 300 else tool_param[:300] + "..."
                        self.console.print(Panel(
                            f"[cyan]{param_display}[/cyan]",
                            title=f"[bold yellow]Tool Call: {tool_name}[/bold yellow]",
                            expand=False,
                            border_style="yellow"
                        ))
 
                    if status_callback:
                        status_callback("update", f"[bold yellow]Executing {tool_name}...[/bold yellow]")
                    try:
                        tool_instance = tools.get_tool(tool_name, self)
                        result = tool_instance.execute(tool_param)
                    except Exception as e:
                        result = f"Error executing tool: {e}"

                    if status_callback:
                        status_callback("print", f"[bold green][DONE][/bold green] Executed {tool_name}")
                        import time
                        time.sleep(0.1)

                    if verbose:
                        res_display = result if len(result) < 500 else result[:500] + "...\n(Truncated)"
                        self.console.print(Panel(
                            f"[green]{res_display}[/green]",
                            title=f"[bold green]Tool Response[/bold green]",
                            expand=False,
                            border_style="green"
                        ))
 
                    # Format tool response and append to history
                    if self.config.get("tool_calling_method") == "native" and not tool_call.id.startswith("mock"):
                        self.history.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": result
                        })
                    else:
                        tool_msg_content = f"<tool_response>{result}</tool_response>"
                        self.history.append({"role": "user", "content": tool_msg_content})
                    self.save_session()
            else:
                # No tool call, assistant has finished reasoning/answering
                return assistant_text
 
        return "Reasoning loop terminated: exceeded maximum iterations."
