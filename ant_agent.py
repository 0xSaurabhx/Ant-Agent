#!/usr/bin/env python3
import sys
import json
import os
from datetime import datetime
import argparse
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PromptStyle

from pathlib import Path
from ant_agent.config import load_config, save_config
from ant_agent.agent import AntAgent
from ant_agent.tui_theme import (
    BANNER, THIN_RULE, get_banner, get_rule,
    ICON_ANT, ICON_BOLT, ICON_BRAIN, ICON_CLIPBOARD, ICON_CHECK,
    ICON_GEAR, ICON_SEARCH, ICON_CHART, ICON_PLUG, ICON_WAVE,
    ICON_KEY, ICON_CLOCK, ICON_WARN, ICON_ROCKET, ICON_FOLDER,
    ICON_TRASH, ICON_CLEAR, ICON_LIST, ICON_EYE, ICON_EXIT, ICON_HELP,
    ICON_ARROW,
    BOX_TOOL_CALL, BOX_TOOL_RESPONSE, BOX_THINKING, BOX_PLAN, BOX_WELCOME,
    ACCENT_CYAN, ACCENT_GREEN, ACCENT_YELLOW, ACCENT_MAGENTA,
    ACCENT_DIM, ACCENT_BLUE, ACCENT_RED,
)

# ─── Helper: Compact size formatter ──────────────────────────────
def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)

# ─── Welcome Banner ──────────────────────────────────────────────
def print_welcome(console, config, agent):
    console.print(get_banner(console.width))
    console.print(THIN_RULE)

    # Info grid — compact key-value pairs
    info_items = [
        f"[{ACCENT_DIM}]Model:[/{ACCENT_DIM}]  [{ACCENT_CYAN}]{config['llm_model']}[/{ACCENT_CYAN}]",
        f"[{ACCENT_DIM}]Server:[/{ACCENT_DIM}] [{ACCENT_DIM}]{config['llm_base_url']}[/{ACCENT_DIM}]",
        f"[{ACCENT_DIM}]Session:[/{ACCENT_DIM}][{ACCENT_MAGENTA}] {agent.session_id[:16]}…[/{ACCENT_MAGENTA}]",
        f"[{ACCENT_DIM}]Tools:[/{ACCENT_DIM}]  [{ACCENT_GREEN}]{len(config.get('active_tools', []))} active[/{ACCENT_GREEN}] [{ACCENT_DIM}]│[/{ACCENT_DIM}] [{ACCENT_DIM}]Context:[/{ACCENT_DIM}] [{ACCENT_GREEN}]{_fmt_tokens(config.get('max_context_tokens', 8192))} tokens[/{ACCENT_GREEN}]",
    ]
    for line in info_items:
        console.print(f"  {line}")

    console.print(THIN_RULE)
    console.print(f"  [{ACCENT_DIM}]Type[/{ACCENT_DIM}] [{ACCENT_MAGENTA}]/help[/{ACCENT_MAGENTA}] [{ACCENT_DIM}]for commands[/{ACCENT_DIM}] [{ACCENT_DIM}]•[/{ACCENT_DIM}] [{ACCENT_MAGENTA}]/exit[/{ACCENT_MAGENTA}] [{ACCENT_DIM}]to quit[/{ACCENT_DIM}]")
    console.print()

