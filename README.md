# <p align="center"><img src="assets/logo.png" width="180" alt="Ant Agent Logo"/><br>Ant Agent</p>

<p align="center">
  <strong>A private, offline-first local AI pair programmer & personal assistant CLI.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python Version"/>
  <img src="https://img.shields.io/badge/status-ready-success.svg" alt="Project Status"/>
  <img src="https://img.shields.io/badge/offline-first-green.svg" alt="Offline First"/>
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License"/>
</p>

---

**Ant Agent** is an advanced developer companion designed to run locally. Built on the philosophy that **small models (e.g., 1B to 30B parameters) shouldn't try to memorize the world—they should call the right tools**, Ant Agent acts as the ultimate local orchestrator. It bridges the reasoning gap by combining a small local model with persistent memory, computation engines, and filesystem controls.

---

## 🚀 Key Features

* **⚡ Intelligent Triage Routing (Dual-Route Execution)**:
  * On every request, a fast Triage Router analyzes the user's intent.
  * **Direct Route**: Instantly bypasses heavy planning and runs simple, single-step tasks (e.g., math calculations, test scripts, single file searches) using the appropriate tool.
  * **Planner Route**: Decomposes complex, multi-step engineering tasks (e.g., building APIs, debugging codebases, refactoring files) into a Directed Acyclic Graph (DAG) checklist.
* **📋 Task Decomposition & Tracking**:
  * Automatically breaks down complex goals into a linear subtask checklist using `decompose_task`.
  * Integrates with `plan_and_todo` to persist, execute, and check off completed subtasks.
  * Recognizes user continuation prompts (e.g., "continue", "next", "proceed") to smoothly advance through the plan without redundant planning overhead.
* **🔍 Developer-First Code Navigation**:
  * **Repository Mapping (`generate_repo_map`)**: Dynamically parses the codebase using AST (Python) or regex (Go, JS, Rust, C) to extract class/function locations and line numbers.
  * **Targeted Line Reading (`read_file_lines`)**: Limits file reads to specific line ranges (up to 50 lines at a time) to prevent context bloat and token waste.
  * **Deep Grep Search (`grep_search`)**: Quickly searches text patterns in workspace files while ignoring build artifacts and virtual environments.
* **🧠 Segregated Hybrid Memory System**:
  * Routes factual context intelligently between **Global Memory** (`~/.ant_agent/memory.json`) and **Workspace Memory** (`.ant_agent/memory.json`).
  * Persists preferences, likes, and project configurations using a local vector store.
* **✂️ Smart Context Optimization**:
  * Automatically compresses and truncates older message histories and verbose tool outputs to fit within small local model contexts (4k-8k windows) while preserving necessary context.
  * Measures active token budgets using `token_counter`.
* **🛠️ Powerful Local Tool Suit**:
  * **Code Execution**: Run sandboxed Python code with `python_repl` for math, analysis, and logic.
  * **Command Runner**: Run tests, formats, and scripts using `code_runner_with_tests`.
  * **Web Scraping**: Web search (`web_search`) via Tavily with a zero-config fallback to DuckDuckGo HTML search, and URL content scraping (`web_fetch_and_extract`) via Trafilatura.
* **💬 Dual Tool-Calling Protocols**:
  * Fully compatible with standard OpenAI native function calling.
  * Supports XML tag-based tool calling (`<tool_call><function=name><parameter>value</parameter></function></tool_call>`), making it extremely robust when running smaller local models like MiniCPM5-1B.
* **💻 Immersive Terminal UI (TUI)**: Powered by `rich` and `prompt_toolkit`. Features animated console states, syntax-highlighted outputs, and command autocompletion.

---

## 📦 Installation & Setup

1. **Clone & Navigate**:
   ```bash
   cd Path/to/ant-agent
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Settings**:
   The configuration file is automatically created in `~/.ant_agent/config.json` upon first startup. Update it with your preferred model configuration:
   ```json
   {
       "llm_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
       "llm_api_key": "YOUR_API_KEY",
       "llm_model": "gemma-4-26b-a4b-it",
       "embedding_provider": "local_python", // Options: mock, ollama, openai, local_python
       "tool_calling_method": "native" // Options: native, xml
   }
   ```

---

## ⚡ Usage

### Start Interactive Chat
```bash
python ant_agent.py chat [--verbose / --no-verbose]
```
*Use `--no-verbose` to hide tool call execution blocks in the console.*

### Resume Saved Sessions
List all saved sessions in this workspace:
```bash
python ant_agent.py resume
```
Resume a specific session:
```bash
python ant_agent.py resume <session-uuid>
```

### Direct Configuration Management
View active configurations:
```bash
python ant_agent.py config show
```
Modify a setting key:
```bash
python ant_agent.py config set <key> <value>
```

### Direct Memory Management
Add a fact to memory:
```bash
python ant_agent.py memory add "I prefer dark mode in UI designs"
```
Search memory records:
```bash
python ant_agent.py memory query "UI preference"
```

### Interactive Chat Slash Commands
While in a chat session, you can use these shortcuts:
* `/help` - Show available slash commands.
* `/tools` - List all active tool schemas.
* `/config` - Show active configuration settings.
* `/thinking` - Toggle the visibility of the agent's thought process scratchpad.
* `/stats` - Print session token utilization and cost metrics.
* `/clear` - Reset current conversation history in memory and clear the screen.
* `/wipe` - Wipe all saved session histories in this workspace.
* `/exit` or `/quit` - Safely exit chat session and display utilization summary.

---

## 🧪 Development & Testing

Unit tests are isolated using a temporary directory sandbox to avoid corrupting active user workspace data:
```bash
python -m unittest test_ant_agent.py
```

---

## 🗺️ Roadmap & Checklist

### Completed Features
- [x] **Intelligent Triage Routing**: Dual routing based on intent (direct single-step vs planner multi-step).
- [x] **Task Decomposition**: Automatic DAG-based task checklist generation and tracking.
- [x] **Targeted Code Navigation**: AST/Regex repo mapping and selective line reading.
- [x] **Hybrid Memory Routing**: Global memory vs Workspace memory split.
- [x] **Context Optimization**: Automatic token-safe context compression and message truncation.
- [x] **Zero-Config Search Fallback**: Seamless fallback to DuckDuckGo HTML search if Tavily API is missing.
- [x] **XML + Native Tooling**: Support for native tool schemas as well as XML tags.

### Yet to Do
- [ ] **Improved stats on cost and token consumption**: Support precise tracking for a wider range of model APIs and local providers.
- [ ] **Improved long-term memory**: Integrate semantic reranking and smarter context truncation for vector embeddings.
- [ ] **Improved TUI**: Add interactive menus, scrollable panels, and enhanced theme configuration.
- [ ] **Multimodal inputs**: Integrate vision capabilities to analyze screenshots and local image/PDF files.
- [ ] **Pip package of Ant Agent**: Package and distribute Ant Agent on PyPI for easy installation.
- [ ] **Agent Orchestration**: Support auto-deployment of sub-agents to distribute heavy workloads and finish tasks faster.
