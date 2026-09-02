#!/usr/bin/env python3
"""
scheduler.py — run a command at a randomly-chosen time, based on 3 modes:

  clock   : pick a random time between two clock times (e.g. between 14:00 and 18:00 today)
  timer   : pick a random delay (in seconds) after the script starts, then run
  trigger : don't schedule anything — run only when triggered manually (Enter key)
            or via an HTTP POST request (e.g. from a webhook or automation)

Only standard library is used, so there's nothing to pip install.

-----------------------------------------------------------------------------
EXAMPLE COMMANDS (syntax reference)
-----------------------------------------------------------------------------

# Clock mode: run `echo "hi"` at a random time between 14:00 and 18:00 today
python3 scheduler.py --mode clock --start 14:00 --end 18:00 --command 'echo "hi"'

# Timer mode: run the command at a random point between 10 and 300 seconds
# from when the script starts
python3 scheduler.py --mode timer --min-delay 10 --max-delay 300 --command 'echo "hi"'

# Trigger mode: do nothing until you press Enter in this terminal, OR
# send: curl -X POST http://localhost:8787/trigger
python3 scheduler.py --mode trigger --port 8787 --command 'echo "hi"'

-----------------------------------------------------------------------------
"""

import argparse
import datetime
import http.server
import random
import subprocess
import sys
import threading
import time


def run_command(command: str) -> None:
    """Runs the configured shell command and prints its output."""
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] Running: {command}")
    result = subprocess.run(command, shell=True)
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] Finished with exit code {result.returncode}")


# -----------------------------------------------------------------------
# CLOCK MODE — random time between two clock times
# -----------------------------------------------------------------------
def parse_clock(value: str) -> datetime.time:
    hour, minute = map(int, value.split(":"))
    return datetime.time(hour=hour, minute=minute)


def run_clock_mode(start: str, end: str, command: str) -> None:
    start_t = parse_clock(start)
    end_t = parse_clock(end)

    now = datetime.datetime.now()
    start_dt = datetime.datetime.combine(now.date(), start_t)
    end_dt = datetime.datetime.combine(now.date(), end_t)

    # If the window wraps past midnight (e.g. 22:00 -> 02:00), push end to next day
    if end_dt <= start_dt:
        end_dt += datetime.timedelta(days=1)

    # If the whole window has already passed today, move both to tomorrow
    if now > end_dt:
        start_dt += datetime.timedelta(days=1)
        end_dt += datetime.timedelta(days=1)

    window_seconds = (end_dt - start_dt).total_seconds()
    random_offset = random.uniform(0, window_seconds)
    target = start_dt + datetime.timedelta(seconds=random_offset)

    wait_seconds = max(0, (target - datetime.datetime.now()).total_seconds())
    print(f"Clock mode: scheduled for {target.isoformat(timespec='seconds')} "
          f"(waiting {wait_seconds/60:.1f} minutes)")
    time.sleep(wait_seconds)
    run_command(command)


# -----------------------------------------------------------------------
# TIMER MODE — random delay since the script started
# -----------------------------------------------------------------------
def run_timer_mode(min_delay: float, max_delay: float, command: str) -> None:
    delay = random.uniform(min_delay, max_delay)
    print(f"Timer mode: will run in {delay:.1f} seconds")
    time.sleep(delay)
    run_command(command)


# -----------------------------------------------------------------------
# TRIGGER MODE — only runs when manually triggered (keypress or API call)
# -----------------------------------------------------------------------
def run_trigger_mode(command: str, port: int) -> None:
    lock = threading.Lock()  # prevents overlapping runs if triggered twice quickly

    def safe_run():
        with lock:
            run_command(command)

    class TriggerHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/trigger":
                threading.Thread(target=safe_run, daemon=True).start()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"triggered\n")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass  # keep console output quiet/clean

    server = http.server.HTTPServer(("0.0.0.0", port), TriggerHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"Trigger mode: waiting for input.")
    print(f"  -> Press Enter in this terminal to trigger, or")
    print(f"  -> curl -X POST http://localhost:{port}/trigger")
    print("  (Ctrl+C to quit)")

    try:
        while True:
            input()  # blocks until Enter is pressed
            threading.Thread(target=safe_run, daemon=True).start()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


# -----------------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run a command based on clock, timer, or trigger scheduling.")
    parser.add_argument("--mode", required=True, choices=["clock", "timer", "trigger"])
    parser.add_argument("--command", required=True, help="Shell command to run")

    # clock mode args
    parser.add_argument("--start", help="Clock mode: window start, e.g. 14:00")
    parser.add_argument("--end", help="Clock mode: window end, e.g. 18:00")

    # timer mode args
    parser.add_argument("--min-delay", type=float, help="Timer mode: minimum seconds")
    parser.add_argument("--max-delay", type=float, help="Timer mode: maximum seconds")

    # trigger mode args
    parser.add_argument("--port", type=int, default=8787, help="Trigger mode: API port (default 8787)")

    args = parser.parse_args()

    if args.mode == "clock":
        if not args.start or not args.end:
            sys.exit("Clock mode requires --start and --end (e.g. --start 14:00 --end 18:00)")
        run_clock_mode(args.start, args.end, args.command)

    elif args.mode == "timer":
        if args.min_delay is None or args.max_delay is None:
            sys.exit("Timer mode requires --min-delay and --max-delay (in seconds)")
        run_timer_mode(args.min_delay, args.max_delay, args.command)

    elif args.mode == "trigger":
        run_trigger_mode(args.command, args.port)


if __name__ == "__main__":
    main()