# ─── Help Table ──────────────────────────────────────────────────
def print_help(console):
    table = Table(
        title=f"{ICON_HELP} Commands",
        show_header=True,
        header_style=f"bold {ACCENT_MAGENTA}",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
        title_style=f"bold {ACCENT_CYAN}",
    )
    table.add_column("Command", style=f"bold {ACCENT_CYAN}", no_wrap=True)
    table.add_column("Description", style="white", overflow="fold")
    commands = [
        ("/help",     f"{ICON_HELP}  Show this command reference"),
        ("/tools",    f"{ICON_PLUG}  List active tools and descriptions"),
        ("/config",   f"{ICON_GEAR}  Show current settings"),
        ("/thinking", f"{ICON_EYE}  Toggle thinking process display"),
        ("/stats",    f"{ICON_CHART}  Token usage & session cost"),
        ("/wipe",     f"{ICON_TRASH}  Delete all saved sessions"),
        ("/clear",    f"{ICON_CLEAR}  Clear current chat history"),
        ("/history",  f"{ICON_LIST}  List saved chat sessions"),
        ("/exit",     f"{ICON_EXIT}  Exit the session"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    console.print(table)

# ─── History Replay ──────────────────────────────────────────────
def print_history(console, history):
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            if not content.startswith("<tool_response>"):
                console.print(f"[bold {ACCENT_GREEN}]{ICON_ANT} User {ICON_ARROW}[/bold {ACCENT_GREEN}] {content}")
        elif role == "assistant":
            if content:
                console.print(f"\n[bold {ACCENT_CYAN}]{ICON_ANT} Agent {ICON_ARROW}[/bold {ACCENT_CYAN}]")
                console.print(Markdown(content))
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn_name = tc.get("function", {}).get("name", "")
                    console.print(f"  [{ACCENT_YELLOW}]{ICON_BOLT} {fn_name}[/{ACCENT_YELLOW}]")
        elif role == "tool":
            console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK} Done[/{ACCENT_GREEN}] [{ACCENT_DIM}]{msg.get('name')}[/{ACCENT_DIM}]")

# ─── Stats Display ───────────────────────────────────────────────
def print_stats(console, agent, show_global=True):
    prompt_tokens = agent.session_prompt_tokens
    completion_tokens = agent.session_completion_tokens
    total_tokens = prompt_tokens + completion_tokens

    # Session stats
    table = Table(
        title=f"{ICON_CHART} Session Token Usage",
        show_header=True,
        header_style=f"bold {ACCENT_GREEN}",
        box=box.ROUNDED,
        padding=(0, 1),
        title_style=f"bold {ACCENT_CYAN}",
    )
    table.add_column("Metric", style=f"{ACCENT_CYAN}", no_wrap=True)
    table.add_column("Value", style="white", justify="right")
    table.add_row(f"{ICON_ROCKET} Model", agent.config.get("llm_model", "Unknown"))
    table.add_row(f"{ICON_ARROW} Input Tokens", f"{prompt_tokens:,}")
    table.add_row(f"{ICON_ARROW} Output Tokens", f"{completion_tokens:,}")
    table.add_row(f"[bold]Total[/bold]", f"[bold]{total_tokens:,}[/bold]")
    console.print(table)

    if show_global:
        from ant_agent.config import STATS_PATH
        if STATS_PATH.exists():
            try:
                with open(STATS_PATH, "r") as f:
                    stats = json.load(f)
            except Exception:
                stats = {}

            models = stats.get("models", {})
            if models:
                g_table = Table(
                    title=f"{ICON_CHART} Lifetime Token Consumption",
                    show_header=True,
                    header_style=f"bold {ACCENT_MAGENTA}",
                    box=box.ROUNDED,
                    padding=(0, 1),
                    title_style=f"bold {ACCENT_CYAN}",
                )
                g_table.add_column("Model", style=f"{ACCENT_CYAN}", no_wrap=True)
                g_table.add_column("Input", style="white", justify="right")
                g_table.add_column("Output", style="white", justify="right")
                g_table.add_column("Total", style="white", justify="right")

                for model_name, m_stats in sorted(models.items()):
                    g_table.add_row(
                        model_name,
                        f"{m_stats.get('prompt_tokens', 0):,}",
                        f"{m_stats.get('completion_tokens', 0):,}",
                        f"{m_stats.get('total_tokens', 0):,}",
                    )
                g_table.add_row(
                    f"[bold {ACCENT_YELLOW}]Total Lifetime[/bold {ACCENT_YELLOW}]",
                    f"{stats.get('total_prompt_tokens', 0):,}",
                    f"{stats.get('total_completion_tokens', 0):,}",
                    f"{stats.get('total_total_tokens', 0):,}",
                    style="bold",
                )
                console.print()
                console.print(g_table)

# ─── Session History List ────────────────────────────────────────
def print_history_list(console):
    sessions_dir = Path.cwd() / ".ant_agent" / "sessions"
    if not sessions_dir.exists() or not list(sessions_dir.glob("*.json")):
        console.print(f"  [{ACCENT_YELLOW}]{ICON_WARN} No saved chat sessions found.[/{ACCENT_YELLOW}]")
        return

    table = Table(
        title=f"{ICON_LIST} Saved Sessions",
        show_header=True,
        header_style=f"bold {ACCENT_CYAN}",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
        title_style=f"bold {ACCENT_CYAN}",
    )
    table.add_column("Session UUID", style=f"{ACCENT_CYAN}", overflow="ellipsis")
    table.add_column("Last Active", style=f"{ACCENT_MAGENTA}", overflow="fold")
    table.add_column("Messages", style=f"{ACCENT_GREEN}", justify="right")

    for p in sorted(sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(p, "r") as f:
                data = json.load(f)
                uuid_str = data.get("uuid", p.stem)
                history = data.get("history", [])
                timestamp = data.get("timestamp", datetime.fromtimestamp(p.stat().st_mtime).isoformat())
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    time_str = timestamp
                table.add_row(uuid_str, time_str, str(len(history)))
        except Exception:
            pass
    console.print(table)

# ─── Goodbye Screen ──────────────────────────────────────────────
def print_goodbye(console, agent):
    print_stats(console, agent, show_global=False)
    console.print(f"\n  [{ACCENT_CYAN}]{ICON_WAVE} Goodbye![/{ACCENT_CYAN}]\n")

# ─── Main Chat Loop ──────────────────────────────────────────────
def cmd_chat(args):
    console = Console()
    config = load_config()

    session_id = getattr(args, "session_id", None)
    agent = AntAgent(config, session_id=session_id)

    print_welcome(console, config, agent)

    # Replay history when resuming
    if session_id and agent.history:
        print_history(console, agent.history)

    completer = WordCompleter(
        ['/exit', '/quit', '/clear', '/help', '/config', '/tools', '/thinking', '/stats', '/wipe', '/history'],
        ignore_case=True,
    )
    prompt_style = PromptStyle.from_dict({
        'prompt': 'ansigreen bold',
    })
    session = PromptSession(completer=completer, style=prompt_style)

    while True:
        try:
            user_input = session.prompt(f"{ICON_ANT} > ")
            user_input = user_input.strip()
            if not user_input:
                continue

            # ── Slash Commands ─────────────────────────────────
            if user_input in ("/exit", "/quit"):
                print_goodbye(console, agent)
                break

            if user_input == "/clear":
                agent.clear_session()
                console.clear()
                console.print(f"  [{ACCENT_YELLOW}]{ICON_CLEAR} Chat history and screen cleared.[/{ACCENT_YELLOW}]")
                continue

            if user_input == "/wipe":
                agent.wipe_all_sessions()
                console.print(f"  [{ACCENT_YELLOW}]{ICON_TRASH} All saved sessions wiped.[/{ACCENT_YELLOW}]")
                continue

            if user_input == "/help":
                print_help(console)
                continue

            if user_input == "/history":
                print_history_list(console)
                continue

            if user_input == "/tools":
                table = Table(
                    title=f"{ICON_PLUG} Active Tools",
                    show_header=True,
                    header_style=f"bold {ACCENT_YELLOW}",
                    box=box.SIMPLE_HEAVY,
                    padding=(0, 1),
                    title_style=f"bold {ACCENT_CYAN}",
                )
                table.add_column("Tool", style=f"bold {ACCENT_CYAN}", no_wrap=True)
                table.add_column("Description", style="white", overflow="fold")
                table.add_column("Authorization", style="bold yellow", no_wrap=True)
                for tname in config.get("active_tools", []):
                    requires_auth = agent.is_authorization_required(tname)
                    auth_str = f"[{ACCENT_YELLOW}]Required[/{ACCENT_YELLOW}]" if requires_auth else f"[{ACCENT_DIM}]Auto[/{ACCENT_DIM}]"
                    try:
                        import ant_agent.tools as tools_mod
                        t_inst = tools_mod.get_tool(tname, agent)
                        table.add_row(tname, t_inst.description, auth_str)
                    except Exception:
                        table.add_row(tname, f"[{ACCENT_RED}]Failed to load[/{ACCENT_RED}]", auth_str)
                console.print(table)
                continue

            if user_input == "/thinking":
                config["show_thinking"] = not config.get("show_thinking", True)
                save_config(config)
                state = f"[{ACCENT_GREEN}]ON[/{ACCENT_GREEN}]" if config["show_thinking"] else f"[{ACCENT_RED}]OFF[/{ACCENT_RED}]"
                console.print(f"  [{ACCENT_YELLOW}]{ICON_EYE} Thinking display: {state}[/{ACCENT_YELLOW}]")
                continue

            if user_input == "/stats":
                print_stats(console, agent)
                continue

            if user_input == "/config":
                table = Table(
                    title=f"{ICON_GEAR} Configuration",
                    show_header=True,
                    header_style=f"bold {ACCENT_GREEN}",
                    box=box.ROUNDED,
                    padding=(0, 1),
                    title_style=f"bold {ACCENT_CYAN}",
                )
                table.add_column("Key", style=f"{ACCENT_CYAN}", no_wrap=True)
                table.add_column("Value", style="white", overflow="fold")
                for k, v in config.items():
                    display_v = str(v)
                    if k == "system_prompt":
                        display_v = display_v.splitlines()[0] + "..." if display_v else ""
                    if k in ("llm_api_key",) and display_v:
                        display_v = display_v[:8] + "••••••••"
                    table.add_row(k, display_v)
                console.print(table)
                continue

            # ── Agent Execution ────────────────────────────────
            with console.status(f"[bold {ACCENT_BLUE}]{ICON_BRAIN} Thinking...[/bold {ACCENT_BLUE}]", spinner="dots") as status:
                def status_callback(action, msg):
                    if action == "update":
                        status.start()
                        status.update(msg)
                    elif action == "print":
                        status.stop()
                        # Restyle triage router lines
                        if isinstance(msg, str):
                            if "[Triage Router]" in msg:
                                # Determine icon based on route
                                if "Analysis" in msg:
                                    icon = ICON_SEARCH
                                elif "Planner" in msg or "Continuing" in msg:
                                    icon = ICON_CLIPBOARD
                                elif "Direct" in msg:
                                    icon = ICON_BOLT
                                else:
                                    icon = ICON_ARROW
                                console.print(f"  [{ACCENT_MAGENTA}]{icon} {msg}[/{ACCENT_MAGENTA}]")
                            elif "[DONE]" in msg:
                                console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK}[/{ACCENT_GREEN}] {msg}")
                            elif "[Gap Solver]" in msg:
                                console.print(f"  [{ACCENT_YELLOW}]{ICON_SEARCH} {msg}[/{ACCENT_YELLOW}]")
                            elif "[*]" in msg:
                                console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK}[/{ACCENT_GREEN}] {msg}")
                            else:
                                console.print(msg)
                        else:
                            # Panels (e.g. DAG decomposition)
                            console.print(msg)
                    elif action == "thought":
                        if config.get("show_thinking", True):
                            console.print(Panel(
                                Text(msg, style="italic dim", overflow="fold"),
                                title=f"[{ACCENT_DIM}]{ICON_BRAIN} Thinking[/{ACCENT_DIM}]",
                                border_style=ACCENT_BLUE,
                                box=BOX_THINKING,
                                expand=False,
                            ))
                response = agent.run_cycle(user_input, verbose=args.verbose, status_callback=status_callback)

            # ── Agent Response ─────────────────────────────────
            console.print()
            console.print(f"[bold {ACCENT_CYAN}]{ICON_ANT} Agent {ICON_ARROW}[/bold {ACCENT_CYAN}]")
            console.print(Markdown(response))
            console.print()

        except KeyboardInterrupt:
            print_goodbye(console, agent)
            break
        except Exception as e:
            console.print(f"\n  [{ACCENT_RED}]{ICON_WARN} Error: {e}[/{ACCENT_RED}]\n")

