#!/usr/bin/env python3
import sys
import json
from datetime import datetime
import argparse
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PromptStyle

from pathlib import Path
from ant_agent.config import load_config, save_config
from ant_agent.agent import AntAgent

def print_help(console):
    table = Table(title="Available Slash Commands", show_header=True, header_style="bold magenta")
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    table.add_row("/help", "Show this help table")
    table.add_row("/tools", "List all active tools and their descriptions")
    table.add_row("/config", "Show the active settings configuration")
    table.add_row("/thinking", "Toggle display of the agent's thinking process")
    table.add_row("/stats", "Show token utilization and estimated session cost")
    table.add_row("/wipe", "Delete all saved persistent conversations in this workspace")
    table.add_row("/clear", "Clear the current chat history")
    table.add_row("/history", "List all saved chat sessions in this workspace")
    table.add_row("/exit", "Exit the chat session")
    table.add_row("/quit", "Exit the chat session")
    console.print(table)

def print_history(console, history):
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        
        if role == "user":
            if not content.startswith("<tool_response>"):
                console.print(f"[bold green]User >[/bold green] {content}")
        elif role == "assistant":
            if content:
                console.print(f"\n[bold cyan]Agent >[/bold cyan]")
                console.print(Markdown(content))
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn_name = tc.get("function", {}).get("name", "")
                    console.print(f"[bold yellow]Tool Call: {fn_name}[/bold yellow]")
        elif role == "tool":
            console.print(f"[bold green][DONE][/bold green] Executed {msg.get('name')}")

def print_stats(console, agent, show_global=True):
    prompt_tokens = agent.session_prompt_tokens
    completion_tokens = agent.session_completion_tokens
    total_tokens = prompt_tokens + completion_tokens
    
    table = Table(title="Current Session Token Utilization", show_header=True, header_style="bold green")
    table.add_column("Metric", style="cyan")
    table.add_column("Count / Value", style="white")
    table.add_row("Active Model", agent.config.get("llm_model", "Unknown"))
    table.add_row("Input (Prompt) Tokens", f"{prompt_tokens:,}")
    table.add_row("Output (Completion) Tokens", f"{completion_tokens:,}")
    table.add_row("Total Session Tokens", f"{total_tokens:,}")
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
                global_table = Table(title="Global Lifetime Token Consumption", show_header=True, header_style="bold magenta")
                global_table.add_column("Model Name", style="cyan")
                global_table.add_column("Input (Prompt) Tokens", style="white")
                global_table.add_column("Output (Completion) Tokens", style="white")
                global_table.add_column("Total Tokens", style="white")
                
                for model_name, m_stats in sorted(models.items()):
                    global_table.add_row(
                        model_name,
                        f"{m_stats.get('prompt_tokens', 0):,}",
                        f"{m_stats.get('completion_tokens', 0):,}",
                        f"{m_stats.get('total_tokens', 0):,}"
                    )
                
                # Add total row
                global_table.add_row(
                    "[bold yellow]Total Lifetime[/bold yellow]",
                    f"{stats.get('total_prompt_tokens', 0):,}",
                    f"{stats.get('total_completion_tokens', 0):,}",
                    f"{stats.get('total_total_tokens', 0):,}",
                    style="bold"
                )
                console.print()
                console.print(global_table)

