"""
Ant Agent TUI Theme — Lightweight color palette, icons, and ASCII branding.
Zero external dependencies beyond Rich (already required).
"""
from rich.box import ROUNDED, HEAVY, SIMPLE, DOUBLE
from rich.style import Style
from rich.rule import Rule

# ─── Color Palette ────────────────────────────────────────────────
# Curated accent colors for consistent visual identity.
ACCENT_CYAN    = "bright_cyan"
ACCENT_MAGENTA = "magenta"
ACCENT_YELLOW  = "yellow"
ACCENT_GREEN   = "green"
ACCENT_RED     = "bright_red"
ACCENT_BLUE    = "blue"
ACCENT_DIM     = "dim"

# ─── Semantic Styles ─────────────────────────────────────────────
STYLE_AGENT_LABEL  = Style(color="bright_cyan", bold=True)
STYLE_USER_LABEL   = Style(color="bright_green", bold=True)
STYLE_TOOL_NAME    = Style(color="yellow", bold=True)
STYLE_DONE_BADGE   = Style(color="bright_green", bold=True)
STYLE_ERROR        = Style(color="bright_red", bold=True)
STYLE_DIM          = Style(dim=True)
STYLE_ROUTE_TAG    = Style(color="magenta", bold=True)
STYLE_THINKING     = Style(color="blue", italic=True, dim=True)

# ─── Box Presets ─────────────────────────────────────────────────
BOX_TOOL_CALL     = HEAVY       # Bold outline for tool invocations
BOX_TOOL_RESPONSE = ROUNDED     # Softer outline for results
BOX_THINKING      = SIMPLE      # Minimal outline for thoughts
BOX_PLAN          = DOUBLE      # Prominent outline for DAG plans
BOX_WELCOME       = ROUNDED     # Welcome banner

# ─── Icons ───────────────────────────────────────────────────────
ICON_ANT       = "🐜"
ICON_BOLT      = "⚡"
ICON_BRAIN     = "🧠"
ICON_CLIPBOARD = "📋"
ICON_CHECK     = "✅"
ICON_GEAR      = "⚙️"
ICON_SEARCH    = "🔍"
ICON_CHART     = "📊"
ICON_PLUG      = "🔌"
ICON_WAVE      = "👋"
ICON_KEY       = "🔑"
ICON_CLOCK     = "⏱️"
ICON_WARN      = "⚠️"
ICON_ROCKET    = "🚀"
ICON_FOLDER    = "📁"
ICON_TRASH     = "🗑️"
ICON_CLEAR     = "🧹"
ICON_LIST      = "📜"
ICON_EYE       = "👁️"
ICON_EXIT      = "🚪"
ICON_HELP      = "❓"
ICON_ARROW     = "›"

# ─── Braille Art Banner ──────────────────────────────────────────
BANNER = """[bright_cyan]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⠓⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣾⠚⢹⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⢀⡠⠶⡟⠳⠤⣄⡓⢤⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⣤⣤⣦⣦⣴⣤⡀⠀⠀⠀⠀⠀⢀⣠⣾⣿⣤⣄⣻⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⢀⡔⠉⠀⡼⠀⠀⠀⠀⠉⠛⢷⣴⣸⠿⢿⣷⣿⣶⣤⣀⠴⢿⣿⣯⣿⣿⣿⣿⣿⣿⣿⣆⠀⠰⢢⣰⣿⣉⣼⣿⣿⣿⣭⣿⣿⣦⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣰⠎⠀⠀⢀⠀⠀⠀⠀⠀⠀⢠⣿⡟⠁⢀⣻⣿⣿⣿⣿⣿⣶⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⡀⠀⠀⠀⠀⠀⠀
⠀⡸⠁⠀⠀⠀⡾⠀⠀⠀⠀⠀⠀⢿⢿⣧⣄⣴⣿⣿⣿⣿⣿⠏⠁⠈⠉⣻⢿⣿⡟⠛⢿⣿⣿⣿⣿⡿⠿⢿⣿⣿⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡆⠀⠀⠀⠀⠀
⠘⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠟⣶⣿⣿⣿⣿⣿⠟⠋⠈⠓⣾⣿⣶⣼⣶⣿⣷⠀⠀⢻⣿⢿⠻⠻⠹⠿⠿⠿⠛⠟⠿⢿⢿⣿⣿⣿⣿⣿⣿⣿⡿⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⢰⡿⠁⠀⡸⠶⢶⣿⣿⣿⣿⣿⣿⠁⠀⣶⣿⡇⠀⠁⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⢿⠀⠀⠀⠀⠹⣆⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣴⠛⠁⢀⣾⠁⠀⠀⠀⠈⠈⠉⠁⠀⠐⣟⠉⠁⠀⠀⠀⠈⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣶⡀⠀⠀⠀⠈⠉⠐⢶⠄
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠼⠋⠀⠀⢠⡾⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣧⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣷⡄⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠒⠉⠁⠀⠀⢀⡼⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⣳⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹⢆⡀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡾⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢣⣀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣰⠟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠧⡀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠠⠼⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠻⣄⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢡⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/bright_cyan]
  [bold bright_cyan]A N T   A G E N T[/bold bright_cyan]  [dim]· Local AI CLI Agent[/dim]"""

COMPACT_BANNER = """  [bold bright_cyan]🐜  A N T   A G E N T[/bold bright_cyan]  [dim]· Local AI CLI Agent[/dim]"""

def get_banner(console_width: int = 80) -> str:
    """Return an appropriate banner based on the current terminal width."""
    if console_width >= 115:
        return BANNER
    return COMPACT_BANNER

# ─── Separator Rule ──────────────────────────────────────────────
def get_rule(style: str = "dim cyan") -> Rule:
    """Return a dynamic Rich Rule that auto-scales to terminal width."""
    return Rule(style=style)

# Backwards-compatible rule instance
THIN_RULE = Rule(style="dim cyan")
