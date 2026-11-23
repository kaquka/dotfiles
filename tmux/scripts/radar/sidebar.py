#!/usr/bin/env python3
"""Barra lateral de claude-radar: árbol sesión → ventana → pane, siempre visible.

La lanza radar-sidebar.sh (prefix b). Lee ~/.cache/claude-radar/state.json, que
escribe el escáner cada 2 s; no consulta tmux por su cuenta salvo para saber en
qué ventana está. Compatible con /usr/bin/python3 (3.9).
"""
import json
import os
import re
import select
import signal
import subprocess
import sys
import termios
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import radar  # noqa: E402
import prt_view  # noqa: E402

C = radar.C
R = "\033[0m"
B = "\033[1m"


def fg(h):
    h = h.lstrip("#")
    return "\033[38;2;%d;%d;%dm" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bg(h):
    h = h.lstrip("#")
    return "\033[48;2;%d;%d;%dm" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


STATE_COL = {"waiting": C["wait"], "done": C["done"], "working": C["work"], "idle": C["idle"],
             "srv": C["srv"], "down": C["wait"]}
FAINT, DIM, WHITE = fg(C["faint"]), fg(C["dim"]), fg(C["white"])


def where():
    out = subprocess.run([radar.TMUX, "display", "-p", "-t", os.environ.get("TMUX_PANE", ""),
                          "#{session_name}\t#{window_index}"], capture_output=True, text=True).stdout
    parts = out.strip().split("\t")
    return (parts[0], int(parts[1])) if len(parts) == 2 and parts[1].isdigit() else ("", -1)


def row(left, right, W, left_plain, right_plain, hl=None):
    """Arma una línea con texto a la izquierda y a la derecha, rellenando con espacios."""
    gap = W - radar.width(left_plain) - radar.width(right_plain)
    line = left + " " * max(1, gap) + right
    return (bg(hl) + line.replace(R, R + bg(hl)) + R) if hl else line


def render(state, W, H, here):
    panes = state.get("panes", [])
    now = time.time()
    lines, targets = [], []

    def add(line, target=None):
        lines.append(line)
        targets.append(target)

    cnt = {}
    for d in panes:
        if d.get("state"):
            cnt[d["state"]] = cnt.get(d["state"], 0) + 1
    sum_plain, sum_col = "", ""
    for st in ("waiting", "done", "working", "idle", "srv", "down"):
        if cnt.get(st):
            t = "%s%d " % (radar.GLYPH[st], cnt[st])
            sum_plain += t
            sum_col += fg(STATE_COL[st]) + t + R
    add(row(WHITE + B + " RADAR" + R, sum_col, W, " RADAR", sum_plain))
    add(FAINT + "─" * W + R)

    sessions = {}
    for d in panes:
        sessions.setdefault(d["session"], {}).setdefault(d["win"], []).append(d)
    order = sorted(sessions, key=lambda s: (s != here[0], s))
    for s in order:
        add(WHITE + B + " " + radar.fit(s, W - 1, pad=False) + R)
        wins = sessions[s]
        widx = sorted(wins)
        for wi, w in enumerate(widx):
            last_w = wi == len(widx) - 1
            ps = sorted(wins[w], key=lambda d: d["pane"])
            edge, topic = radar.win_summary(ps)
            ecol = STATE_COL.get(edge, C["faint"])
            cur = (s, w) == here
            br = " └ " if last_w else " ├ "
            left_plain = "%s%d %s" % (br, w, topic)
            right_plain = "◂ " if cur else ""
            left_plain = radar.fit(left_plain, W - len(right_plain) - 1, pad=False)
            txt = left_plain[len(br):]
            left = FAINT + br + R + fg(ecol) + B + txt.split(" ", 1)[0] + R + \
                (WHITE + B if cur else fg(C["fg"])) + (" " + txt.split(" ", 1)[1] if " " in txt else "") + R
            add(row(left, DIM + right_plain + R, W, left_plain, right_plain,
                    hl="#2c2c2c" if cur else None), "%s:%d" % (s, w))
            shown = [d for d in ps if d["kind"] != "other"]
            stem = "   " if last_w else " │ "
            for pi, d in enumerate(shown):
                last_p = pi == len(shown) - 1
                pb = "└ " if last_p else "├ "
                cont = "  " if last_p else "│ "
                st = d["state"]
                col = fg(STATE_COL.get(st, C["dim"]))
                if d["kind"] == "claude":
                    label = radar.short_topic(d.get("topic", "")) or d.get("repo", "")
                    right = radar.human(now - (d.get("since") or now))
                    rcol = col if st in ("waiting", "done", "working") else DIM
                    sub, subcol = "", DIM
                    if st == "working" and d.get("doing"):
                        sub = d["doing"]
                    elif st == "waiting":
                        sub, subcol = d.get("msg") or "espera tu respuesta", col
                    elif st == "done":
                        sub, subcol = "terminó · sin revisar", col
                elif d["kind"] == "srv":
                    label = ":%s %s" % (d["port"], d.get("repo", ""))
                    ok = d.get("healthy")
                    right = "✓" if ok else ("✗" if ok is False else "…")
                    rcol = fg(C["ok"]) if ok else fg(C["wait"])
                    sub, subcol = "", DIM
                else:
                    label = ":%s caído" % d.get("port")
                    right, rcol, sub, subcol = "✗", col, d.get("task", ""), DIM
                prefix = stem + pb
                glyph = radar.GLYPH.get(st, "·") + " "
                room = W - radar.width(prefix) - radar.width(glyph) - radar.width(right) - 1
                lab = radar.fit(label, room, pad=False)
                lp = prefix + glyph + lab
                add(row(FAINT + prefix + R + col + glyph + R + fg(C["fg"]) + lab + R,
                        rcol + right + R, W, lp, right), d["id"])
                if sub:
                    sp = stem + cont + "  "
                    add(FAINT + sp + R + subcol +
                        radar.fit(radar.clean(sub), W - radar.width(sp), pad=False) + R, d["id"])
        add("")

    foot = " clic: ir · tab PRs · b ocultar · a panel"
    n = max(1, H - 1)
    body, tg = lines[:n], targets[:n]
    body += [""] * (n - len(body))
    tg += [None] * (n - len(tg))
    body.append(FAINT + radar.fit(foot, W, pad=False) + R)
    tg.append(None)
    return body, tg


