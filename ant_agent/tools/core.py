import json
from pathlib import Path
from ant_agent.tools import BaseTool, register_tool

@register_tool
class ExtendedThinkTool(BaseTool):
    name = "extended_think"
    description = "Chain-of-thought scratchpad. Think through complex tasks locally before responding."

    def execute(self, parameter: str) -> str:
        # Just return that reasoning was recorded.
        # This gives a scratchpad memory.
        return f"Reasoning processed successfully. Think output noted."

@register_tool
class PlanAndTodoTool(BaseTool):
    name = "plan_and_todo"
    description = "Manage tasks: 'list', 'add <task>', 'complete <index>', 'clear'."

    def _get_todo_path(self) -> Path:
        if self.context and hasattr(self.context, "get_session_todo_path"):
            return self.context.get_session_todo_path()
        p = Path.cwd() / ".ant_agent" / "sessions" / "default_todo.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def execute(self, parameter: str) -> str:
        cmd = parameter.strip()
        tasks = []
        todo_path = self._get_todo_path()
        if todo_path.exists():
            try:
                with open(todo_path, "r") as f:
                    tasks = json.load(f)
            except Exception:
                tasks = []

        if cmd.startswith("add "):
            task_desc = cmd[4:].strip()
            tasks.append({"desc": task_desc, "done": False})
            self._save(tasks)
            return f"Added task: {task_desc}"
        elif cmd.startswith("complete "):
            try:
                idx = int(cmd[9:].strip())
                if 0 <= idx < len(tasks):
                    tasks[idx]["done"] = True
                    self._save(tasks)
                    return f"Completed task: {tasks[idx]['desc']}"
                return "Index out of range."
            except ValueError:
                return "Invalid index. Use: complete <number>"
        elif cmd == "clear":
            self._save([])
            return "Cleared all tasks."
        elif cmd == "list" or not cmd:
            if not tasks:
                return "Todo list is empty."
            res = []
            for i, t in enumerate(tasks):
                status = "[x]" if t["done"] else "[ ]"
                res.append(f"{i}: {status} {t['desc']}")
            return "\n".join(res)
        else:
            return "Unknown command. Use: list, add <task>, complete <index>, clear"

    def _save(self, tasks):
        todo_path = self._get_todo_path()
        with open(todo_path, "w") as f:
            json.dump(tasks, f, indent=4)

@register_tool
class TokenCounterTool(BaseTool):
    name = "token_counter"
    description = "Counts tokens in a given text to keep context window in check."

    def execute(self, parameter: str) -> str:
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = len(encoding.encode(parameter))
        except Exception:
            # Fallback to simple estimation
            tokens = int(len(parameter.split()) * 1.3)
        return f"Token count: {tokens}"

@register_tool
class SelfCritiqueTool(BaseTool):
    name = "self_critique"
    description = "Critique proposed answer or code. Returns flaws & fixes."

    def execute(self, parameter: str) -> str:
        if not self.context or not hasattr(self.context, "query_llm"):
            return "Error: self_critique has no active LLM context. Review the code manually."
        
        prompt = f"Critique the following draft/code. Identify flaws, bugs, edge cases, and provide concrete fixes:\n\n{parameter}"
        try:
            critique = self.context.query_llm(prompt, system_override="You are an expert critic and code reviewer. Be critical, clear, and direct.")
            return critique
        except Exception as e:
            return f"Critique request failed: {e}"

@register_tool
class VectorMemoryStoreTool(BaseTool):
    name = "vector_memory_store"
    description = "Store a fact or text in memory. Param: text string OR JSON object with 'text' and optional 'scope' ('session'/'episodic', 'workspace', 'global')."

    def execute(self, parameter: str) -> str:
        if not self.context:
            return "Error: No active agent context."
        try:
            param_str = parameter.strip()
            text = param_str
            explicit_scope = None

            if param_str.startswith("{") and param_str.endswith("}"):
                try:
                    data = json.loads(param_str)
                    text = data.get("text", param_str)
                    explicit_scope = data.get("scope")
                except Exception:
                    pass

            valid_scopes = ["session", "episodic", "workspace", "global"]
            if explicit_scope and str(explicit_scope).lower() in valid_scopes:
                target_scope = str(explicit_scope).lower()
            elif hasattr(self.context, "request_memory_scope_selection"):
                target_scope = self.context.request_memory_scope_selection(text, proposed_scope=explicit_scope)
            else:
                target_scope = "session"

            if target_scope in ["session", "episodic"] and hasattr(self.context, "episodic_db"):
                self.context.episodic_db.store(text)
                return "Fact stored in session (episodic) memory."
            elif target_scope == "workspace" and hasattr(self.context, "workspace_db"):
                self.context.workspace_db.store(text)
                return "Fact stored in workspace memory."
            elif target_scope == "global" and hasattr(self.context, "global_db"):
                self.context.global_db.store(text)
                return "Fact stored in global memory."
            elif hasattr(self.context, "db"):
                self.context.db.store(text)
                return "Fact stored in memory."
            else:
                return "Error: Memory store unavailable."
        except Exception as e:
            return f"Error storing memory: {e}"