# ─── Config Command ──────────────────────────────────────────────
def cmd_config(args):
    console = Console()
    config = load_config()
    if args.action == "show":
        table = Table(
            title=f"{ICON_GEAR} Configuration",
            show_header=True,
            header_style=f"bold {ACCENT_CYAN}",
            box=box.ROUNDED,
            padding=(0, 1),
        )
        table.add_column("Setting", style=f"{ACCENT_CYAN}", no_wrap=True)
        table.add_column("Value", style="white", overflow="fold")
        for k, v in config.items():
            display_v = str(v)
            if k == "system_prompt":
                prompt_lines = display_v.splitlines()
                display_v = "\n".join(prompt_lines[:3]) + "\n..." if len(prompt_lines) > 3 else display_v
            if k in ("llm_api_key",) and display_v:
                display_v = display_v[:8] + "••••••••"
            table.add_row(k, display_v)
        console.print(table)
    elif args.action == "set":
        key = args.key
        value = args.value
        if key not in config:
            console.print(f"  [{ACCENT_YELLOW}]{ICON_WARN} {key} is not a standard key, adding it.[/{ACCENT_YELLOW}]")
        if key in ("active_tools", "authorization_required_tools", "authorization_required"):
            value = [t.strip() for t in value.split(",") if t.strip()]
        config[key] = value
        if save_config(config):
            console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK} Updated: {key} = {value}[/{ACCENT_GREEN}]")
        else:
            console.print(f"  [{ACCENT_RED}]{ICON_WARN} Failed to save configuration.[/{ACCENT_RED}]")

