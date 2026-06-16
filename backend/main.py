from backend import privacy
from backend.db import DatabaseInterface
from backend.eco_scheduler import EcoScheduler

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import traceback
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.align import Align

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter

import time
import os
import json

traceback.install()
console = Console()

# ─────────────────────────────────────────────────────────────
# ROLE CONFIGURATION
# ─────────────────────────────────────────────────────────────
ROLE_CONFIG = {
    "admin": {
        "budget": 999.0,
        "allowed_modes": ["raw", "private", "audit"]
    },
    "analyst": {
        "budget": 10.0,
        "allowed_modes": ["private"]
    },
    "auditor": {
        "budget": 15.0,
        "allowed_modes": ["private", "audit"]
    }
}

SQL_KEYWORDS = [
    "SELECT", "INSERT", "UPDATE", "DELETE",
    "FROM", "WHERE", "LIMIT", "VALUES",
    "CREATE", "DROP", "TABLE", "ALTER",
    "COUNT", "AVG", "SUM", "MIN", "MAX",
    "JOIN", "INNER", "LEFT", "RIGHT",
    "GROUP BY", "ORDER BY"
]

# ─────────────────────────────────────────────────────────────
# MASK CONFIG  —  persistent JSON
# ─────────────────────────────────────────────────────────────
# Saved in backend/.mask_config.json
# Admin writes it; analyst/auditor sessions read it silently.
# ─────────────────────────────────────────────────────────────

MASK_CONFIG_FILE     = os.path.join(os.path.dirname(__file__), ".mask_config.json")
DEFAULT_SENSITIVE     = {"aadhar_number", "abc_id"}


