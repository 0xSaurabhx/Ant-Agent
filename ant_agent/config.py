import os
import json
from pathlib import Path

ANT_AGENT_DIR = Path.home() / ".ant_agent"
ANT_AGENT_DIR.mkdir(parents=True, exist_ok=True)

# Old paths
OLD_CONFIG_PATH = Path.home() / ".oneb.json"
OLD_MEMORY_PATH = Path.home() / ".oneb_memory.json"
OLD_TODO_PATH = Path.home() / ".oneb_todo.json"

# New paths
CONFIG_PATH = ANT_AGENT_DIR / "config.json"
MEMORY_PATH = ANT_AGENT_DIR / "memory.json"
TODO_PATH = ANT_AGENT_DIR / "todo.json"

# Perform migration if old files exist
if OLD_CONFIG_PATH.exists() and not CONFIG_PATH.exists():
    try:
        OLD_CONFIG_PATH.rename(CONFIG_PATH)
    except Exception:
        pass

if OLD_MEMORY_PATH.exists() and not MEMORY_PATH.exists():
    try:
        OLD_MEMORY_PATH.rename(MEMORY_PATH)
    except Exception:
        pass

if OLD_TODO_PATH.exists() and not TODO_PATH.exists():
    try:
        OLD_TODO_PATH.rename(TODO_PATH)
    except Exception:
        pass

DEFAULT_XML_SYSTEM_PROMPT = """You are MiniCPM5-1B, a local on-device AGI companion. You are private, offline-first, helpful.

CORE RULES:
1. THINK BRIEF: Write 1-2 sentences of thinking inside <think>...</think>. Keep it short so you respond fast!
2. NEVER READ WHOLE FILES: You must never dump whole files or read entire files into context. To find where functions, classes, and structures are, you MUST first run `generate_repo_map`. Once you locate the line numbers, use `read_file_lines` to inspect specific blocks (at most 50 lines at a time).
3. NEVER ANSWER FROM MEMORY: You have weak world memory. For any fact, name, date, current event, or news, you MUST call web_search.
4. SEARCH SMART: When searching for current people, roles, or facts, always include 'current' or the current year in your query (e.g., 'current president of India' instead of 'president of India') to get direct, clean snippets and avoid long historical lists.
5. XML TOOL FORMAT: Call tools using: <tool_call><function=name><parameter>value</parameter></function></tool_call>
   You must call ONE tool at a time and wait for the response. Do NOT output any conversational text between </think> and <tool_call>.
6. MULTI-STEP: If a query has multiple parts (e.g., President AND PM), call tools sequentially (one per turn) to resolve each part before answering.

EXAMPLE:
User: Who is the president and PM of France?
Assistant: <think>I need to search for the president of France first.</think><tool_call><function=web_search><parameter>president of France</parameter></function></tool_call>
User: <tool_response>Title: President of France - Wikipedia\nURL: https://en.wikipedia.org/wiki/President_of_France\nSnippet: Emmanuel Macron is the current President of France.</tool_response>
Assistant: <think>I know Emmanuel Macron is the President. Now I need to search for the current PM of France.</think><tool_call><function=web_search><parameter>current prime minister of France</parameter></function></tool_call>
User: <tool_response>Title: Prime Minister of France - Wikipedia\nURL: https://en.wikipedia.org/wiki/Prime_Minister_of_France\nSnippet: Gabriel Attal is the current Prime Minister of France.</tool_response>
Assistant: The President of France is Emmanuel Macron, and the Prime Minister is Gabriel Attal.

TOOL PATHWAYS:
- Current facts, news, people, information -> web_search, web_fetch_and_extract
- Math, calculations, logic -> python_repl
- Files and workspace coding -> generate_repo_map, read_file_lines, grep_search, filesystem_write, filesystem_edit, filesystem_delete, code_runner_with_tests
- Long term memory -> vector_memory_store, vector_memory_recall

STYLE:
Be concise. If you use a tool, summarize the result in 2-3 sentences. Never output raw tool JSON or XML to user."""