# ─── Resume Command ──────────────────────────────────────────────
def cmd_resume(args):
    console = Console()
    if args.session_id:
        cmd_chat(args)
        return
    print_history_list(console)
    console.print(f"\n  [{ACCENT_DIM}]To resume:[/{ACCENT_DIM}] [{ACCENT_GREEN}]python ant_agent.py resume <session-uuid>[/{ACCENT_GREEN}]\n")

# ─── Memory Command ──────────────────────────────────────────────
def cmd_memory(args):
    console = Console()
    config = load_config()
    agent = AntAgent(config)

    if args.action == "add":
        text = " ".join(args.text)
        scope = getattr(args, "scope", None)
        if scope:
            target_scope = scope
        else:
            target_scope = agent.request_memory_scope_selection(text)

        if target_scope in ["session", "episodic"]:
            agent.episodic_db.store(text)
            console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK} Stored in Session (Episodic) Memory: '{text}'[/{ACCENT_GREEN}]")
        elif target_scope == "workspace":
            agent.workspace_db.store(text)
            console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK} Stored in Workspace Memory: '{text}'[/{ACCENT_GREEN}]")
        elif target_scope == "global":
            agent.global_db.store(text)
            console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK} Stored in Global Memory: '{text}'[/{ACCENT_GREEN}]")
        else:
            agent.db.store(text)
            console.print(f"  [{ACCENT_GREEN}]{ICON_CHECK} Stored in Memory: '{text}'[/{ACCENT_GREEN}]")
    elif args.action == "query":
        query = " ".join(args.text)
        all_results = []
        for r in agent.episodic_db.recall(query, limit=args.limit):
            r["scope"] = "Episodic"
            all_results.append(r)
        for r in agent.workspace_db.recall(query, limit=args.limit):
            r["scope"] = "Workspace"
            all_results.append(r)
        for r in agent.global_db.recall(query, limit=args.limit):
            r["scope"] = "Global"
            all_results.append(r)

        all_results.sort(key=lambda x: x["score"], reverse=True)
        seen = set()
        unique_results = []
        for r in all_results:
            if r["text"] not in seen:
                seen.add(r["text"])
                unique_results.append(r)
                if len(unique_results) >= args.limit:
                    break

        table = Table(
            title=f"{ICON_SEARCH} Memory Results for '{query}'",
            show_header=True,
            header_style=f"bold {ACCENT_CYAN}",
            box=box.ROUNDED,
            padding=(0, 1),
        )
        table.add_column("#", style=f"{ACCENT_YELLOW}", no_wrap=True)
        table.add_column("Scope", style=f"{ACCENT_MAGENTA}", no_wrap=True)
        table.add_column("Score", style=f"{ACCENT_MAGENTA}", justify="right")
        table.add_column("Content", style="white", overflow="fold")
        table.add_column("Timestamp", style=f"{ACCENT_DIM}", overflow="fold")
        for i, res in enumerate(unique_results, 1):
            table.add_row(str(i), res.get("scope", "Memory"), f"{res['score']:.4f}", res['text'], str(res['timestamp']))
        console.print(table)