def load_mask_config() -> set:
    """Load admin-configured masked columns. Falls back to defaults."""
    try:
        with open(MASK_CONFIG_FILE, "r") as f:
            data = json.load(f)
            return set(c.lower() for c in data.get("masked_columns", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set(DEFAULT_SENSITIVE)


def save_mask_config(cols: set) -> None:
    """Write masked column set to JSON file."""
    with open(MASK_CONFIG_FILE, "w") as f:
        json.dump({"masked_columns": sorted(list(cols))}, f, indent=2)


# ─────────────────────────────────────────────────────────────
# MASKING ENGINE
# ─────────────────────────────────────────────────────────────

def mask_value(value: str) -> str:
    """Keep last 4 characters; replace rest with *.
    "123456789012" → "********9012"
    "ABC1001"      → "***1001"
    """
    s = str(value)
    vis = 4
    if len(s) <= vis:
        return "*" * len(s)
    return "*" * (len(s) - vis) + s[-vis:]


def apply_masking(rows: list, columns: list,
                  role: str, sensitive: set) -> list:
    """Replace sensitive column values with masked equivalents.
    Admin always bypasses. Database is never touched."""
    if role == "admin" or not rows or not sensitive:
        return rows

    idxs = {i for i, c in enumerate(columns) if c.lower() in sensitive}
    if not idxs:
        return rows

    out = []
    for row in rows:
        r = list(row)
        for i in idxs:
            if i < len(r) and r[i] is not None:
                r[i] = mask_value(str(r[i]))
        out.append(tuple(r))
    return out


def has_sensitive(columns: list, sensitive: set) -> bool:
    return any(c.lower() in sensitive for c in columns)


# ─────────────────────────────────────────────────────────────
# ADMIN MASK WIZARD  (runs at admin login)
# ─────────────────────────────────────────────────────────────

def get_all_db_columns(db_interface) -> dict:
    """Returns {table_name: [col1, col2, ...]} for all public tables."""
    try:
        result, _ = db_interface.execute_query("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position;
        """)
        tables = {}
        if result:
            for tbl, col in result:
                tables.setdefault(tbl, []).append(col)
        return tables
    except Exception:
        return {}


def admin_mask_wizard(db_interface, current: set) -> set:
    """
    Interactive wizard shown to admin right after login.
    Fetches every column from every public table, lets admin
    choose which ones to mask for analyst/auditor sessions.
    """
    console.print()
    console.print(Panel(
        "[bold cyan]Sensitive Data Masking Configuration[/bold cyan]\n"
        "[dim]Select which columns will be masked for analyst and auditor roles.\n"
        "Admin always sees the real unmasked values.[/dim]",
        border_style="cyan"
    ))

    all_tables = get_all_db_columns(db_interface)

    if not all_tables:
        console.print("[yellow]  ⚠  Could not retrieve columns from database.[/yellow]")
        console.print("[dim]  Keeping existing mask configuration.[/dim]")
        return current

    # ── Show all available columns ──
    tbl = Table(
        title="All Database Columns",
        show_header=True,
        header_style="bold white",
        border_style="dim cyan"
    )
    tbl.add_column("Table",           style="cyan",   min_width=22)
    tbl.add_column("Column",          style="white",  min_width=26)
    tbl.add_column("Currently Masked",style="yellow", justify="center")

    all_flat = []
    for table_name, cols in sorted(all_tables.items()):
        for col in cols:
            is_masked = "🔒 YES" if col.lower() in current else "—"
            tbl.add_row(table_name, col, is_masked)
            all_flat.append(col.lower())

    console.print(tbl)

    # ── Show current selection ──
    if current:
        console.print(
            f"\n  Currently masked: [yellow]{', '.join(sorted(current))}[/yellow]"
        )
    else:
        console.print("\n  Currently masked: [dim]none[/dim]")

    console.print()
    console.print("  [bold]Enter your choice:[/bold]")
    console.print("  • Column names (comma-separated) → sets the new mask list")
    console.print("  • [cyan]keep[/cyan]  → keep current config unchanged")
    console.print("  • [cyan]none[/cyan]  → disable all masking")
    console.print()

    while True:
        raw = console.input(
            "[bold cyan]Columns to mask (comma-separated / keep / none):[/bold cyan] "
        ).strip()

        if not raw:
            continue

        if raw.lower() == "keep":
            console.print("[green]  ✓  Mask configuration unchanged.[/green]")
            return current

        if raw.lower() == "none":
            save_mask_config(set())
            console.print("[green]  ✓  All masking disabled.[/green]")
            return set()

        chosen  = {c.strip().lower() for c in raw.split(",") if c.strip()}
        unknown = chosen - set(all_flat)
        valid   = chosen - unknown

        if unknown:
            console.print(
                f"  [yellow]⚠  Not found in DB schema: "
                f"{', '.join(sorted(unknown))}[/yellow]"
            )
            ans = console.input("  Add them anyway? (y/n): ").strip().lower()
            if ans != "y":
                continue
            valid = chosen

        if not valid:
            console.print("[red]  No valid columns entered. Try again.[/red]")
            continue

        save_mask_config(valid)

        confirm_tbl = Table(show_header=False, box=None)
        confirm_tbl.add_column("", style="dim")
        confirm_tbl.add_column("")
        confirm_tbl.add_row(
            "Masked columns", f"[yellow]{', '.join(sorted(valid))}[/yellow]"
        )
        confirm_tbl.add_row("Applied to",  "analyst, auditor roles")
        confirm_tbl.add_row("Admin view",  "unmasked (full access)")

        console.print(Panel(
            confirm_tbl,
            title="[green]✓  Configuration Saved[/green]",
            border_style="green"
        ))
        return valid


# ─────────────────────────────────────────────────────────────
# RUNTIME  \mask  COMMAND  (admin only)
# ─────────────────────────────────────────────────────────────

def handle_mask_command(query: str, role: str,
                        sensitive: set, db_interface) -> set:
    """
    \\mask              — show config + help
    \\mask list         — list masked columns
    \\mask add <col>    — add a column
    \\mask remove <col> — remove a column
    \\mask clear        — disable all masking
    \\mask reset        — restore defaults (aadhar_number, abc_id)
    \\mask wizard       — launch interactive picker again
    """
    if role != "admin":
        console.print("[red]  Access Denied: only admin can configure masking.[/red]")
        return sensitive

    parts = query.strip().split()
    sub   = parts[1].lower() if len(parts) > 1 else "list"

    # list / no subcommand
    if sub in ("list", "mask"):
        body = (
            "\n".join(f"  🔒  {c}" for c in sorted(sensitive))
            if sensitive else "  [dim]No columns currently masked.[/dim]"
        )
        help_text = (
            "\n\n[dim]Sub-commands:[/dim]\n"
            "  [cyan]\\mask add <col>[/cyan]      Add a column to the mask list\n"
            "  [cyan]\\mask remove <col>[/cyan]   Remove a column\n"
            "  [cyan]\\mask clear[/cyan]          Disable all masking\n"
            "  [cyan]\\mask reset[/cyan]          Restore defaults (aadhar_number, abc_id)\n"
            "  [cyan]\\mask wizard[/cyan]         Full interactive column picker"
        )
        console.print(Panel(
            body + help_text,
            title="[cyan]Masking Configuration[/cyan]",
            border_style="cyan"
        ))
        return sensitive

    if sub == "add":
        if len(parts) < 3:
            console.print("[red]  Usage: \\mask add <column_name>[/red]")
            return sensitive
        col = parts[2].lower()
        sensitive.add(col)
        save_mask_config(sensitive)
        console.print(f"[green]  ✓  '{col}' added to masked columns.[/green]")
        console.print(f"  Active: [yellow]{', '.join(sorted(sensitive))}[/yellow]")
        return sensitive

    if sub == "remove":
        if len(parts) < 3:
            console.print("[red]  Usage: \\mask remove <column_name>[/red]")
            return sensitive
        col = parts[2].lower()
        if col not in sensitive:
            console.print(f"[yellow]  '{col}' is not in the masked list.[/yellow]")
            return sensitive
        sensitive.discard(col)
        save_mask_config(sensitive)
        console.print(f"[green]  ✓  '{col}' removed.[/green]")
        rem = ', '.join(sorted(sensitive)) if sensitive else "none"
        console.print(f"  Active: [yellow]{rem}[/yellow]")
        return sensitive

    if sub == "clear":
        sensitive = set()
        save_mask_config(sensitive)
        console.print("[green]  ✓  All masking cleared.[/green]")
        return sensitive

    if sub == "reset":
        sensitive = set(DEFAULT_SENSITIVE)
        save_mask_config(sensitive)
        console.print(
            f"[green]  ✓  Defaults restored: "
            f"[yellow]{', '.join(sorted(sensitive))}[/yellow][/green]"
        )
        return sensitive

    if sub == "wizard":
        return admin_mask_wizard(db_interface, sensitive)

    console.print(f"[red]  Unknown sub-command: '{sub}'[/red]  →  run [cyan]\\mask[/cyan] for help.")
    return sensitive


# ─────────────────────────────────────────────────────────────
# COMMAND REFERENCE
# ─────────────────────────────────────────────────────────────

def show_command_reference(role: str):
    tbl = Table(title="NOVA QL Commands", show_header=True, header_style="bold cyan")
    tbl.add_column("Command",  min_width=32)
    tbl.add_column("Use Case")

    tbl.add_row("\\epsilon <value>",       "Set privacy noise level  (range: 0.01 – 10.0  |  lower = more private)")
    tbl.add_row("\\mode raw|private|audit","Switch privacy mode (role restricted)")
    tbl.add_row("\\metrics",              "Show live metrics dashboard")
    tbl.add_row("\\help",                 "Show this command reference")

    if role == "admin":
        tbl.add_row("\\dmc",               "Data Masking Configuration wizard")
        tbl.add_row("\\mask",              "Show masked column config")
        tbl.add_row("\\mask add <col>",    "Add column to mask list")
        tbl.add_row("\\mask remove <col>", "Remove column from mask list")
        tbl.add_row("\\mask clear",        "Disable all masking")
        tbl.add_row("\\mask reset",        "Restore defaults (aadhar_number, abc_id)")
        tbl.add_row("\\mask wizard",       "Interactive column picker")

    tbl.add_row("\\logout",               "Log out and return to login prompt")
    tbl.add_row("exit",                    "Exit NOVA QL")
    tbl.add_row("SQL Query",              "Execute SQL query")

    console.print(Panel(tbl, border_style="cyan"))


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Startup animation
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]Initializing NOVA QL Engine...[/bold cyan]"),
        transient=True, console=console
    ) as progress:
        progress.add_task("init", total=None)
        time.sleep(1.2)

    # Banner
    console.print()
    console.print()

    GLYPHS = {
        "N": ["10001","11001","10101","10011","10001","10001","10001"],
        "O": ["01110","10001","10001","10001","10001","10001","01110"],
        "V": ["10001","10001","10001","10001","10001","01010","00100"],
        "A": ["01110","10001","10001","11111","10001","10001","10001"],
        " ": ["000","000","000","000","000","000","000"],
        "Q": ["01110","10001","10001","10001","10101","10011","01111"],
        "L": ["10000","10000","10000","10000","10000","10000","11111"],
    }
    ROW_COLORS = ["#64b4ff","#50a0ff","#3c84f0","#286edc","#1e5ac8","#1446b4","#0a32a0"]

    glyphs = [GLYPHS[ch] for ch in "NOVA QL" if ch in GLYPHS]
    for row_idx in range(7):
        line = Text()
        for li, glyph in enumerate(glyphs):
            for bit in glyph[row_idx]:
                line.append("██" if bit == "1" else "  ",
                            style=f"bold {ROW_COLORS[row_idx]}")
            if li < len(glyphs) - 1:
                line.append("  ")
        console.print(Align.center(line))

    console.print()
    console.print(Align.center(
        Text("—  Privacy-Preserving & Energy-Aware SQL Engine  —", style="bold #4a9eff")
    ))
    console.print()

    # DB connection created once — same credentials for all sessions
    db_config = {
        "host": "localhost", "database": "Students",
        "user": "postgres",  "password": "SQL", "port": "5432"
    }
    db_interface = DatabaseInterface(db_config)

    # ─────────────────────────────────────────────────────
    # SESSION LOOP — restarts here on \logout
    # ─────────────────────────────────────────────────────
    while True:

        console.print()
        # Login
        username = console.input("[bold cyan]Enter username:[/bold cyan] ").strip()
        role     = console.input(
            "[bold cyan]Select role (admin / analyst / auditor):[/bold cyan] "
        ).strip().lower()

        if role not in ROLE_CONFIG:
            console.print("[red]Invalid role selected. Try again.[/red]")
            continue

        role_data = ROLE_CONFIG[role]

        # Per-session init — fresh DP instance and counters each login
        dp_instance            = privacy.DifferentialPrivacy(epsilon=1.0)
        dp_instance.register_user(username, total_budget=role_data["budget"])
        eco_scheduler_instance = EcoScheduler(query_buffer_size=5)

        total_queries        = 0
        total_emissions      = 0.0
        total_execution_time = 0.0
        _do_logout           = False

        # ── Mask config ──────────────────────────────────────
        # All roles: silently load whatever admin last configured.
        # Admin can run the wizard anytime with \dmc or \mask wizard.
        sensitive_columns = load_mask_config()

        # Startup diagnostics
        if sensitive_columns:
            cols_str = ", ".join(sorted(sensitive_columns))
            mask_status = (
                f"[green]✓ Configured[/green]  [dim](you see unmasked values)[/dim]"
                if role == "admin"
                else f"[green]✓ Active[/green]  [yellow]{cols_str}[/yellow]"
            )
        else:
            mask_status = "[dim]Disabled — no columns configured[/dim]"

        diag = Table(show_header=False, box=None)
        diag.add_column("Component", style="bold")
        diag.add_column("Status")
        diag.add_row("Database Connection",    "[green]✓ Connected[/green]")
        diag.add_row("Differential Privacy",   "[green]✓ Ready[/green]")
        diag.add_row("Sensitive Data Masking", mask_status)
        diag.add_row("Energy Tracker",         "[green]✓ Ready[/green]")
        diag.add_row("User",                   f"[cyan]{username}[/cyan]")
        diag.add_row("Role",                   f"[yellow]{role}[/yellow]")

        console.print(Panel(diag, title="Startup Diagnostics", border_style="green"))
        # Compact hint — full table available via \help
        hint = Text()
        hint.append("  Type ", style="dim")
        hint.append("\\help", style="bold cyan")
        hint.append(" to list all commands", style="dim")
        if role == "admin":
            hint.append("  ·  ", style="dim")
            hint.append("\\dmc", style="bold cyan")
            hint.append(" to configure data masking", style="dim")
        console.print(hint)

        # Autocomplete
        try:
            tables_result, _ = db_interface.execute_query(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
            )
            table_names = [row[0] for row in tables_result] if tables_result else []
        except Exception:
            table_names = []

        completer    = WordCompleter(SQL_KEYWORDS + table_names, ignore_case=True)
        history_file = os.path.join(os.path.dirname(__file__), ".safe_sql_history")
        session      = PromptSession(history=FileHistory(history_file))

        # ─────────────────────────────────────────────────────
        # CLI LOOP
        # ─────────────────────────────────────────────────────
        while True:
            try:
                user_query = session.prompt("\nSQL > ", completer=completer)
            except KeyboardInterrupt:
                continue
            except EOFError:
                break

            if not user_query.strip():
                continue

            # \logout — end this session, return to login prompt
            if user_query.lower() == "\\logout":
                console.print("[bold cyan]Logging out...[/bold cyan]")
                _do_logout = True
                break

            # exit — shut down entirely
            if user_query.lower() == "exit":
                console.print("[bold red]Shutting down NOVA QL...[/bold red]")
                break

            # \help — print full command reference on demand
            if user_query.lower() == "\\help":
                show_command_reference(role)
                continue

            # \epsilon
            if user_query.startswith("\\epsilon"):
                try:
                    value = float(user_query.split()[1])
                    dp_instance.set_epsilon(value)
                    console.print(f"[green]Epsilon updated to {value}[/green]")
                except Exception:
                    console.print("[red]Usage: \\epsilon <value>[/red]")
                continue

            # \mode
            if user_query.startswith("\\mode"):
                try:
                    mode = user_query.split()[1]
                    if mode not in role_data["allowed_modes"]:
                        console.print(
                            f"[red]Access Denied: {role} cannot use '{mode}' mode.[/red]"
                        )
                        continue
                    dp_instance.set_mode(mode)
                    console.print(f"[green]Mode switched to {mode}[/green]")
                except Exception:
                    console.print("[red]Usage: \\mode raw|private|audit[/red]")
                continue

            # \dmc — Data Masking Configuration wizard (admin only)
            if user_query.lower() == "\\dmc":
                if role != "admin":
                    console.print("[red]  Access Denied: only admin can access masking config.[/red]")
                else:
                    sensitive_columns = admin_mask_wizard(db_interface, sensitive_columns)
                continue

            # \mask  (admin only)
            if user_query.startswith("\\mask"):
                sensitive_columns = handle_mask_command(
                    user_query, role, sensitive_columns, db_interface
                )
                continue

            # \metrics
            if user_query.startswith("\\metrics"):
                metrics = dp_instance.get_metrics(username)

                mt = Table(show_header=False)
                mt.add_row("User",                     username)
                mt.add_row("Role",                     role)
                mt.add_row("Total Queries",            str(total_queries))
                mt.add_row("Total Emissions (kg CO2)", f"{total_emissions:.6f}")
                mt.add_row(
                    "Avg Execution Time (sec)",
                    f"{(total_execution_time / total_queries):.4f}" if total_queries else "0"
                )
                mt.add_row("Epsilon",          str(metrics["epsilon"]))
                mt.add_row("Remaining Budget", str(metrics["remaining_budget"]))
                mt.add_row("Mode",             metrics["mode"])

                if sensitive_columns:
                    mask_info = (
                        f"Configured — admin sees unmasked"
                        if role == "admin"
                        else f"Active — {', '.join(sorted(sensitive_columns))}"
                    )
                else:
                    mask_info = "Disabled"
                mt.add_row("PII Masking", mask_info)

                console.print(Panel(mt, title="Live Metrics Dashboard", border_style="cyan"))
                continue

            # SQL query
            try:
                with console.status("[bold green]Executing query...[/bold green]", spinner="dots"):
                    start_time = time.time()
                    eco_scheduler_instance.start_tracking()

                    result, columns = db_interface.execute_query(user_query)
                    privacy_output  = dp_instance.process_result(username, user_query, result)

                    emissions      = eco_scheduler_instance.stop_tracking()
                    end_time       = time.time()
                    execution_time = end_time - start_time

                total_queries        += 1
                total_emissions      += emissions
                total_execution_time += execution_time

                if privacy_output is None:
                    console.print("[green]Query executed successfully.[/green]")
                    continue

                raw     = privacy_output["raw"]
                private = privacy_output["private"]
                noise   = privacy_output["noise"]

                # ══════════════════════════════════════════════════
                # LAYER 2 — ADMIN-CONFIGURED SENSITIVE DATA MASKING
                # Applied after DP, before display. DB unchanged.
                # Columns chosen by admin, persisted in JSON config.
                # ══════════════════════════════════════════════════
                masked_private  = apply_masking(private, columns, role, sensitive_columns)
                masking_applied = (
                    role != "admin"
                    and private is not None
                    and has_sensitive(columns, sensitive_columns)
                )
                # ══════════════════════════════════════════════════

                if masked_private:
                    table = Table(show_header=True, header_style="bold magenta")
                    for col in columns:
                        if col.lower() in sensitive_columns and role != "admin":
                            table.add_column(f"[yellow]{col} 🔒[/yellow]")
                        else:
                            table.add_column(col)
                    for row in masked_private:
                        table.add_row(*[str(item) for item in row])
                    console.print(table)

                if masking_applied:
                    masked_names = ", ".join(
                        c for c in columns if c.lower() in sensitive_columns
                    )
                    console.print(
                        f"[dim yellow]  🔒  Masked: {masked_names} — "
                        f"last 4 characters visible.[/dim yellow]"
                    )

                if dp_instance.mode == "audit" and raw is not None:
                    console.print(Panel(f"Raw Result:\n{raw}",    border_style="yellow"))
                    console.print(Panel(f"Noise Added:\n{noise}", border_style="red"))

                console.print(
                    Panel.fit(
                        f"[bold cyan]Execution Time:[/bold cyan] {execution_time:.4f} sec\n"
                        f"[bold green]Epsilon:[/bold green] {dp_instance.epsilon}\n"
                        f"[bold yellow]Remaining Budget:[/bold yellow] "
                        f"{dp_instance.get_remaining_budget(username)}\n"
                        f"[bold magenta]Emissions:[/bold magenta] {emissions:.6f} kg CO2",
                        border_style="blue"
                    )
                )

            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")

        # ── End of CLI loop ──────────────────────────────────
        # If \logout was typed, restart the session loop.
        # If exit or EOF, break out and shut down.
        if not _do_logout:
            break