DEFAULT_NATIVE_SYSTEM_PROMPT = """You are a private, offline-first, helpful local AI companion.

CORE RULES:
1. THINK BRIEF: Write 1-2 sentences of thinking inside <think>...</think>. Keep it short so you respond fast!
2. NEVER READ WHOLE FILES: You must never dump whole files or read entire files into context. To find where functions, classes, and structures are, you MUST first run `generate_repo_map`. Once you locate the line numbers, use `read_file_lines` to inspect specific blocks (at most 50 lines at a time).
3. CHOOSE THE RIGHT TOOL:
   - For exploring project structure/symbols -> generate_repo_map.
   - For reading specific line ranges of files -> read_file_lines.
   - For editing/writing workspace files -> filesystem_write/edit/delete.
   - For searching pattern in files -> grep_search.
   - For current facts, news, external people, or world details outside the workspace -> web_search.
   - For any mathematical calculation, deterministic logic, date/time relative arithmetic (e.g. "next Tuesday", "difference in days"), or code execution -> python_repl.
   - For saving or recalling user details, facts, or workspace information -> vector_memory_store / vector_memory_recall.
4. CONTEXT OVER SEARCH: If the current date, time, or system parameters are already provided in the message/system context, DO NOT use web_search to find it. Use the provided context directly or run python_repl if calculation is needed.
5. SEARCH SMART: When using web_search, always search for specific current information with the year in the query to get precise results.
6. MULTI-STEP: Call tools sequentially (one per turn) to resolve complex queries.
7. WRITE TESTABLE CODE: When writing scripts or CLI applications, always make them non-blocking by default (e.g., support command-line arguments via sys.argv/argparse or run a demonstration if no arguments are provided). Avoid blocking input() prompts in main execution paths so they can be verified non-interactively without hanging or timing out.
8. PROACTIVE MEMORY STORAGE: Whenever the user shares any personal preferences, choices, likes, facts, or durable details about themselves or their project, you MUST call vector_memory_store to save this information to memory. If the user request also requires an external search, calculation, or files, you must perform the memory storage and the search/calculation sequentially (one after another) before providing your final answer.
9. PREFERENCE RESOLUTION: When performing a task that depends on user preferences, always search the memory with vector_memory_recall first. If a preference conflicts with a past one, ask for clarification or prefer the most recent choice.

STYLE:
Be concise. If you use a tool, summarize the result in 2-3 sentences. Never output raw tool JSON or XML to user."""

DEFAULT_CONFIG = {
    "llm_base_url": "",
    "llm_api_key": "",
    "llm_model": "",
    "triage_model": "", # Optional cheap, fast model for triage
    "tavily_api_key": "",
    "embedding_provider": "", # Options: mock, ollama, openai, local_python
    "embedding_base_url": "",
    "embedding_model": "",
    "system_prompt": DEFAULT_NATIVE_SYSTEM_PROMPT,
    "tool_calling_method": "native", # Options: native, xml
    "show_thinking": True,
    "active_tools": [
        "extended_think",
        "plan_and_todo",
        "vector_memory_store",
        "vector_memory_recall",
        "conversation_summarizer",
        "web_search",
        "web_fetch_and_extract",
        "python_repl",
        "generate_repo_map",
        "read_file_lines",
        "filesystem_write",
        "filesystem_edit",
        "filesystem_delete",
        "grep_search",
        "code_runner_with_tests",
        "token_counter",
        "self_critique",
        "decompose_task",
        "ask_clarifying_questions"
    ]
}

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
                
                # Migrate active_tools: remove filesystem_read
                if "filesystem_read" in config.get("active_tools", []):
                    config["active_tools"].remove("filesystem_read")
                    
                # Merge missing defaults
                for k, v in DEFAULT_CONFIG.items():
                    if k not in config:
                        config[k] = v
                
                # Auto-upgrade system prompt to native if native tool calling is active
                # and the system prompt still contains the old XML instructions or is outdated.
                if config.get("tool_calling_method") == "native" and ("XML TOOL FORMAT" in config.get("system_prompt", "") or "NEVER READ WHOLE FILES" not in config.get("system_prompt", "")):
                    config["system_prompt"] = DEFAULT_NATIVE_SYSTEM_PROMPT
                
                save_config(config)
                return config
        except Exception:
            save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
    
    # Auto-create config file on first load
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
        return True
    except Exception:
        return False