def cmd_chat(args):
    console = Console()
    config = load_config()
    
    session_id = getattr(args, "session_id", None)
    agent = AntAgent(config, session_id=session_id)
    
    console.print(Panel.fit(
        f"[bold cyan]Ant Agent: Local AI CLI Agent [/bold cyan]\n"
        f"[dim]LLM Server: {config['llm_base_url']}[/dim]\n"
        f"[dim]LLM Model:  {config['llm_model']}[/dim]\n"
        f"[dim]Session ID: {agent.session_id}[/dim]\n\n"
        f"Type [bold magenta]/help[/bold magenta] to list commands. Type [bold magenta]/exit[/bold magenta] to quit.",
        title="[bold white]Welcome[/bold white]",
        border_style="cyan"
    ))

    # Print history if resuming an existing session
    if session_id and agent.history:
        print_history(console, agent.history)

    completer = WordCompleter([
        '/exit', '/quit', '/clear', '/help', '/config', '/tools', '/thinking', '/stats', '/wipe', '/history'
    ], ignore_case=True)
    
    prompt_style = PromptStyle.from_dict({
        'prompt': 'ansigreen bold',
    })
    session = PromptSession(completer=completer, style=prompt_style)

    while True:
        try:
            user_input = session.prompt("User > ")
            user_input = user_input.strip()
            if not user_input:
                continue
            
            if user_input in ("/exit", "/quit"):
                print_stats(console, agent)
                console.print("[cyan]Goodbye![/cyan]")
                break
                
            if user_input == "/clear":
                agent.clear_session()
                console.clear()
                console.print("[yellow][*] Chat history and terminal screen cleared.[/yellow]")
                continue

            if user_input == "/wipe":
                agent.wipe_all_sessions()
                console.print("[yellow][*] All saved conversations wiped.[/yellow]")
                continue

            if user_input == "/help":
                print_help(console)
                continue

            if user_input == "/history":
                print_history_list(console)
                continue

            if user_input == "/tools":
                table = Table(title="Active Tools", show_header=True, header_style="bold yellow")
                table.add_column("Tool Name", style="cyan")
                table.add_column("Description", style="white")
                for tname in config.get("active_tools", []):
                    try:
                        import ant_agent.tools as tools
                        t_inst = tools.get_tool(tname, agent)
                        table.add_row(tname, t_inst.description)
                    except Exception:
                        table.add_row(tname, "[red]Failed to load tool[/red]")
                console.print(table)
                continue

            if user_input == "/thinking":
                config["show_thinking"] = not config.get("show_thinking", True)
                save_config(config)
                state = "ENABLED" if config["show_thinking"] else "DISABLED"
                console.print(f"[yellow][*] Thinking process visualization {state}.[/yellow]")
                continue

            if user_input == "/stats":
                print_stats(console, agent)
                continue

            if user_input == "/config":
                table = Table(title="Active Configuration", show_header=True, header_style="bold green")
                table.add_column("Key", style="cyan")
                table.add_column("Value", style="white")
                for k, v in config.items():
                    if k == "system_prompt":
                        v = v.splitlines()[0] + "..." if v else ""
                    table.add_row(k, str(v))
                console.print(table)
                continue

            # Run with a status spinner
            with console.status("[bold blue]Thinking...[/bold blue]", spinner="dots") as status:
                def status_callback(action, msg):
                    if action == "update":
                        status.start()
                        status.update(msg)
                    elif action == "print":
                        status.stop()
                        console.print(msg)
                    elif action == "thought":
                        if config.get("show_thinking", True):
                            console.print(Panel(
                                f"[italic dim]{msg}[/italic dim]",
                                title="[dim]Thinking Process[/dim]",
                                border_style="blue",
                                expand=False
                            ))
                response = agent.run_cycle(user_input, verbose=args.verbose, status_callback=status_callback)
            
            console.print("\n[bold cyan]Agent >[/bold cyan]")
            console.print(Markdown(response))
            console.print()

        except KeyboardInterrupt:
            print_stats(console, agent)
            console.print("\n[cyan]Goodbye![/cyan]")
            break
        except Exception as e:
            console.print(f"[bold red]\nError in loop: {e}\n[/bold red]")

def cmd_config(args):
    console = Console()
    config = load_config()
    if args.action == "show":
        table = Table(title="Current Configuration", show_header=True, header_style="bold cyan")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")
        for k, v in config.items():
            if k == "system_prompt":
                prompt_lines = v.splitlines()
                v = "\n".join(prompt_lines[:3]) + "\n..." if len(prompt_lines) > 3 else v
            table.add_row(k, str(v))
        console.print(table)
    elif args.action == "set":
        key = args.key
        value = args.value
        if key not in config:
            console.print(f"[yellow]Warning: {key} is not a standard config key, adding it.[/yellow]")
        
        if key == "active_tools":
            value = [t.strip() for t in value.split(",")]
        
        config[key] = value
        if save_config(config):
            console.print(f"[bold green]Successfully updated config: {key} = {value}[/bold green]")
        else:
            console.print("[bold red]Failed to save configuration.[/bold red]")