@register_tool
class VectorMemoryRecallTool(BaseTool):
    name = "vector_memory_recall"
    description = "Recall relevant facts from memory. Param: search query."

    def execute(self, parameter: str) -> str:
        if not self.context:
            return "Error: No active agent context."
        try:
            query = parameter.strip()
            all_results = []
            
            # Query Episodic / Session memory
            if hasattr(self.context, "episodic_db"):
                for r in self.context.episodic_db.recall(query, limit=3):
                    r["scope"] = "Episodic"
                    all_results.append(r)
                    
            # Query Workspace memory
            if hasattr(self.context, "workspace_db"):
                for r in self.context.workspace_db.recall(query, limit=3):
                    r["scope"] = "Workspace"
                    all_results.append(r)
                    
            # Query Global memory
            if hasattr(self.context, "global_db"):
                for r in self.context.global_db.recall(query, limit=3):
                    r["scope"] = "Global"
                    all_results.append(r)
            
            if not all_results and hasattr(self.context, "db"):
                for r in self.context.db.recall(query, limit=3):
                    r["scope"] = "Default"
                    all_results.append(r)
                    
            if not all_results:
                return "No relevant memories found."
            
            # Sort by score descending (higher score is better)
            all_results.sort(key=lambda x: x["score"], reverse=True)
            
            # Deduplicate and limit to top 5
            seen = set()
            unique_results = []
            for r in all_results:
                if r["text"] not in seen:
                    seen.add(r["text"])
                    unique_results.append(r)
                    if len(unique_results) >= 5:
                        break
            
            out = []
            for r in unique_results:
                scope = r.get("scope", "Memory")
                out.append(f"- [{scope}] {r['text']} (stored: {r['timestamp']})")
            return "\n".join(out)
        except Exception as e:
            return f"Error recalling memory: {e}"

@register_tool
class ConversationSummarizerTool(BaseTool):
    name = "conversation_summarizer"
    description = "Summarize the chat history. Param: none."

    def execute(self, parameter: str) -> str:
        if not self.context or not hasattr(self.context, "history"):
            return "Error: No history context."
        if not self.context.history:
            return "Conversation history is empty."
            
        history_text = ""
        for msg in self.context.history:
            history_text += f"{msg['role']}: {msg['content']}\n"
            
        prompt = f"Summarize the following chat history to compress it, listing key points and any open questions/loops:\n\n{history_text}"
        try:
            summary = self.context.query_llm(prompt, system_override="You are a helpful assistant that summarizes conversations concisely.")
            return summary
        except Exception as e:
            return f"Summarization failed: {e}"

@register_tool
class DecomposeTaskTool(BaseTool):
    name = "decompose_task"
    description = "Decompose a complex goal into a detailed, step-by-step checklist / DAG of subtasks. Param: complex goal."

    def execute(self, parameter: str) -> str:
        if not self.context or not hasattr(self.context, "query_llm"):
            return "Error: decompose_task has no active LLM context."
        
        prompt = f"Decompose the following complex goal into a detailed, step-by-step checklist / DAG of subtasks with clear dependencies:\n\n{parameter}"
        try:
            decomposition = self.context.query_llm(prompt, system_override="You are a principal task planner. Break down the user's goal into logical, linear, actionable steps.")
            return decomposition
        except Exception as e:
            return f"Decomposition failed: {e}"

@register_tool
class AskClarifyingQuestionsTool(BaseTool):
    name = "ask_clarifying_questions"
    description = "Forces asking a clarifying question when intent is ambiguous or context is missing. Param: the question to ask."

    def execute(self, parameter: str) -> str:
        return f"Clarification question logged: '{parameter}'. Ask the user this question directly now and stop requesting tools until they respond."

