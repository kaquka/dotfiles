#!/usr/bin/python3
"""Cierra un pane / ventana / sesión de tmux sin dejar nada vivo.

  close-agent.py pane    <pane_id>
  close-agent.py window  <window_id>
  close-agent.py session <session_id>

1. Toma una foto del árbol de procesos de cada pane (pid + hora de inicio).
2. A los Claude les manda SIGTERM y espera hasta 5 s a que salgan solos
   (así guardan la conversación y cierran sus MCP).
3. Cierra el pane/ventana/sesión en tmux. Si en la ventana solo queda el
   sidebar de workmux, cierra también la ventana.
4. Lo que siga vivo de la foto (procesos en segundo plano, MCP colgados) recibe
   SIGTERM y luego SIGKILL. La hora de inicio evita matar un pid reciclado.
Lo llaman los binds x / X / K de radar.conf (run-shell -b).
"""
import os
import re
import signal
import subprocess
import sys
import time

TMUX = "/opt/homebrew/bin/tmux"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def tmux(*a):
    return subprocess.run([TMUX, *a], capture_output=True, text=True).stdout.strip()


def say(msg):
    tmux("display-message", "-d", "4000", msg)


def ps():
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,lstart=,comm="], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 7)  # pid ppid Dow Mon DD HH:MM:SS YYYY comm
        if len(parts) < 8:
            continue
        procs[int(parts[0])] = (int(parts[1]), " ".join(parts[2:7]), os.path.basename(parts[7]))
    return procs


def tree(root, procs):
    kids = {}
    for pid, (ppid, _, _) in procs.items():
        kids.setdefault(ppid, []).append(pid)
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        if p in procs:
            out.append(p)
        stack.extend(kids.get(p, []))
    return out


def alive(snap):
    now = ps()
    return [pid for pid, start in snap.items() if pid in now and now[pid][1] == start]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    scope, target = sys.argv[1], sys.argv[2]
    flag = {"pane": [], "window": [], "session": ["-s"]}[scope]
    if scope == "pane":
        fmt_target = ["-t", target]
        rows = [tmux("display", "-p", "-t", target,
                     "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{window_id}\t#{@workmux_token}\t#{pane_current_path}")]
    else:
        fmt_target = ["-t", target]
        rows = tmux("list-panes", *flag, *fmt_target, "-F",
                    "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{window_id}\t#{@workmux_token}\t#{pane_current_path}").splitlines()
    rows = [r.split("\t") for r in rows if r.count("\t") == 5]
    if not rows:
        say("close-agent: no encontré %s %s" % (scope, target))
        return

    procs = ps()
    snap, claudes, worktrees = {}, [], set()
    for pane_id, pane_pid, cmd, win, token, path in rows:
        if cmd == "workmux":
            continue  # sidebar de workmux: lo maneja workmux
        for pid in tree(int(pane_pid), procs):
            snap[pid] = procs[pid][1]
            name = procs[pid][2]
            if name == "claude" or VERSION_RE.match(name):
                claudes.append(pid)
        if token and scope != "pane":
            worktrees.add(path)

    # 2) Claude: salida ordenada
    for pid in claudes:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 5
    while claudes and time.time() < deadline:
        if not alive({p: snap[p] for p in claudes}):
            break
        time.sleep(0.2)

    # 3) tmux
    win = rows[0][3]
    if scope == "pane":
        tmux("kill-pane", "-t", target)
        left = tmux("list-panes", "-t", win, "-F", "#{pane_current_command}").split()
        if left and all(c == "workmux" for c in left):
            tmux("kill-window", "-t", win)
    elif scope == "window":
        tmux("kill-window", "-t", target)
    else:
        tmux("kill-session", "-t", target)

    # 4) lo que quede vivo
    time.sleep(0.8)
    rest = alive(snap)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in rest:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        if sig == signal.SIGTERM and rest:
            time.sleep(1.5)
            rest = alive(snap)
        if not rest:
            break

    subprocess.run([os.path.expanduser("~/.config/tmux/scripts/radar/radar-scan")], capture_output=True)
    msg = "Cerrado %s · %d Claude · %d procesos" % (
        {"pane": "pane", "window": "ventana", "session": "sesión"}[scope], len(claudes), len(snap))
    if rest:
        msg += " · %d forzados" % len(rest)
    if worktrees:
        msg += " · worktree conservado (wm rm <repo> <tarea> para borrarlo)"
    say(msg)


if __name__ == "__main__":
    main()
