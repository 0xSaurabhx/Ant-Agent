import os
import re
import json
import uuid
import openai
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from ant_agent import tools
from ant_agent.memory import SimpleVectorDB
from ant_agent.config import load_config
from ant_agent.tui_theme import (
    BOX_TOOL_CALL, BOX_TOOL_RESPONSE, BOX_PLAN,
    ICON_BOLT, ICON_CHECK, ICON_CLIPBOARD, ICON_WARN,
    ACCENT_CYAN, ACCENT_GREEN, ACCENT_YELLOW, ACCENT_BLUE,
)

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
        base_url = self.config.get("llm_base_url") or os.environ.get("OPENAI_BASE_URL")
        api_key = self.config.get("llm_api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.client = openai.OpenAI(
            base_url=base_url or None,
            api_key=api_key or None
        )

    def safe_chat_completion(self, **kwargs):
        import time
        retries = 5
        delay = 4
        for attempt in range(retries):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as e:
                err_msg = str(e).lower()
                is_rate_limit = "429" in err_msg or "rate limit" in err_msg or "quota" in err_msg
                if is_rate_limit and attempt < retries - 1:
                    sleep_time = delay * (2 ** attempt)
                    self.console.print(f"[bold yellow][*] Rate limit (429) hit. Waiting {sleep_time} seconds before retry...[/bold yellow]")
                    time.sleep(sleep_time)
                else:
                    raise e

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

    def is_authorization_required(self, tool_name: str) -> bool:
        auth_tools = self.config.get("authorization_required_tools")
        if auth_tools is None:
            auth_tools = self.config.get("authorization_required")
        if auth_tools is None:
            try:
                latest = load_config()
                auth_tools = latest.get("authorization_required_tools", latest.get("authorization_required", []))
            except Exception:
                auth_tools = []
        if not isinstance(auth_tools, list):
            auth_tools = []
        return tool_name in auth_tools

    def request_tool_authorization(self, tool_name: str, tool_param: str, status_callback=None, authorization_callback=None) -> bool:
        if not self.is_authorization_required(tool_name):
            return True

        if status_callback:
            status_callback("print", f"[bold yellow]{ICON_WARN} Authorization Required for Tool: '{tool_name}'[/bold yellow]")

        if callable(authorization_callback):
            return bool(authorization_callback(tool_name, tool_param))

        if hasattr(self, "authorization_callback") and callable(getattr(self, "authorization_callback", None)):
            return bool(self.authorization_callback(tool_name, tool_param))

        param_preview = tool_param if len(tool_param) < 400 else tool_param[:400] + "... (truncated)"
        self.console.print(Panel(
            f"[bold cyan]Tool:[/bold cyan] {tool_name}\n[bold cyan]Parameters:[/bold cyan]\n{param_preview}",
            title=f"[bold yellow]{ICON_WARN} Authorization Request[/bold yellow]",
            border_style=ACCENT_YELLOW,
            box=BOX_TOOL_CALL,
            expand=False
        ))

        try:
            ans = input(f"Approve execution of tool '{tool_name}'? (y/n): ").strip().lower()
            return ans in ["y", "yes"]
        except (KeyboardInterrupt, EOFError):
            return False

    def _execute_tool_with_auth(self, tool_name: str, tool_param: str, status_callback=None, authorization_callback=None) -> str:
        if not self.request_tool_authorization(tool_name, tool_param, status_callback=status_callback, authorization_callback=authorization_callback):
            if status_callback:
                status_callback("print", f"[bold red][DENIED][/bold red] User denied authorization for {tool_name}")
            return f"Tool execution denied by user: Permission for '{tool_name}' was not granted."

        tool_instance = tools.get_tool(tool_name, self)
        return tool_instance.execute(tool_param)

    def get_clean_history_messages(self) -> list:
        """
        Returns a list of history messages optimized for token count and JSON serialization.
        Converts custom tool call objects to standard dicts.
        """
        messages = []
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
            
            messages.append(api_msg)
        return messages

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            return int(len(text.split()) * 1.3)

    def count_history_tokens(self) -> int:
        total = self.count_tokens(self.get_system_prompt())
        for msg in self.history:
            if "content" in msg and msg["content"]:
                total += self.count_tokens(msg["content"])
            if "role" in msg:
                total += self.count_tokens(msg["role"])
            if "name" in msg and msg["name"]:
                total += self.count_tokens(msg["name"])
            if "tool_calls" in msg and msg["tool_calls"]:
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        total += self.count_tokens(tc.get("function", {}).get("name", ""))
                        total += self.count_tokens(tc.get("function", {}).get("arguments", ""))
                    else:
                        total += self.count_tokens(getattr(tc.function, "name", ""))
                        total += self.count_tokens(getattr(tc.function, "arguments", ""))
        return total

    def auto_summarize_history_if_needed(self):
        if not self.history or len(self.history) <= 3:
            return
            
        max_context = int(self.config.get("max_context_tokens", 8192))
        threshold = int(max_context * 0.8)
        
        current_tokens = self.count_history_tokens()
        if current_tokens < threshold:
            return
            
        if hasattr(self, "_summarizing") and self._summarizing:
            return
            
        self._summarizing = True
        try:
            self.console.print(f"[bold yellow][*] Context usage ({current_tokens} tokens) has exceeded 80% of limit ({max_context} tokens). Automatically summarizing history...[/bold yellow]")
            
            # Summarize everything except the last 3 messages
            history_to_summarize = self.history[:-3]
            history_text = ""
            for msg in history_to_summarize:
                role = msg.get("role")
                content = msg.get("content") or ""
                if role == "user":
                    history_text += f"User: {content}\n"
                elif role == "assistant":
                    history_text += f"Agent: {content}\n"
                    if "tool_calls" in msg and msg["tool_calls"]:
                        for tc in msg["tool_calls"]:
                            name = tc.get("function", {}).get("name", "") if isinstance(tc, dict) else getattr(tc.function, "name", "")
                            history_text += f"Agent Tool Call: {name}\n"
                elif role == "tool":
                    history_text += f"Tool Output: {content}\n"
            
            summary_prompt = (
                "You are an expert developer assistant. Summarize the conversation history and progress of the task execution so far. "
                "Analyze the history and provide a concise, consolidated summary containing:\n"
                "1. The Overall Goal of the user.\n"
                "2. Previous Work Progress (what has been done, what was verified, and what files were modified/created).\n"
                "3. Active Plan/Todo Checklist status (what is remaining, what is completed).\n\n"
                "Focus only on important context. Keep it professional, clear, and highly compact."
            )
            
            summary_content = self.query_llm(
                prompt=f"Here is the history to summarize:\n\n{history_text}\n\nInstructions:\n{summary_prompt}",
                system_override="You are a precise, developer-focused assistant. Output only the consolidated summary.",
                use_history=False
            )
            
            summary_msg = {
                "role": "user",
                "content": f"[CONSOLIDATED PROGRESS SUMMARY OF PREVIOUS WORK]\n\n{summary_content}"
            }
            
            self.history = [summary_msg] + self.history[-3:]
            self.save_session()
            
            new_tokens = self.count_history_tokens()
            self.console.print(f"[bold green][*] History compressed. New token count: {new_tokens} tokens (Context freed).[/bold green]")
        except Exception as e:
            self.console.print(f"[bold red][-] Auto-summarization failed: {e}[/bold red]")
        finally:
            self._summarizing = False

    def resolve_knowledge_gaps(self, gaps: list):
        self.console.print(f"[bold yellow][*] Extracted {len(gaps)} knowledge gap(s):[/bold yellow]")
        for g in gaps:
            self.console.print(f"[yellow] - {g}[/yellow]")
            
        resolutions = {}
        
        # Instantiate search and fetch tools
        from ant_agent.tools.web import WebSearchTool, WebFetchAndExtractTool
        search_tool = WebSearchTool(self)
        fetch_tool = WebFetchAndExtractTool(self)
        
        for gap in gaps:
            self.console.print(f"[bold blue][Gap Solver] Generating search query for: '{gap}'...[/bold blue]")
            
            # Step 1: Generate Search Query
            search_query_prompt = (
                f"Convert this knowledge gap into a highly specific search query "
                f"focused on finding official documentation or reference syntax:\n\nGap: {gap}"
            )
            query = self.query_llm(
                prompt=search_query_prompt,
                system_override="You are a search query generator. Generate ONLY the search query. No quotes, no markdown, no other text.",
                use_history=False
            ).strip().strip('"').strip("'")
            
            self.console.print(f"[bold blue][Gap Solver] Query generated: '{query}'. Searching...[/bold blue]")
            
            # Step 2: Search
            search_result = search_tool.execute(query)
            
            # Extract first URL from Tavily / DuckDuckGo result
            urls = re.findall(r'URL:\s*(https?://[^\s\n]+)', search_result)
            scraped_content = ""
            if urls:
                first_url = urls[0]
                self.console.print(f"[bold blue][Gap Solver] Fetching and scraping: {first_url}...[/bold blue]")
                scraped_content = fetch_tool.execute(first_url)
            
            # Step 3: Extract exact code/syntax from scraped content or search snippets
            self.console.print(f"[bold blue][Gap Solver] Extracting syntax for: '{gap}'...[/bold blue]")
            dump_prompt = (
                f"Given the following scraped documentation/context, extract the exact code snippet, "
                f"configuration, or syntax needed to resolve this knowledge gap:\n\n"
                f"Knowledge Gap: {gap}\n\n"
                f"Scraped Context:\n{scraped_content or search_result}\n\n"
                f"Instructions:\n"
                f"Provide a concise, direct snippet or answer that fully resolves the gap. "
                f"Do not include conversational filler. Focus on exact syntax, endpoints, or rules."
            )
            resolution = self.query_llm(
                prompt=dump_prompt,
                system_override="You are a technical sniper. Extract and output only the code, config, or precise information that resolves the knowledge gap. No explanation.",
                use_history=False
            )
            
            resolutions[gap] = resolution.strip()
            self.console.print(f"[bold green][Gap Solver] Successfully resolved: '{gap}'[/bold green]")
            
        # Step 4: Inject back into history
        resolutions_str = json.dumps(resolutions, indent=2)
        injection_prompt = (
            f"Here is the missing documentation and syntax resolved for your knowledge gaps:\n"
            f"```json\n{resolutions_str}\n```\n\n"
            f"Now, replace your placeholders and output the final code/implementation."
        )
        self.history.append({"role": "user", "content": injection_prompt})
        self.save_session()

    def query_llm(self, prompt: str = None, system_override: str = None, use_history: bool = False) -> str:
        if use_history:
            self.auto_summarize_history_if_needed()
            
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

        response = self.safe_chat_completion(
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
        response = self.safe_chat_completion(
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
Your task is to analyze the user's prompt and route it to either "direct", "analysis", or "planner" mode.

ROUTING CRITERIA:
1. "direct":
   - Use this for simple, deterministic, single-step commands.
   - Examples: restarting a PM2 instance, running a test/linting script, checking git status, reading/displaying a specific line range, searching for a single fact on the web, simple mathematical calculations, simple conversational greetings or queries.
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

2. "analysis":
   - Use this for purely informational requests, walkthroughs, codebase explanations, code review queries, questions about architecture or logic flow, and documentation reading.
   - These requests DO NOT require any code modifications, creating new files, or editing existing files in the workspace. They are read-only inquiries.

3. "planner":
   - Use this for complex, multi-step engineering tasks that require writing new code, modifying existing files, implementing features, refactoring, or writing documentation files in the workspace.
   - These tasks require breaking the task down into a Directed Acyclic Graph (DAG) of sub-tasks.

You MUST return a JSON object with the following fields:
{
  "route": "direct" | "analysis" | "planner",
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

    def run_cycle(self, user_input: str, verbose: bool = True, status_callback=None, authorization_callback=None):
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
                        f"[{ACCENT_CYAN}]{param_display}[/{ACCENT_CYAN}]",
                        title=f"[bold {ACCENT_YELLOW}]{ICON_BOLT} {tool_name}[/bold {ACCENT_YELLOW}]",
                        expand=False,
                        border_style=ACCENT_YELLOW,
                        box=BOX_TOOL_CALL,
                    ))
                
                try:
                    result = self._execute_tool_with_auth(tool_name, tool_param, status_callback=status_callback, authorization_callback=authorization_callback)
                except Exception as e:
                    result = f"Error executing tool: {e}"
                
                if status_callback:
                    if result.startswith("Tool execution denied"):
                        status_callback("print", f"[bold red][DENIED][/bold red] Denied {tool_name}")
                    else:
                        status_callback("print", f"[bold green][DONE][/bold green] Executed {tool_name}")
                
                if verbose:
                    res_display = result if len(result) < 500 else result[:500] + "...\n(Truncated)"
                    self.console.print(Panel(
                        f"[{ACCENT_GREEN}]{res_display}[/{ACCENT_GREEN}]",
                        title=f"[bold {ACCENT_GREEN}]{ICON_CHECK} Response[/bold {ACCENT_GREEN}]",
                        expand=False,
                        border_style=ACCENT_GREEN,
                        box=BOX_TOOL_RESPONSE,
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
        
        # 3. Handle Planner / Analysis Route / Fallback
        else:
            is_analysis = (triage_result.get("route") == "analysis")
            original_active_tools = list(self.config.get("active_tools", []))
            
            try:
                if is_analysis:
                    if status_callback:
                        status_callback("print", f"[bold blue][Triage Router] Route: Analysis Mode ({triage_result.get('explanation', '')})[/bold blue]")
                        status_callback("update", "[bold blue]Analysis Mode: Initializing read-only research loop...[/bold blue]")
                    
                    # Remove modifying tools
                    read_only_tools = [t for t in original_active_tools if t not in ["filesystem_write", "filesystem_edit", "filesystem_delete", "code_runner_with_tests"]]
                    self.config["active_tools"] = read_only_tools
                    
                    contextualized_input = f"Analysis/Research Goal: {user_input}\n\nYou are in read-only analysis/research mode. Research the codebase using read tools (like grep_search, read_file_lines, generate_repo_map) or search the web if needed, and write a clear, structured explanation. Do not write or edit any files."
                    self.history.append({"role": "user", "content": contextualized_input})
                    self.save_session()
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
                                title=f"[bold {ACCENT_BLUE}]{ICON_CLIPBOARD} Task DAG[/bold {ACCENT_BLUE}]",
                                border_style=ACCENT_BLUE,
                                box=BOX_PLAN,
                                expand=False,
                            ))
                        
                        # Parse steps and add to plan_and_todo list
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
                
                # Run the heavy agent loop
                turn = 0
                while True:
                    turn += 1
                    self.auto_summarize_history_if_needed()
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
                        status_callback("update", f"[bold blue]Thinking (turn {turn})...[/bold blue]")

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
                        
                        response = self.safe_chat_completion(**kwargs)
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

                    # Check for knowledge gaps
                    gaps = re.findall(r'__GAP::\[?([^\]\n]+)\]?__', raw_assistant_text)
                    if gaps:
                        if status_callback:
                            status_callback("print", f"[bold yellow][Gap Solver] Knowledge Gap(s) detected: {gaps}[/bold yellow]")
                        
                        history_msg = {"role": "assistant", "content": raw_assistant_text}
                        self.history.append(history_msg)
                        self.save_session()
                        
                        self.resolve_knowledge_gaps(gaps)
                        continue

                    thoughts = ""
                    think_match = re.search(r"<think>(.*?)</think>", raw_assistant_text, re.DOTALL | re.IGNORECASE)
                    if think_match:
                        thoughts = think_match.group(1).strip()
                        assistant_text = re.sub(r"<think>.*?</think>", "", raw_assistant_text, flags=re.DOTALL | re.IGNORECASE).strip()

                    if status_callback:
                        status_callback("print", f"[bold green][DONE][/bold green] Thinking (turn {turn})...")
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
                                    f"[{ACCENT_CYAN}]{param_display}[/{ACCENT_CYAN}]",
                                    title=f"[bold {ACCENT_YELLOW}]{ICON_BOLT} {tool_name}[/bold {ACCENT_YELLOW}]",
                                    expand=False,
                                    border_style=ACCENT_YELLOW,
                                    box=BOX_TOOL_CALL,
                                ))
         
                            if status_callback:
                                status_callback("update", f"[bold yellow]Executing {tool_name}...[/bold yellow]")
                            try:
                                result = self._execute_tool_with_auth(tool_name, tool_param, status_callback=status_callback, authorization_callback=authorization_callback)
                            except Exception as e:
                                result = f"Error executing tool: {e}"

                            if status_callback:
                                if result.startswith("Tool execution denied"):
                                    status_callback("print", f"[bold red][DENIED][/bold red] Denied {tool_name}")
                                else:
                                    status_callback("print", f"[bold green][DONE][/bold green] Executed {tool_name}")
                                import time
                                time.sleep(0.1)

                            if verbose:
                                res_display = result if len(result) < 500 else result[:500] + "...\n(Truncated)"
                                self.console.print(Panel(
                                    f"[{ACCENT_GREEN}]{res_display}[/{ACCENT_GREEN}]",
                                    title=f"[bold {ACCENT_GREEN}]{ICON_CHECK} Response[/bold {ACCENT_GREEN}]",
                                    expand=False,
                                    border_style=ACCENT_GREEN,
                                    box=BOX_TOOL_RESPONSE,
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
            finally:
                self.config["active_tools"] = original_active_tools