def print_history_list(console):
    sessions_dir = Path.cwd() / ".ant_agent" / "sessions"
    if not sessions_dir.exists() or not list(sessions_dir.glob("*.json")):
        console.print("[yellow]No saved chat sessions found in this workspace.[/yellow]")
        return
        
    table = Table(title="Saved Chat Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Session UUID", style="cyan")
    table.add_column("Last Active", style="magenta")
    table.add_column("Messages", style="green")
    
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

def cmd_resume(args):
    console = Console()
    if args.session_id:
        cmd_chat(args)
        return
    print_history_list(console)
    console.print("\nTo resume a session, run: [bold green]python ant_agent.py resume <session-uuid>[/bold green]\n")

def cmd_memory(args):
    console = Console()
    config = load_config()
    agent = AntAgent(config)
    
    if args.action == "add":
        text = " ".join(args.text)
        agent.db.store(text)
        console.print(f"[bold green]Stored in vector memory: '{text}'[/bold green]")
    elif args.action == "query":
        query = " ".join(args.text)
        results = agent.db.recall(query, limit=args.limit)
        
        table = Table(title=f"Memory Search Results for '{query}'", show_header=True, header_style="bold cyan")
        table.add_column("No.", style="yellow")
        table.add_column("Score", style="magenta")
        table.add_column("Content", style="white")
        table.add_column("Timestamp", style="dim")
        
        for i, res in enumerate(results, 1):
            table.add_row(str(i), f"{res['score']:.4f}", res['text'], str(res['timestamp']))
        console.print(table)

def cmd_stats(args):
    console = Console()
    config = load_config()
    agent = AntAgent(config)
    print_stats(console, agent, show_global=True)

def main():
    parser = argparse.ArgumentParser(description="Ant Agent CLI AI Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Chat Subcommand
    chat_parser = subparsers.add_parser("chat", help="Start interactive agent chat session")
    chat_parser.add_argument("--verbose", action="store_true", default=True, help="Display tool calls and execution step-by-step")
    chat_parser.add_argument("--no-verbose", dest="verbose", action="store_false", help="Hide tool calling steps")

    # Resume Subcommand
    resume_parser = subparsers.add_parser("resume", help="Resume a saved interactive agent chat session")
    resume_parser.add_argument("session_id", nargs="?", default=None, help="The UUID of the session to resume")
    resume_parser.add_argument("--verbose", action="store_true", default=True, help="Display tool calls and execution step-by-step")
    resume_parser.add_argument("--no-verbose", dest="verbose", action="store_false", help="Hide tool calling steps")

    # Config Subcommand
    config_parser = subparsers.add_parser("config", help="Manage settings")
    config_subparsers = config_parser.add_subparsers(dest="action", required=True)
    config_subparsers.add_parser("show", help="Display active settings")
    set_parser = config_subparsers.add_parser("set", help="Modify a setting")
    set_parser.add_argument("key", help="Configuration key (e.g. llm_base_url, embedding_provider)")
    set_parser.add_argument("value", help="Configuration value")

    # Memory Subcommand
    memory_parser = subparsers.add_parser("memory", help="Manage agent memory store")
    memory_subparsers = memory_parser.add_subparsers(dest="action", required=True)
    
    add_parser = memory_subparsers.add_parser("add", help="Add new memory text block")
    add_parser.add_argument("text", nargs="+", help="Memory content to store")
    
    query_parser = memory_subparsers.add_parser("query", help="Search the memory store")
    query_parser.add_argument("text", nargs="+", help="Search query string")
    query_parser.add_argument("--limit", type=int, default=5, help="Number of records to show")

    # Stats Subcommand
    stats_parser = subparsers.add_parser("stats", help="Display global lifetime token consumption stats")

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
