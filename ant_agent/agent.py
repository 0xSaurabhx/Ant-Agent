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
        self.session_tracked_prompt_tokens = 0
        self.session_tracked_completion_tokens = 0
        
        # Session file setup
        self.sessions_dir = workspace_dir / ".ant_agent" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        if session_id:
            self.session_id = session_id
        else:
            self.session_id = uuid.uuid4().hex
            
        self.session_file = self.sessions_dir / f"{self.session_id}.json"
        self.load_session()
        
        # Reconcile global stats with resumed session tokens
        untracked_prompt = self.session_prompt_tokens - self.session_tracked_prompt_tokens
        untracked_completion = self.session_completion_tokens - self.session_tracked_completion_tokens
        if untracked_prompt > 0 or untracked_completion > 0:
            self.record_global_usage(self.config.get("llm_model", "Unknown"), max(0, untracked_prompt), max(0, untracked_completion))
            self.session_tracked_prompt_tokens = self.session_prompt_tokens
            self.session_tracked_completion_tokens = self.session_completion_tokens
            self.save_session()
            
        self.init_client()

    def load_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, "r") as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
                    self.session_prompt_tokens = data.get("session_prompt_tokens", 0)
                    self.session_completion_tokens = data.get("session_completion_tokens", 0)
                    self.session_tracked_prompt_tokens = data.get("session_tracked_prompt_tokens", 0)
                    self.session_tracked_completion_tokens = data.get("session_tracked_completion_tokens", 0)
            except Exception:
                self.history = []
                self.session_prompt_tokens = 0
                self.session_completion_tokens = 0
                self.session_tracked_prompt_tokens = 0
                self.session_tracked_completion_tokens = 0
        else:
            self.history = []
            self.session_prompt_tokens = 0
            self.session_completion_tokens = 0
            self.session_tracked_prompt_tokens = 0
            self.session_tracked_completion_tokens = 0

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
                        if isinstance(tc, dict):
                            tc_dict = {
                                "id": tc.get("id"),
                                "type": tc.get("type", "function"),
                                "function": {
                                    "name": tc.get("function", {}).get("name", "") if tc.get("function") else "",
                                    "arguments": tc.get("function", {}).get("arguments", "") if tc.get("function") else ""
                                }
                            }
                            if "thought_signature" in tc:
                                tc_dict["thought_signature"] = tc["thought_signature"]
                            if "extra_content" in tc:
                                tc_dict["extra_content"] = tc["extra_content"]
                        else:
                            tc_dict = {
                                "id": getattr(tc, "id", None),
                                "type": getattr(tc, "type", "function"),
                                "function": {
                                    "name": getattr(tc.function, "name", "") if hasattr(tc, "function") and tc.function else "",
                                    "arguments": getattr(tc.function, "arguments", "") if hasattr(tc, "function") and tc.function else ""
                                }
                            }
                            if hasattr(tc, "thought_signature"):
                                tc_dict["thought_signature"] = getattr(tc, "thought_signature")
                            if hasattr(tc, "extra_content"):
                                tc_dict["extra_content"] = getattr(tc, "extra_content")
                            if hasattr(tc, "model_extra") and tc.model_extra:
                                for k, v in tc.model_extra.items():
                                    tc_dict[k] = v
                        serialized_tcs.append(tc_dict)
                    new_msg["tool_calls"] = serialized_tcs
                serialized_history.append(new_msg)

            with open(self.session_file, "w") as f:
                json.dump({
                    "uuid": self.session_id,
                    "history": serialized_history,
                    "session_prompt_tokens": self.session_prompt_tokens,
                    "session_completion_tokens": self.session_completion_tokens,
                    "session_tracked_prompt_tokens": self.session_tracked_prompt_tokens,
                    "session_tracked_completion_tokens": self.session_tracked_completion_tokens,
                    "timestamp": datetime.now().isoformat()
                }, f, indent=4)
        except Exception as e:
            self.console.print(f"[bold red][-] Failed to save session: {e}[/bold red]")

    def clear_session(self):
        self.history = []
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_tracked_prompt_tokens = 0
        self.session_tracked_completion_tokens = 0
        self.save_session()

    def wipe_all_sessions(self):
        self.history = []
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_tracked_prompt_tokens = 0
        self.session_tracked_completion_tokens = 0
        if self.sessions_dir.exists():
            for p in self.sessions_dir.glob("*.json"):
                try:
                    p.unlink()
                except Exception:
                    pass

    def track_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int):
        self.session_prompt_tokens += prompt_tokens
        self.session_completion_tokens += completion_tokens
        self.session_tracked_prompt_tokens += prompt_tokens
        self.session_tracked_completion_tokens += completion_tokens
        self.save_session()
        self.record_global_usage(model_name, prompt_tokens, completion_tokens)

    def record_global_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int):
        from ant_agent.config import STATS_PATH
        stats = {}
        if STATS_PATH.exists():
            try:
                with open(STATS_PATH, "r") as f:
                    stats = json.load(f)
            except Exception:
                stats = {}

        if "models" not in stats:
            stats["models"] = {}

        m_entry = stats["models"].get(model_name, {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        })

        m_entry["prompt_tokens"] += prompt_tokens
        m_entry["completion_tokens"] += completion_tokens
        m_entry["total_tokens"] += (prompt_tokens + completion_tokens)
        stats["models"][model_name] = m_entry

        total_p = sum(m.get("prompt_tokens", 0) for m in stats["models"].values())
        total_c = sum(m.get("completion_tokens", 0) for m in stats["models"].values())
        stats["total_prompt_tokens"] = total_p
        stats["total_completion_tokens"] = total_c
        stats["total_total_tokens"] = total_p + total_c

        try:
            STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(STATS_PATH, "w") as f:
                json.dump(stats, f, indent=4)
        except Exception as e:
            self.console.print(f"[bold red][-] Failed to save global stats: {e}[/bold red]")

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

    def get_clean_history_messages(self) -> list:
        """
        Returns a list of history messages optimized for token count and JSON serialization.
        Truncates older large tool outputs and converts custom tool call objects to standard dicts.
        """
        messages = []
        history_len = len(self.history)
        for idx, msg in enumerate(self.history):
            api_msg = {"role": msg["role"]}
            if "content" in msg:
                api_msg["content"] = msg["content"]
            if "name" in msg:
                api_msg["name"] = msg["name"]
            if "tool_call_id" in msg:
                api_msg["tool_call_id"] = msg["tool_call_id"]
                
            if "tool_calls" in msg and msg["tool_calls"]:
                serialized_tcs = []
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        tc_dict = {
                            "id": tc.get("id"),
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": tc.get("function", {}).get("name", "") if tc.get("function") else "",
                                "arguments": tc.get("function", {}).get("arguments", "") if tc.get("function") else ""
                            }
                        }
                        if "thought_signature" in tc:
                            tc_dict["thought_signature"] = tc["thought_signature"]
                        if "extra_content" in tc:
                            tc_dict["extra_content"] = tc["extra_content"]
                    else:
                        tc_dict = {
                            "id": getattr(tc, "id", None),
                            "type": getattr(tc, "type", "function"),
                            "function": {
                                "name": getattr(tc.function, "name", "") if hasattr(tc, "function") and tc.function else "",
                                "arguments": getattr(tc.function, "arguments", "") if hasattr(tc, "function") and tc.function else ""
                            }
                        }
                        if hasattr(tc, "thought_signature"):
                            tc_dict["thought_signature"] = getattr(tc, "thought_signature")
                        if hasattr(tc, "extra_content"):
                            tc_dict["extra_content"] = getattr(tc, "extra_content")
                        if hasattr(tc, "model_extra") and tc.model_extra:
                            for k, v in tc.model_extra.items():
                                tc_dict[k] = v
                    serialized_tcs.append(tc_dict)
                api_msg["tool_calls"] = serialized_tcs
                
                # Gemini thought_signature check: any assistant message with tool calls must contain a thought block
                if api_msg["role"] == "assistant":
                    content = api_msg.get("content") or ""
                    if "<think>" not in content.lower():
                        api_msg["content"] = f"<think>Executing tool calls.</think>\n{content}".strip()
            
            # Truncate content of older messages if needed
            if idx < history_len - 3 and "content" in api_msg and api_msg["content"]:
                content = api_msg["content"]
                if len(content) > 1000:
                    if api_msg["role"] == "tool":
                        api_msg["content"] = content[:800] + "\n... [Remaining tool output truncated to save tokens] ..."
                    elif api_msg["role"] == "user" and content.startswith("<tool_response>"):
                        api_msg["content"] = content[:800] + "\n... [Remaining tool response truncated to save tokens] ...</tool_response>"
                    elif api_msg["role"] == "assistant":
                        api_msg["content"] = content[:800] + "\n... [Remaining assistant response truncated to save tokens] ..."
            messages.append(api_msg)
        return messages

    def query_llm(self, prompt: str = None, system_override: str = None, use_history: bool = False) -> str:
        messages = []
        sys_prompt = system_override if system_override else self.get_system_prompt()
        messages.append({"role": "system", "content": sys_prompt})
        
        if use_history:
            clean_history = self.get_clean_history_messages()
            for msg in clean_history:
                messages.append(msg)
            
            if prompt and (not messages or messages[-1].get("content") != prompt):
                messages.append({"role": "user", "content": prompt})
        else:
            if prompt:
                messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.config["llm_model"],
            messages=messages,
            temperature=0.0
        )
        if hasattr(response, "usage") and response.usage:
            self.track_usage(
                self.config["llm_model"],
                getattr(response.usage, "prompt_tokens", 0),
                getattr(response.usage, "completion_tokens", 0)
            )
        return response.choices[0].message.content or ""

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

    def query_triage_llm(self, prompt: str, system_override: str) -> str:
        triage_model = self.config.get("triage_model") or self.config["llm_model"]
        messages = [
            {"role": "system", "content": system_override},
            {"role": "user", "content": prompt}
        ]
        response = self.client.chat.completions.create(
            model=triage_model,
            messages=messages,
            temperature=0.0,
            max_tokens=1000
        )
        if hasattr(response, "usage") and response.usage:
            self.track_usage(
                triage_model,
                getattr(response.usage, "prompt_tokens", 0),
                getattr(response.usage, "completion_tokens", 0)
            )
        return response.choices[0].message.content

    def triage_request(self, user_input: str) -> dict:
        triage_system_prompt = """You are a Fast Triage Router for an AI assistant.
Your task is to analyze the user's prompt and route it to either "direct" or "planner" mode.

ROUTING CRITERIA:
1. "direct":
   - Use this for simple, deterministic, single-step commands.
   - Examples: restarting a PM2 instance, running a test/linting script, checking git status, reading/displaying a specific line range, searching for a single fact on the web, simple mathematical calculations, simple conversational greetings or queries.
   - DO NOT use "direct" for requests that require analyzing code flow, reviewing file(s) for bugs or vulnerabilities, comparing multiple code sections, or explaining complex architectural patterns. These MUST go to "planner".
   - If a tool is required for direct execution, specify the tool name and the exact parameter to pass to it.
   - Eligible tools:
     * code_runner_with_tests (e.g. for running command line scripts, restarting pm2, running tests, linting)
     * python_repl (for math, date arithmetic, python code execution)
     * read_file_lines (for reading a line range of a file, parameter format: path:start-end)
     * generate_repo_map (for mapping repository structure)
     * filesystem_write (for writing a whole file)
     * filesystem_edit (for editing a file)
     * filesystem_delete (for deleting a file)
     * grep_search (for searching a pattern in files)
     * web_search (for searching the web)
     * web_fetch_and_extract (for fetching a URL)
     * vector_memory_store (for saving user info)
     * vector_memory_recall (for recalling user info)

2. "planner":
   - Use this for complex, multi-step tasks that require breaking the task down into a Directed Acyclic Graph (DAG) of sub-tasks.
   - Examples: building a full CRUD API, implementing a new feature across multiple files, debugging a complex bug, refactoring code, writing extensive documentation, analyzing a codebase or a main source file (like agent.py) to find severe issues or flow flaws.

You MUST return a JSON object with the following fields:
{
  "route": "direct" | "planner",
  "tool": "tool_name_if_direct_else_null",
  "parameter": "tool_parameter_if_direct_else_null",
  "explanation": "Brief explanation of the routing decision"
}

Do not include any markdown formatting (like ```json or ```) in your output. Return only the raw JSON string."""

        try:
            response_text = self.query_triage_llm(user_input, system_override=triage_system_prompt)
            clean_text = response_text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```(?:json)?\n", "", clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r"\n```$", "", clean_text)
            clean_text = clean_text.strip()
            
            json_match = re.search(r"(\{.*\})", clean_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(1)

            triage_data = json.loads(clean_text)
            if "route" not in triage_data:
                triage_data["route"] = "planner"
            return triage_data
        except Exception as e:
            return {
                "route": "planner",
                "tool": None,
                "parameter": None,
                "explanation": f"Failed to parse triage JSON: {e}"
            }

    def run_cycle(self, user_input: str, verbose: bool = True, status_callback=None):
        # Check if it is a continuation command
        is_continuation = False
        todo_path = Path.cwd() / ".ant_agent" / "todo.json"
        if todo_path.exists():
            try:
                with open(todo_path, "r") as f:
                    tasks = json.load(f)
                if tasks and any(not t.get("done", False) for t in tasks):
                    cleaned_input = user_input.strip().lower().rstrip(".")
                    if cleaned_input in ["continue", "go on", "next", "next step", "resume", "proceed", "run next"]:
                        is_continuation = True
            except Exception:
                pass

        # 1. Run Triage Request
        if is_continuation:
            triage_result = {
                "route": "planner",
                "tool": None,
                "parameter": None,
                "explanation": "Continuation signal detected. Continuing the existing plan."
            }
        else:
            if status_callback:
                status_callback("update", "[bold blue]Routing request...[/bold blue]")
            triage_result = self.triage_request(user_input)
        
        # 2. Handle Direct Execution Route
        if triage_result.get("route") == "direct":
            tool_name = triage_result.get("tool")
            tool_param = triage_result.get("parameter")
            
            if status_callback:
                status_callback("print", f"[bold yellow][Triage Router] Route: Direct Execution ({triage_result.get('explanation', '')})[/bold yellow]")
                if tool_name:
                    status_callback("update", f"[bold blue]Direct Execution: Routing to worker agent to run {tool_name}...[/bold blue]")
            
            self.history.append({"role": "user", "content": user_input})
            self.save_session()
            
            if tool_name and tool_name in self.config.get("active_tools", []):
                if verbose:
                    param_display = tool_param if len(tool_param) < 300 else tool_param[:300] + "..."
                    self.console.print(Panel(
                        f"[cyan]{param_display}[/cyan]",
                        title=f"[bold yellow]Tool Call (Direct): {tool_name}[/bold yellow]",
                        expand=False,
                        border_style="yellow"
                    ))
                
                try:
                    tool_instance = tools.get_tool(tool_name, self)
                    result = tool_instance.execute(tool_param)
                except Exception as e:
                    result = f"Error executing tool: {e}"
                
                if status_callback:
                    status_callback("print", f"[bold green][DONE][/bold green] Executed {tool_name}")
                
                if verbose:
                    res_display = result if len(result) < 500 else result[:500] + "...\n(Truncated)"
                    self.console.print(Panel(
                        f"[green]{res_display}[/green]",
                        title=f"[bold green]Tool Response[/bold green]",
                        expand=False,
                        border_style="green"
                    ))
                
                # Append tool call and response to history
                if self.config.get("tool_calling_method") == "native":
                    class MockFunction:
                        def __init__(self, name, args):
                            self.name = name
                            self.arguments = args
                    class MockToolCall:
                        def __init__(self, id, name, args):
                            self.id = id
                            self.type = "function"
                            self.function = MockFunction(name, args)
                    
                    mock_id = f"call_{uuid.uuid4().hex[:12]}"
                    mock_tool_call = MockToolCall(mock_id, tool_name, json.dumps({"parameter": tool_param}))
                    
                    self.history.append({
                        "role": "assistant",
                        "content": "<think>Executing tool directly based on triage routing.</think>",
                        "tool_calls": [mock_tool_call]
                    })
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": mock_id,
                        "name": tool_name,
                        "content": result
                    })
                else:
                    self.history.append({
                        "role": "assistant",
                        "content": f"<tool_call><function={tool_name}><parameter>{tool_param}</parameter></function></tool_call>"
                    })
                    self.history.append({
                        "role": "user",
                        "content": f"<tool_response>{result}</tool_response>"
                    })
                self.save_session()
                
                # Summary completion
                summary_prompt = f"The user requested: '{user_input}'.\n\nThe tool '{tool_name}' was executed with parameter: '{tool_param}'.\n\nThe tool returned the following result:\n{result}\n\nPlease summarize the result or answer the user query based on this result."
                if status_callback:
                    status_callback("update", "[bold blue]Direct Execution: Generating summary...[/bold blue]")
                
                summary_response = self.query_llm(summary_prompt, system_override="You are a helpful assistant. Provide a concise, clear response summarizing the tool execution results.", use_history=True)
                
                if status_callback:
                    status_callback("print", "[bold green][DONE][/bold green] Direct Execution summary generated.")
                
                self.history.append({"role": "assistant", "content": summary_response})
                self.save_session()
                return summary_response
            else:
                # Direct chat response (no tool needed)
                if status_callback:
                    status_callback("update", "[bold blue]Direct Execution: Generating direct response...[/bold blue]")
                
                response_text = self.query_llm(system_override=None, use_history=True)
                
                if status_callback:
                    status_callback("print", "[bold green][DONE][/bold green] Direct response generated.")
                
                self.history.append({"role": "assistant", "content": response_text})
                self.save_session()
                return response_text
        
        # 3. Handle Planner Route / Fallback
        else:
            if is_continuation:
                if status_callback:
                    status_callback("print", f"[bold yellow][Triage Router] Route: Continuing existing plan.[/bold yellow]")
                self.history.append({"role": "user", "content": user_input})
                self.save_session()
            else:
                if status_callback:
                    status_callback("print", f"[bold blue][Triage Router] Route: Planner Mode ({triage_result.get('explanation', '')})[/bold blue]")
                    status_callback("update", "[bold blue]Planner Mode: Decomposing task into Directed Acyclic Graph (DAG)...[/bold blue]")
                
                # Decompose task
                try:
                    decompose_tool = tools.get_tool("decompose_task", self)
                    decomposition = decompose_tool.execute(user_input)
                except Exception as e:
                    decomposition = f"Failed to decompose task: {e}"
                
                if status_callback:
                    status_callback("print", f"[bold green][DONE][/bold green] Task decomposed.")
                    status_callback("print", Panel(
                        decomposition,
                        title="[bold blue]Decomposed Task DAG[/bold blue]",
                        border_style="blue",
                        expand=False
                    ))
                
                # Parse steps and add to plan_and_todo list
                # Strip thoughts/reasoning tags to avoid parsing thoughts as actionable tasks
                clean_decomp = re.sub(r"<think>.*?</think>", "", decomposition, flags=re.DOTALL | re.IGNORECASE)
                clean_decomp = re.sub(r"<thought>.*?</thought>", "", clean_decomp, flags=re.DOTALL | re.IGNORECASE).strip()
                
                steps = []
                for line in clean_decomp.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    match = re.match(r'^(?:\d+[\.\)]|[\-\*\+]|\[\s*\])\s*(.+)$', line)
                    if match:
                        steps.append(match.group(1).strip())
                    elif len(line) > 5 and not line.lower().startswith("step") and not line.lower().startswith("phase"):
                        steps.append(line)
                
                if steps:
                    try:
                        todo_tool = tools.get_tool("plan_and_todo", self)
                        todo_tool.execute("clear")
                        for step in steps:
                            todo_tool.execute(f"add {step}")
                        if status_callback:
                            status_callback("print", f"[bold green][*][/bold green] Initialized plan_and_todo list with {len(steps)} sub-tasks.")
                    except Exception:
                        pass
                
                # Prepend/add the planning context to the user input
                contextualized_input = f"Task Decomposition Plan:\n{decomposition}\n\nOverall Goal: {user_input}\n\nPlease begin executing the plan. Start by calling plan_and_todo list, then work on the sub-tasks."
                self.history.append({"role": "user", "content": contextualized_input})
                self.save_session()
            
            # Run the heavy agent loop with the contextualized input
            max_iterations = self.config.get("max_iterations", 30)
            for i in range(max_iterations):
                messages = []
                messages.append({"role": "system", "content": self.get_system_prompt()})
                
                clean_history = self.get_clean_history_messages()
                has_prepended = False
                for msg in clean_history:
                    if msg["role"] == "user" and not has_prepended:
                        current_time_str = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
                        combined_content = f"Environment Details:\n- Current Time: {current_time_str}\n\nUser Query: {msg['content']}"
                        messages.append({"role": "user", "content": combined_content})
                        has_prepended = True
                    else:
                        messages.append(msg)

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
                        self.track_usage(
                            self.config["llm_model"],
                            getattr(response.usage, "prompt_tokens", 0),
                            getattr(response.usage, "completion_tokens", 0)
                        )
                except Exception as e:
                    self.console.print(f"[bold red][-] LLM Error: {e}[/bold red]")
                    return "Failed to query the LLM model. Check base URL / model name configuration."

                assistant_message = response.choices[0].message
                raw_assistant_text = assistant_message.content or ""
                assistant_text = raw_assistant_text

                thoughts = ""
                think_match = re.search(r"<think>(.*?)</think>", raw_assistant_text, re.DOTALL | re.IGNORECASE)
                if think_match:
                    thoughts = think_match.group(1).strip()
                    assistant_text = re.sub(r"<think>.*?</think>", "", raw_assistant_text, flags=re.DOTALL | re.IGNORECASE).strip()

                if status_callback:
                    status_callback("print", f"[bold green][DONE][/bold green] Thinking (turn {i+1})...")
                    if thoughts:
                        status_callback("thought", thoughts)
                
                history_msg = {"role": "assistant", "content": raw_assistant_text}
                if assistant_message.tool_calls:
                    history_msg["tool_calls"] = assistant_message.tool_calls
                self.history.append(history_msg)
                self.save_session()
     
                tool_calls_to_process = []
                if self.config.get("tool_calling_method") == "native" and assistant_message.tool_calls:
                    tool_calls_to_process = assistant_message.tool_calls
                else:
                    xml_name, xml_param = self.parse_tool_call(assistant_text)
                    if xml_name:
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
                    return assistant_text
     
            return "Reasoning loop terminated: exceeded maximum iterations."