# ─── Stats Command ───────────────────────────────────────────────
def cmd_stats(args):
    console = Console()
    config = load_config()
    agent = AntAgent(config)
    print_stats(console, agent, show_global=True)

# ─── Main ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Ant Agent CLI AI Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Chat
    chat_parser = subparsers.add_parser("chat", help="Start interactive agent chat session")
    chat_parser.add_argument("--verbose", action="store_true", default=True, help="Display tool calls step-by-step")
    chat_parser.add_argument("--no-verbose", dest="verbose", action="store_false", help="Hide tool calling steps")

    # Resume
    resume_parser = subparsers.add_parser("resume", help="Resume a saved chat session")
    resume_parser.add_argument("session_id", nargs="?", default=None, help="Session UUID to resume")
    resume_parser.add_argument("--verbose", action="store_true", default=True, help="Display tool calls step-by-step")
    resume_parser.add_argument("--no-verbose", dest="verbose", action="store_false", help="Hide tool calling steps")

    # Config
    config_parser = subparsers.add_parser("config", help="Manage settings")
    config_subparsers = config_parser.add_subparsers(dest="action", required=True)
    config_subparsers.add_parser("show", help="Display active settings")
    set_parser = config_subparsers.add_parser("set", help="Modify a setting")
    set_parser.add_argument("key", help="Configuration key (e.g. llm_base_url)")
    set_parser.add_argument("value", help="Configuration value")

    # Memory
    memory_parser = subparsers.add_parser("memory", help="Manage agent memory store")
    memory_subparsers = memory_parser.add_subparsers(dest="action", required=True)
    add_parser = memory_subparsers.add_parser("add", help="Add new memory text block")
    add_parser.add_argument("text", nargs="+", help="Memory content to store")
    add_parser.add_argument("--scope", choices=["session", "episodic", "workspace", "global"], help="Memory storage target scope")
    query_parser = memory_subparsers.add_parser("query", help="Search the memory store")
    query_parser.add_argument("text", nargs="+", help="Search query string")
    query_parser.add_argument("--limit", type=int, default=5, help="Number of records to show")

    # Stats
    stats_parser = subparsers.add_parser("stats", help="Display global lifetime token stats")

    args = parser.parse_args()

    if args.command == "chat":
        cmd_chat(args)
    elif args.command == "resume":
        cmd_resume(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "memory":
        cmd_memory(args)
    elif args.command == "stats":
        cmd_stats(args)

if __name__ == "__main__":
    main()
