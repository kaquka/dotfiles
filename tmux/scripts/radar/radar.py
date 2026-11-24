#!/usr/bin/env python3
"""claude-radar: detecta sesiones de Claude Code y servidores locales por pane de tmux.

`radar.py scan` calcula el estado de cada pane y publica opciones que usa tmux.conf:
  sesión  @radar_l0 / @radar_l1   las dos filas de pestañas tarjeta
  global  @radar_sum              resumen ◆ ● ○ ▲
  pane    @pane_bar               barra de título del pane (pane-border-format)
  pane    @radar_state/@radar_since  estado anterior y desde cuándo (para edades)
mission.py importa collect() de aquí para el tablero.

Compatible con /usr/bin/python3 (3.9).
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

TMUX = "/opt/homebrew/bin/tmux"
CACHE = os.path.expanduser("~/.cache/claude-radar")
EVENTS = os.path.join(CACHE, "events.log")
SHELLS = {"fish", "zsh", "bash", "sh", "-fish", "-zsh", "-bash", "login"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
WORKING_RE = re.compile(r"esc to interrupt")
NOISE_RE = re.compile(
    r"Update installed|Auto-update|/clear to save|ctrl\+b|How is Claude doing|1: Bad|Jump to bottom"
    r"|^\s*[✻✽✢✶✳·*]\s+\S+…|esc to interrupt|Restart to update")
WAITING_RE = re.compile(r"Do you want to |❯ 1\. Yes|Would you like to proceed")

C = dict(
    bar="#202020", card="#262626", card_on="#3a3a3a", card_wait="#4a1717", card_wait_on="#5c1f1f",
    fg="#d0d0d0", dim="#777777", faint="#4a4a4a", white="#f2f2f2",
    work="#e8a33d", work_bg="#3a2a10", work_hi="#f5c06a", work_dark="#1d1200",
    wait="#ff6464", wait_bg="#4a1717", wait_hi="#ffb3b3", wait_dark="#1a0000",
    idle="#8c8c8c", idle_bg="#2a2a2a", idle_st="#3a3a3a",
    done="#62c48a", done_bg="#14301f", done_hi="#a8e6c0", done_dark="#04210f", card_done="#17301f",
    card_done_on="#1f4029",
    srv="#5fb3dc", srv_bg="#11303f", srv_hi="#a9dcf3", srv_dark="#04202d", ok="#62c48a",
)
GLYPH = {"waiting": "◆", "done": "◉", "working": "●", "idle": "○", "srv": "▲", "down": "✗"}
RANK = {"waiting": 6, "down": 5, "done": 4, "working": 3, "srv": 2, "idle": 1}

FIELDS = [
    "pane_id", "session_name", "window_id", "window_index", "window_active", "window_name",
    "pane_index", "pane_active", "pane_pid", "pane_title", "pane_current_command",
    "pane_current_path", "pane_width", "window_width", "window_panes", "history_size",
    "pane-border-status",
    "@claude_state", "@claude_doing", "@claude_msg", "@claude_ts", "@radar_state", "@radar_since",
    "@srv_last_port", "@radar_unread", "@radar_sidebar", "@srv_task", "@pane_bar",
]
SIDEBARS = []  # panes de la barra lateral (se excluyen del radar)
BARS = {}  # @pane_bar actual por pane (para no reescribirlo si no cambió)
STATE = os.path.join(CACHE, "state.json")
SEP = "\x1f"


# ---------------------------------------------------------------- utilidades
def run(args, timeout=3):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def tmux(*args):
    return run([TMUX, *args])


def width(s):
    n = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def fit(s, n, pad=True):
    """Recorta a n columnas con … y rellena con espacios."""
    if n <= 0:
        return ""
    if width(s) > n:
        out = ""
        for ch in s:
            if width(out + ch) > n - 1:
                break
            out += ch
        s = out + "…"
    return s + " " * (n - width(s)) if pad else s


def clean(s):
    # '#' se interpretaría como formato/estilo de tmux.
    return (s or "").replace("#", "＃").replace("\n", " ").strip()


def human(secs):
    if secs is None:
        return ""
    secs = int(max(0, secs))
    if secs < 60:
        return "%ds" % secs
    if secs < 3600:
        return "%dm" % (secs // 60)
    if secs < 86400:
        return "%dh%02dm" % (secs // 3600, secs % 3600 // 60)
    return "%dd%dh" % (secs // 86400, secs % 86400 // 3600)


def etime_secs(s):
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return days * 86400 + h * 3600 + m * 60 + sec


def topic_of(title):
    title = (title or "").strip()
    if title and not title[0].isalnum():
        title = re.sub(r"^\S+\s*", "", title)
    return title


STOP = {"de", "del", "la", "el", "los", "las", "en", "con", "para", "por", "y", "a", "al", "un", "una",
        "the", "of", "for", "to", "in", "and", "on", "worktree"}
# Prefijos de repos/servicios a recortar en los títulos, p. ej. RADAR_STRIP_PREFIXES="acme- my-"
STRIP_PREFIXES = tuple(os.environ.get("RADAR_STRIP_PREFIXES", "").split())
STOP |= {p.strip("-").lower() for p in STRIP_PREFIXES}
ABBR = {"configuración": "config", "configuracion": "config", "integración": "integ",
        "integracion": "integ", "migración": "migr", "migracion": "migr", "requisitos": "reqs",
        "producto": "prod", "hacia": "→", "implementación": "impl",
        "documentación": "docs", "validación": "valid", "notificaciones": "notifs",
        "development": "dev", "production": "prod", "environment": "env"}


def short_topic(t):
    """'PR 442 de acme-billing-svc' -> 'PR442 billing' (con RADAR_STRIP_PREFIXES="acme-")."""
    t = re.sub(r"\bPR\s+#?(\d+)", r"PR\1", t or "")
    out = []
    for w in t.split():
        lw = w.lower()
        if lw in STOP:
            continue
        w = ABBR.get(lw, w)
        if "/" in w and not w.startswith("http"):
            w = w.rstrip("/").split("/")[-1]
        for pre in STRIP_PREFIXES:
            if w.startswith(pre):
                w = w[len(pre):]
                break
        w = re.sub(r"-(svc|service|api|bff)$", "", w)
        out.append(w)
    return " ".join(out).replace(" → ", "→") or t


# ---------------------------------------------------------------- procesos
def proc_table():
    procs, children = {}, {}
    for line in run(["ps", "-axo", "pid=,ppid=,etime=,comm="]).splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        procs[pid] = (ppid, parts[2], os.path.basename(parts[3]))
        children.setdefault(ppid, []).append(pid)
    return procs, children


def descendants(pid, children):
    out, stack = [pid], [pid]
    while stack:
        for c in children.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def _cached(name, ttl, fn):
    path = os.path.join(CACHE, name)
    try:
        if time.time() - os.path.getmtime(path) < ttl:
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    data = fn()
    try:
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass
    return data


def listening():
    """{pid: [puertos]} de procesos escuchando TCP (cache 6s)."""
    def scan():
        out, pid = {}, None
        for line in run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"], timeout=5).splitlines():
            if line.startswith("p"):
                pid = line[1:]
            elif line.startswith("n") and pid:
                port = line.rsplit(":", 1)[-1]
                if port.isdigit():
                    out.setdefault(pid, [])
                    if int(port) not in out[pid]:
                        out[pid].append(int(port))
        return out
    return {int(k): sorted(v) for k, v in _cached("listen.json", 6, scan).items()}


def _check(port):
    """Connect TCP sin enviar nada: no ensucia los logs del servidor."""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.8):
                return True
        except (socket.timeout, TimeoutError):
            return False
        except OSError:
            continue
    return False


def health(ports):
    path = os.path.join(CACHE, "health.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
    now = time.time()
    stale = [p for p in ports if now - data.get(str(p), [None, 0])[1] > 10]
    if stale:
        with ThreadPoolExecutor(max_workers=len(stale)) as ex:
            for p, ok in zip(stale, ex.map(_check, stale)):
                data[str(p)] = [ok, now]
        try:
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception:
            pass
    return {p: data.get(str(p), [None])[0] for p in ports}


def capture(pane_id):
    return tmux("capture-pane", "-p", "-t", pane_id).rstrip("\n").splitlines()


def claude_body(lines):
    """Líneas de conversación arriba de la caja de entrada de Claude."""
    seps = [i for i, l in enumerate(lines) if l.strip().startswith("─────")]
    cut = seps[-2] if len(seps) >= 2 else len(lines)
    return [l.rstrip() for l in lines[:cut] if l.strip() and not NOISE_RE.search(l)]


# ---------------------------------------------------------------- recolección
def collect(with_screen=False):
    fmt = SEP.join("#{%s}" % f for f in FIELDS)
    rows = [dict(zip(FIELDS, l.split(SEP))) for l in tmux("list-panes", "-a", "-F", fmt).splitlines()]
    procs, children = proc_table()
    listen = listening()
    now = time.time()
    viewed_sessions = set(tmux("list-clients", "-F", "#{client_session}").split())
    panes, ports_needed = [], set()
    del SIDEBARS[:]
    BARS.clear()
    for p in rows:
        BARS[p["pane_id"]] = p["@pane_bar"]
        if p["@radar_sidebar"] == "1":
            SIDEBARS.append(p["pane_id"])
    rows = [p for p in rows if p["@radar_sidebar"] != "1"]
    per_win = {}
    for p in rows:
        per_win[p["window_id"]] = per_win.get(p["window_id"], 0) + 1
    for p in rows:
        p["window_panes"] = str(per_win[p["window_id"]])

    for p in rows:
        try:
            pid = int(p["pane_pid"])
        except ValueError:
            continue
        desc = descendants(pid, children)
        names = [procs[d][2] for d in desc if d in procs]
        is_claude = any(VERSION_RE.match(n) or n == "claude" for n in names) or bool(p["@claude_state"])
        d = dict(
            id=p["pane_id"], session=p["session_name"], window_id=p["window_id"],
            win=int(p["window_index"]), win_active=p["window_active"] == "1", window_name=p["window_name"],
            pane=int(p["pane_index"]), pane_active=p["pane_active"] == "1",
            title=p["pane_title"], cmd=p["pane_current_command"], path=p["pane_current_path"],
            repo=os.path.basename(p["pane_current_path"].rstrip("/")) or "~",
            pane_width=int(p["pane_width"] or 80), window_width=int(p["window_width"] or 200),
            window_panes=int(p["window_panes"] or 1), history=int(p["history_size"] or 0),
            border_status=p["pane-border-status"],
            prev=p["@radar_state"], since=float(p["@radar_since"] or 0) or None,
            last_port=p["@srv_last_port"], topic="", doing="", msg="", port=None, ports=[],
            healthy=None, uptime=None, task="", tail=[], kind="other", state=None, srv_task=p["@srv_task"],
        )
        if is_claude:
            d["kind"] = "claude"
            d["topic"] = topic_of(p["pane_title"])
            lines = capture(d["id"])
            bottom = "\n".join(lines[-40:])
            hook = p["@claude_state"]
            if WAITING_RE.search(bottom):
                st = "waiting"
            elif WORKING_RE.search(bottom):
                st = "working"
            elif hook == "waiting":
                st = "waiting"
            else:
                st = "idle"
            viewed = p["session_name"] in viewed_sessions and p["window_active"] == "1" and p["pane_active"] == "1"
            unread = p["@radar_unread"] == "1"
            if st == "idle":
                if p["@radar_state"] in ("claude:working", "claude:waiting") and not viewed:
                    unread = True
                if viewed:
                    unread = False
                if unread:
                    st = "done"
            else:
                unread = False
            d["unread"], d["unread_prev"] = unread, p["@radar_unread"] == "1"
            d["state"] = st
            body = claude_body(lines)
            d["tail"] = body[-4:]
            screen_doing = ""
            for l in reversed(body):
                if l.startswith("⏺ "):
                    screen_doing = l[2:].strip()
                    break
            hook_fresh = p["@claude_ts"] and now - float(p["@claude_ts"] or 0) < 900
            d["doing"] = (p["@claude_doing"] if hook_fresh and p["@claude_doing"] else screen_doing)
            d["msg"] = p["@claude_msg"] if st == "waiting" else ""
            if st == "waiting" and not d["msg"]:
                m = re.search(r"(Bash|Edit|Write|Update|Read|Fetch|WebFetch)\(([^)]{0,60})", bottom)
                d["msg"] = "permiso " + (m.group(0) if m else "pendiente")
        else:
            ports = sorted({pt for x in desc for pt in listen.get(x, [])})
            if p["pane_title"].startswith("mise run "):
                d["task"] = p["pane_title"][9:].split()[0]
            elif p["@srv_task"]:
                d["task"] = p["@srv_task"]  # el título ya es el nuestro (▲ :puerto · tarea)
            else:
                d["task"] = p["pane_current_command"]
            if ports:
                d["kind"], d["state"], d["ports"], d["port"] = "srv", "srv", ports, ports[0]
                ports_needed.update(ports[:1])
                lp = [x for x in desc if ports[0] in listen.get(x, [])]
                if lp and lp[0] in procs:
                    d["uptime"] = etime_secs(procs[lp[0]][1])
                    if d["task"] in SHELLS:
                        d["task"] = os.path.basename(procs[lp[0]][2])  # el shell solo envuelve: nombra el proceso que escucha
            elif p["@srv_last_port"] and p["pane_current_command"] not in SHELLS:
                d["kind"], d["state"], d["port"] = "down", "down", int(p["@srv_last_port"])
            if with_screen and d["kind"] in ("srv", "down"):
                d["tail"] = [l for l in capture(d["id"]) if l.strip()][-3:]
        key = "%s:%s" % (d["kind"], d["state"])
        d["changed"] = key != d["prev"]
        if d["changed"] or not d["since"]:
            d["since"] = now
        d["key"] = key
        d["age"] = now - d["since"]
        panes.append(d)

    hl = health(sorted(ports_needed)) if ports_needed else {}
    for d in panes:
        if d["kind"] == "srv":
            d["healthy"] = hl.get(d["port"])
    return panes


# ---------------------------------------------------------------- render tmux
def win_summary(panes):
    best = max(panes, key=lambda d: RANK.get(d["state"], 0))
    edge = best["state"]
    act = next((d for d in panes if d["pane_active"]), panes[0])
    claudes = [d for d in panes if d["kind"] == "claude"]
    if act["kind"] == "claude" or not claudes:
        pick = act if act["kind"] != "other" or not claudes else claudes[0]
    else:
        pick = max(claudes, key=lambda d: RANK.get(d["state"], 0))
    if pick["kind"] == "claude":
        topic = short_topic(pick["topic"]) or pick["repo"]
    elif pick["kind"] in ("srv", "down"):
        topic = "%s %s" % (pick["repo"], pick["task"])
    else:
        topic = pick["repo"]
    return edge, clean(topic)


def chip(d, n=10):
    if d["kind"] == "claude":
        color = {"waiting": C["wait"], "working": C["work"], "done": C["done"]}.get(d["state"], C["idle"])
        label = "espera" if d["state"] == "waiting" else (short_topic(d["topic"]) or d["repo"])
        return GLYPH[d["state"]] + (fit(clean(label), n, pad=False) if n else ""), color
    if d["kind"] == "srv":
        return "▲%s" % d["port"], C["srv"]
    if d["kind"] == "down":
        return "✗%s" % d["port"], C["wait"]
    return None


def card(win_idx, panes, cw, active):
    edge, topic = win_summary(panes)
    ecol = {"waiting": C["wait"], "down": C["wait"], "working": C["work"], "srv": C["srv"], "done": C["done"],
            "idle": C["idle"]}.get(edge, C["faint"])
    if edge in ("waiting", "down"):
        bg = C["card_wait_on"] if active else C["card_wait"]
    elif edge == "done":
        bg = C["card_done_on"] if active else C["card_done"]
    else:
        bg = C["card_on"] if active else C["card"]
    tfg = C["white"] if active else C["fg"]
    bold = "bold" if active else "nobold"
    rng = "#[range=window|%d]" % win_idx
    inner = cw - 1
    r0 = "%s#[bg=%s,fg=%s]▌#[fg=%s,%s]%s#[nobold,fg=%s]%s" % (
        rng, bg, ecol, C["dim"], bold, " %d " % win_idx, tfg, fit(topic, inner - width(" %d " % win_idx)))
    room = inner - 1
    ordered = sorted(panes, key=lambda d: d["pane"])
    for n in (10, 8, 6, 4, 3, 0):
        chips = [c for c in (chip(d, n) for d in ordered) if c]
        if sum(width(t) for t, _ in chips) + len(chips) - 1 <= room:
            break
    used, parts = 0, []
    for i, (txt, col) in enumerate(chips):
        need = width(txt) + (1 if parts else 0)
        rest = len(chips) - i - 1
        if used + need + (3 if rest else 0) > room:
            more = "+%d" % (len(chips) - i)
            parts.append("#[fg=%s] %s" % (C["dim"], more))
            used += width(more) + 1
            break
        parts.append(("#[fg=%s]" % col) + (" " if parts else "") + txt)
        used += need
    r1 = "%s#[bg=%s,fg=%s]▌#[nobold] %s%s" % (rng, bg, ecol, "".join(parts), " " * max(0, room - used))
    tail = "#[norange]#[bg=%s] " % C["bar"]
    return r0 + tail, r1 + tail


def sess_label(name):
    return fit(name, 10, pad=False)


def session_lines(spanes):
    wins = {}
    for d in spanes:
        wins.setdefault(d["win"], []).append(d)
    order = sorted(wins)
    active = next((d["win"] for d in spanes if d["win_active"]), order[0])
    total = next((d["window_width"] for d in spanes if d["win_active"]), 200)
    avail = total - (width(sess_label(spanes[0]["session"])) + 3) - 14
    n = len(order)
    cw = max(14, min(30, avail // n - 1))
    shown = order
    if (cw + 1) * n > avail:
        k = max(1, avail // (cw + 1))
        i = order.index(active)
        start = max(0, min(i - k // 2, n - k))
        shown = order[start:start + k]
    l0, l1 = "", ""
    if shown[0] != order[0]:
        hid = order.index(shown[0])
        l0 += "#[fg=%s]‹%d " % (C["dim"], hid)
        l1 += " " * (width("‹%d " % hid))
    for w in shown:
        a, b = card(w, wins[w], cw, w == active)
        l0 += a
        l1 += b
    if shown[-1] != order[-1]:
        l0 += "#[fg=%s]%d›" % (C["dim"], n - order.index(shown[-1]) - 1)
    return l0, l1


def pane_bar(d):
    w = max(10, d["pane_width"] - 1)
    if d["kind"] == "claude":
        st = d["state"]
        age = human(d["age"])
        if st == "waiting":
            head, hs, rs = " ◆ ESPERA %s " % age, (C["wait"], C["wait_dark"]), (C["wait_bg"], C["wait_hi"])
            rest = d["msg"] or d["topic"]
            rest = "%s │ %s" % (rest, d["topic"]) if d["msg"] else rest
        elif st == "done":
            head, hs, rs = " ◉ TERMINÓ %s " % age, (C["done"], C["done_dark"]), (C["done_bg"], C["done_hi"])
            rest = d["topic"] + " │ sin revisar"
        elif st == "working":
            head, hs, rs = " ● TRABAJANDO %s " % age, (C["work"], C["work_dark"]), (C["work_bg"], C["work_hi"])
            rest = d["topic"] + (" │ " + d["doing"] if d["doing"] else "")
        else:
            head, hs, rs = " ○ LISTO %s " % age, (C["idle_st"], C["fg"]), (C["idle_bg"], C["dim"])
            rest = d["topic"]
    elif d["kind"] == "srv":
        ok = d["healthy"]
        mark = "✓" if ok else ("✗" if ok is False else "…")
        head, hs, rs = " ▲ :%s " % d["port"], (C["srv"], C["srv_dark"]), (C["srv_bg"], C["srv_hi"])
        rest = "%s │ %s │ %s %s" % (d["repo"], d["task"], mark, human(d["uptime"]))
        if len(d["ports"]) > 1:
            rest += " │ +" + ",".join(str(x) for x in d["ports"][1:4])
    elif d["kind"] == "down":
        head, hs, rs = " ✗ :%s CAÍDO " % d["port"], (C["wait"], C["wait_dark"]), (C["wait_bg"], C["wait_hi"])
        rest = "%s │ %s" % (d["repo"], d["task"])
    else:
        return "#[fg=%s] %s · %s " % (C["faint"], clean(d["cmd"]), clean(d["repo"]))
    rest = " " + clean(rest)
    return "#[bg=%s,fg=%s,bold]%s#[bg=%s,fg=%s,nobold]%s#[default]" % (
        hs[0], hs[1], head, rs[0], rs[1], fit(rest, w - width(head)))

# ---------------------------------------------------------------- workmux
# Registra en el panel de workmux lo que sus hooks no ven:
#   - servidores (▲ arriba = sin estado, ✗ caído = "waiting", rojo)
#   - Claude abiertos antes de instalar los hooks de workmux
# Usa el formato interno de ~/.local/state/workmux/agents/*.json (no es API pública):
# workmux descarta un registro si el comando del pane deja de coincidir con "command".
# Solo se tocan registros creados aquí (lista en wm-owned.json).
WM_AGENTS = os.path.expanduser("~/.local/state/workmux/agents")
WM_OWNED = os.path.join(CACHE, "wm-owned.json")
WM_STATUS = {"waiting": "waiting", "working": "working", "done": "done", "down": "waiting"}


def srv_title(d):
    if d["kind"] == "srv":
        mark = "" if d["healthy"] is not False else " · no responde"
        return ":%s · %s%s" % (d["port"], d["task"] or d["cmd"], mark)
    return ":%s · %s caído" % (d["port"], d["task"] or d["cmd"])


def wm_sync(panes):
    if not os.path.isdir(WM_AGENTS):
        return
    info = tmux("display", "-p", "#{socket_path}\t#{start_time}:#{pid}").strip().split("\t")
    if len(info) != 2:
        return
    sock, boot = info
    enc = lambda pid: "tmux__%s__%s.json" % (sock.replace("/", "%2F"), pid.replace("%", "%25"))
    try:
        owned = json.load(open(WM_OWNED))
    except Exception:
        owned = {}
    keep, changed = {}, False
    for d in panes:
        f = os.path.join(WM_AGENTS, enc(d["id"]))
        mine = d["id"] in owned
        if d["kind"] in ("srv", "down"):
            # workmux solo pinta iconos de agentes conocidos: grok/copilot = ▲ azul / ✗ rojo (agent_icons)
            kind = "grok" if d["kind"] == "srv" else "copilot"
            status, title = WM_STATUS.get(d["state"]), srv_title(d)
        elif d["kind"] == "claude":
            if not mine and os.path.exists(f):
                continue  # lo maneja workmux con sus hooks
            if mine:
                try:
                    if json.load(open(f)).get("agent_session_id"):
                        continue  # ya llegaron los hooks de workmux: se lo cedemos
                except Exception:
                    pass
            kind, status, title = "claude", WM_STATUS.get(d["state"]), d["title"]
        else:
            continue
        if not mine and os.path.exists(f):
            continue
        sig = "%s|%s|%s|%s" % (kind, status, title, d["cmd"])
        keep[d["id"]] = sig
        if owned.get(d["id"]) == sig and os.path.exists(f):
            continue
        ts = int(d["since"] or time.time())
        rec = {
            "pane_key": {"backend": "tmux", "instance": sock, "pane_id": d["id"]},
            "workdir": d["path"], "status": status, "status_ts": ts, "activity_ts": int(time.time()),
            "pane_title": title, "pane_pid": int(tmux("display", "-p", "-t", d["id"], "#{pane_pid}").strip() or 0),
            "command": d["cmd"], "updated_ts": int(time.time()), "window_name": d["window_name"],
            "session_name": d["session"], "boot_id": boot, "agent_kind": kind,
        }
        tmp = f + ".radar.tmp"
        with open(tmp, "w") as fh:
            json.dump(rec, fh)
        os.replace(tmp, f)
        changed = True
    for pid in set(owned) - set(keep):
        try:
            os.remove(os.path.join(WM_AGENTS, enc(pid)))
            changed = True
        except OSError:
            pass
    if keep != owned:
        with open(WM_OWNED, "w") as fh:
            json.dump(keep, fh)
    if changed:
        subprocess.run(["pkill", "-USR1", "-f", "workmux _sidebar-daemon"], capture_output=True)


def summary(panes):
    cnt = {}
    for d in panes:
        if d["state"]:
            cnt[d["state"]] = cnt.get(d["state"], 0) + 1
    out = []
    for st, col in (("waiting", C["wait"]), ("done", C["done"]), ("working", C["work"]), ("idle", C["idle"]),
                    ("srv", C["srv"]), ("down", C["wait"])):
        if cnt.get(st):
            out.append("#[fg=%s]%s%d" % (col, GLYPH[st], cnt[st]))
    return " ".join(out)


def log_events(panes):
    lines = ["%d %s %s\n" % (time.time(), d["id"], d["state"])
             for d in panes if d["changed"] and d["kind"] == "claude"]
    if not lines:
        return
    try:
        with open(EVENTS, "a") as f:
            f.writelines(lines)
        if os.path.getsize(EVENTS) > 400_000:
            with open(EVENTS) as f:
                keep = f.readlines()[-2000:]
            with open(EVENTS, "w") as f:
                f.writelines(keep)
    except Exception:
        pass


def scan(soft=False):
    os.makedirs(CACHE, exist_ok=True)
    stamp = os.path.join(CACHE, "scan.stamp")
    try:
        if soft and time.time() - os.path.getmtime(stamp) < 1.0:
            return
    except OSError:
        pass
    open(stamp, "w").close()

    panes = collect()
    cmds = []

    def add(*a):
        if cmds:
            cmds.append(";")
        cmds.extend(a)

    for d in panes:
        # Solo si cambió: cada `set` repinta la pantalla completa de todos los clientes.
        bar = pane_bar(d)
        if BARS.get(d["id"]) != bar:
            add("set", "-p", "-t", d["id"], "@pane_bar", bar)
        if d["changed"]:
            add("set", "-p", "-t", d["id"], "@radar_state", d["key"])
            add("set", "-p", "-t", d["id"], "@radar_since", str(int(d["since"])))
        if d["kind"] == "srv" and d["last_port"] != str(d["port"]):
            add("set", "-p", "-t", d["id"], "@srv_last_port", str(d["port"]))
        if d.get("unread") and not d.get("unread_prev"):
            add("set", "-p", "-t", d["id"], "@radar_unread", "1")
        if not d.get("unread") and d.get("unread_prev"):
            add("set", "-pu", "-t", d["id"], "@radar_unread")
        if d["kind"] == "other" and d["last_port"]:
            add("set", "-pu", "-t", d["id"], "@srv_last_port")
    seen = set()
    for d in panes:
        if d["window_id"] in seen:
            continue
        seen.add(d["window_id"])
        want = "top" if d["window_panes"] > 1 else "off"
        if d["border_status"] != want:
            add("set", "-w", "-t", d["window_id"], "pane-border-status", want)
    # (2026-11-23) las pestañas tarjeta se retiraron: el estado por agente vive en el panel de workmux.
    for d in panes:
        if d["kind"] in ("srv", "down"):
            want = srv_title(d)
            if d["title"] != want:
                add("select-pane", "-t", d["id"], "-T", want)
            if d["task"] and d["srv_task"] != d["task"]:
                add("set", "-p", "-t", d["id"], "@srv_task", d["task"])
        elif d["srv_task"]:
            add("set", "-pu", "-t", d["id"], "@srv_task")
    for sid in SIDEBARS:
        bar = "#[fg=%s,bold] RADAR #[default]" % C["faint"]
        if BARS.get(sid) != bar:
            add("set", "-p", "-t", sid, "@pane_bar", bar)
    sm = summary(panes)
    if tmux("show", "-gv", "@radar_sum").rstrip("\n") != sm:
        add("set", "-g", "@radar_sum", sm)
    add("refresh-client", "-S")
    if cmds:
        run([TMUX, *cmds])
    log_events(panes)
    try:
        wm_sync(panes)
    except Exception:
        pass
    try:
        tmp = "%s.%d.tmp" % (STATE, os.getpid())
        with open(tmp, "w") as f:
            json.dump({"ts": time.time(), "panes": panes}, f)
        os.replace(tmp, STATE)
    except Exception:
        pass


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        scan(soft="--soft" in sys.argv)
    elif cmd == "dump":
        for d in collect():
            print(d["id"], d["session"], "%d.%d" % (d["win"], d["pane"]), d["kind"], d["state"],
                  human(d["age"]), d["port"] or "", "|", d["topic"] or d["task"], "|", d["doing"][:50])