def jump(target):
    """target = pane id (%12) o 'sesion:ventana'."""
    log = os.environ.get("RADAR_SIDEBAR_LOG")
    if log:
        with open(log, "a") as f:
            f.write(target + "\n")
        return
    if target.startswith("%"):
        cmd = ["switch-client", "-t", target, ";", "select-window", "-t", target, ";",
               "select-pane", "-t", target]
    else:
        cmd = ["switch-client", "-t", target, ";", "select-window", "-t", target]
    subprocess.run([radar.TMUX, *cmd], capture_output=True)


MOUSE_RE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
KEYS = {b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT", b"\x1b[D": "LEFT", b"\x1b[Z": "BTAB",
        b"\x1bOA": "UP", b"\x1bOB": "DOWN", b"\x1bOC": "RIGHT", b"\x1bOD": "LEFT"}


def parse(buf):
    """Separa el buffer en eventos: ("mouse", btn, x, y, kind) o ("key", k). Devuelve (eventos, resto)."""
    ev = []
    while buf:
        if buf.startswith(b"\x1b[<"):
            m = MOUSE_RE.match(buf)
            if not m:
                if len(buf) > 32:
                    buf = b""
                break
            ev.append(("mouse", int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)))
            buf = buf[m.end():]
            continue
        hit = next((k for k in KEYS if buf.startswith(k)), None)
        if hit:
            ev.append(("key", KEYS[hit]))
            buf = buf[len(hit):]
            continue
        if buf.startswith(b"\x1b"):
            if len(buf) == 1:
                ev.append(("key", "ESC"))
                buf = b""
                break
            if buf[1:2] in (b"[", b"O") and len(buf) < 3:
                break
            buf = buf[1:]   # secuencia desconocida: se descarta el ESC
            continue
        ch = buf[:1].decode("latin-1")
        ev.append(("key", ch))
        buf = buf[1:]
    return ev, buf


def leave():
    """Esc: regresa el foco al panel donde estabas."""
    if subprocess.run([radar.TMUX, "select-pane", "-l"], capture_output=True).returncode != 0:
        subprocess.run([radar.TMUX, "select-pane", "-L"], capture_output=True)


def main():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    # 1000: clics y rueda · 1006: coordenadas SGR
    sys.stdout.write("\033[?25l\033[?1000h\033[?1006h")

    def restore(*_):
        sys.stdout.write("\033[?1000l\033[?1006l\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.exit(0)

    signal.signal(signal.SIGTERM, restore)
    signal.signal(signal.SIGHUP, restore)
    ui = prt_view.UI()
    last_where = (0, ("", -1))
    targets, buf = [], b""
    next_draw = 0
    try:
        while True:
            now = time.time()
            if ui.check_request():
                next_draw = 0
            if now >= next_draw:
                try:
                    W, H = os.get_terminal_size()
                except OSError:
                    W, H = 36, 40
                if ui.tab == "claude":
                    if now - last_where[0] > 2:
                        last_where = (now, where())
                    try:
                        with open(radar.STATE) as f:
                            state = json.load(f)
                    except Exception:
                        state = {"panes": []}
                    out, tg = render(state, W, H - 1, last_where[1])
                    out = [prt_view.tab_bar(ui, W)] + out
                    targets = [("tabs", None)] + tg
                else:
                    out, targets = prt_view.render(ui, W, H)
                sys.stdout.write("\033[H" + "\n".join(l + "\033[K" for l in out) + "\033[J")
                sys.stdout.flush()
                next_draw = now + 1
            r, _, _ = select.select([fd], [], [], max(0.05, min(0.5, next_draw - time.time())))
            if not r:
                continue
            buf += os.read(fd, 1024)
            if buf == b"\x1b":
                # un Esc suelto o el inicio de una secuencia: se espera un instante
                r2, _, _ = select.select([fd], [], [], 0.03)
                if r2:
                    buf += os.read(fd, 1024)
            events, buf = parse(buf)
            for e in events:
                if e[0] == "key":
                    if e[1] == "ESC":
                        leave()
                    elif prt_view.key(ui, e[1]):
                        next_draw = 0
                    continue
                _, button, x, y, kind = e
                if kind != b"M":
                    continue
                t = targets[y - 1] if 0 < y <= len(targets) else None
                if ui.tab == "claude" and isinstance(t, str) and button == 0:
                    jump(t)
                    last_where = (0, last_where[1])
                    next_draw = 0
                elif button in (0, 64, 65) and prt_view.click(ui, x, y, targets, button):
                    next_draw = 0
    finally:
        restore()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
