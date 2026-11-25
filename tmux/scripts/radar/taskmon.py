# /// script
# requires-python = ">=3.10"
# dependencies = ["textual>=0.80", "psutil>=5.9"]
# ///
"""Administrador de tareas en la terminal: ¿quién está calentando la laptop?

Agrupa TODOS los procesos por dueño y los ordena por CPU:
  - cada sesión de tmux → sus panes (con el arnés: ✳ claude, π pi) → sus procesos hijos
  - Colima / Docker (la VM y sus contenedores, incl. los de testcontainers)
  - cada app de macOS (.app), tmux+workmux, procesos del sistema, y "otros"
    (los huérfanos —padre = launchd, fuera de apps— se marcan con ⚠: MCP o tests que quedaron vivos)

Teclas:
  ↑↓/jk mover · espacio/→/← expandir/colapsar · enter ir al pane
  c  cerrar bien (pane/sesión → close-agent.py; app → Quit; contenedor → docker stop;
     Colima → colima stop; proceso → SIGTERM a su árbol)
  K  forzar (SIGKILL al árbol del proceso)
  t  (en Colima) borrar los contenedores de testcontainers
  d  panel lateral con TODOS los procesos de lo seleccionado (árbol; sigue al cursor sin expandir)
  tab  pasar el foco al panel (ahí c / K / enter actúan sobre ese proceso) · esc volver
  p  vista agrupada ↔ lista plana de procesos · m  ordenar por CPU ↔ RAM · q salir

Se abre con `tareas` (fish) o prefix + M (popup de tmux).
"""
import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque

import psutil
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

TMUX = "/opt/homebrew/bin/tmux"
CLOSE_AGENT = os.path.expanduser("~/.config/tmux/scripts/close-agent.py")
RADAR_STATE = os.path.expanduser("~/.cache/claude-radar/state.json")
ME = os.environ.get("USER") or ""
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
APP_RE = re.compile(r"/([^/]+)\.app/")
SYS_PREFIX = ("/System/", "/usr/libexec/", "/usr/sbin/", "/sbin/", "/Library/Apple/", "/usr/bin/")
VM_NAMES = ("com.apple.Virtualization.VirtualMachine", "limactl", "colima", "lima-guestagent",
            "com.docker.backend", "com.docker.vmnetd", "docker")
INFRA_NAMES = ("tmux", "workmux")
THERMAL = {0: ("normal", "#62c48a"), 1: ("moderada", "#e8a33d"), 2: ("alta", "#ff6464"),
           3: ("crítica", "#ff6464"), 4: ("crítica", "#ff6464")}
MEMP = {1: ("normal", "#62c48a"), 2: ("aviso", "#e8a33d"), 4: ("crítica", "#ff6464")}
STATE = {"working": ("● trabajando", "#e8a33d"), "waiting": ("◆ espera", "#ff6464"),
         "done": ("◉ terminó", "#62c48a"), "idle": ("○ quieto", "#6a6a6a")}
DIM, TXT, HEAD = "#6a6a6a", "#d0d0d0", "#ffffff"
SPARK = " ▁▂▃▄▅▆▇█"


# ------------------------------------------------------------------ utilidades
def sh(*cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def gb(kb):
    return "%.1fG" % (kb / 1048576) if kb >= 1048576 else "%dM" % (kb / 1024)


def cpu_style(v):
    return "#ff6464 bold" if v >= 80 else "#e8a33d" if v >= 30 else TXT if v >= 3 else DIM


def short_cmd(p):
    args = p["args"] or p["comm"]
    first, _, rest = args.partition(" ")
    name = os.path.basename(first) if first.startswith("/") else first
    if VERSION_RE.match(p["name"]):
        name = "claude"
    rest = re.sub(r"/(?:[^/\s]+/)+([^/\s]+)", r"…/\1", rest)  # paths largos → …/archivo
    return (name + " " + rest).strip()


# ------------------------------------------------------------------ recolección
def read_procs():
    procs = {}
    for line in sh("ps", "-axo", "pid=,ppid=,pcpu=,rss=,etime=,user=,comm=").splitlines():
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        pid = int(parts[0])
        procs[pid] = dict(pid=pid, ppid=int(parts[1]), cpu=float(parts[2]), rss=int(parts[3]),
                          etime=parts[4], user=parts[5], comm=parts[6],
                          name=os.path.basename(parts[6]), args="")
    for line in sh("ps", "-axo", "pid=,args=").splitlines():
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit() and int(pid) in procs:
            procs[int(pid)]["args"] = args.strip()
    return procs


def read_panes():
    fmt = "\t".join("#{%s}" % f for f in (
        "pane_id", "pane_pid", "session_name", "session_id", "window_index", "window_id",
        "pane_index", "pane_title", "pane_current_path"))
    panes = []
    for line in sh(TMUX, "list-panes", "-a", "-F", fmt).splitlines():
        f = line.split("\t")
        if len(f) == 9:
            panes.append(dict(id=f[0], pid=int(f[1] or 0), session=f[2], session_id=f[3], win=f[4],
                              window_id=f[5], pane=f[6], title=f[7], path=f[8]))
    return panes


def radar_states():
    try:
        return {p["id"]: p.get("state") for p in json.load(open(RADAR_STATE)).get("panes", [])}
    except Exception:
        return {}


def system_stats():
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    therm = sh("notifyutil", "-g", "com.apple.system.thermalpressurelevel").split()
    memp = sh("sysctl", "-n", "kern.memorystatus_vm_pressure_level").strip()
    batt = re.search(r"(\d+)%;\s*([^;]+)", sh("pmset", "-g", "batt"))
    return dict(cpu=psutil.cpu_percent(None), ncpu=psutil.cpu_count(), load=os.getloadavg(),
                mem_used=vm.total - vm.available, mem_total=vm.total, swap_used=sw.used, swap_total=sw.total,
                thermal=int(therm[-1]) if therm and therm[-1].isdigit() else None,
                memp=int(memp) if memp.isdigit() else None,
                batt=(batt.group(1), batt.group(2).strip()) if batt else None)


def docker_containers():
    """Contenedores corriendo + su CPU/RAM (lento: ~2 s, se llama en su propio hilo)."""
    ps_out = sh("docker", "ps", "--format",
                '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.RunningFor}}\t{{.Label "org.testcontainers"}}', timeout=4)
    if not ps_out.strip():
        return []
    stats = {}
    for line in sh("docker", "stats", "--no-stream", "--format",
                   "{{.ID}}\t{{.CPUPerc}}\t{{.MemUsage}}", timeout=8).splitlines():
        f = line.split("\t")
        if len(f) == 3:
            stats[f[0][:12]] = (float(f[1].rstrip("%") or 0), f[2].split(" / ")[0])
    out = []
    for line in ps_out.splitlines():
        f = line.split("\t")
        if len(f) == 5:
            cpu, mem = stats.get(f[0][:12], (0.0, ""))
            out.append(dict(id=f[0], name=f[1], image=f[2], age=f[3], tc=f[4] == "true", cpu=cpu, mem=mem))
    return sorted(out, key=lambda c: -c["cpu"])


# ------------------------------------------------------------------ agrupación
def classify(procs, panes):
    """Devuelve {pid: clave_de_grupo}. Un pane se adueña de todo su árbol de procesos."""
    kids = {}
    for p in procs.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    owner = {}
    for pn in panes:
        stack = [pn["pid"]]
        while stack:
            pid = stack.pop()
            if pid in procs and pid not in owner:
                owner[pid] = ("pane", pn["id"])
                stack.extend(kids.get(pid, []))

    def own_rule(p):
        if any(n in p["comm"] for n in VM_NAMES) or ".colima" in p["args"] or "/lima/" in p["args"]:
            return ("vm",)
        m = APP_RE.search(p["comm"])
        if m:
            return ("app", m.group(1))
        if p["name"] in INFRA_NAMES:
            return ("infra",)
        if p["user"] != ME or p["comm"].startswith(SYS_PREFIX) or p["pid"] <= 1:
            return ("sys",)
        return None

    def group(pid, depth=0):
        if pid in owner:
            return owner[pid]
        p = procs.get(pid)
        if p is None:
            return ("sys",)
        g = own_rule(p)
        if g is None:
            par = p["ppid"]
            if par > 1 and par in procs and depth < 50:
                g = group(par, depth + 1)
                if g == ("sys",):  # hijo de un daemon del sistema pero es tuyo
                    g = ("other",)
            else:
                g = ("other",)
        owner[pid] = g
        return g

    for pid in procs:
        group(pid)
    return owner


def harness(pids, procs):
    names = {procs[p]["name"] for p in pids if p in procs}
    if "claude" in names or any(VERSION_RE.match(n) for n in names):
        return "✳ claude"
    if "pi" in names:
        return "π pi"
    if "codex" in names:
        return "◎ codex"
    return ""


def build_rows(data, expanded, sort_key):
    """Filas de la vista agrupada: (key, depth, label, kind, cpu, rss, nprocs, extra, meta)."""
    procs, panes, owner = data["procs"], data["panes"], data["owner"]
    states, containers = data["states"], data["containers"]
    members = {}
    for pid, g in owner.items():
        members.setdefault(g, []).append(pid)
    agg = lambda pids: (sum(procs[p]["cpu"] for p in pids), sum(procs[p]["rss"] for p in pids))
    keyf = (lambda r: -r[0]) if sort_key == "cpu" else (lambda r: -r[1])

    top = []  # (cpu, rss, row, children_fn)
    by_session = {}
    for pn in panes:
        by_session.setdefault((pn["session"], pn["session_id"]), []).append(pn)

    def proc_rows(pids, depth, limit=8, flag_orphans=False):
        ps = sorted((procs[p] for p in pids), key=lambda p: -(p["cpu"] if sort_key == "cpu" else p["rss"]))
        rows = []
        for p in ps[:limit]:
            orphan = flag_orphans and p["ppid"] == 1 and p["user"] == ME
            rows.append((("proc", p["pid"]), depth, short_cmd(p), "proceso", p["cpu"], p["rss"], 1,
                         ("⚠ huérfano · " if orphan else "") + p["etime"], {"pid": p["pid"]}))
        if len(ps) > limit:
            rest = ps[limit:]
            rows.append((("more", depth, ps[0]["pid"]), depth, "… %d procesos más" % len(rest), "",
                         sum(p["cpu"] for p in rest), sum(p["rss"] for p in rest), len(rest), "", {}))
        return rows

    for (sname, sid), pns in by_session.items():
        pane_rows = []
        for pn in pns:
            pids = members.get(("pane", pn["id"]), [])
            cpu, rss = agg(pids)
            hz = harness(pids, procs)
            st = STATE.get(states.get(pn["id"]) or "", ("", DIM))[0] if hz else ""
            title = pn["title"] if pn["title"] and not pn["title"].startswith("MacBook") else os.path.basename(pn["path"])
            if not hz and cpu < 1 and any(procs[p]["name"] == "workmux" for p in pids):
                continue  # el sidebar de workmux
            label = "%s.%s %s%s" % (pn["win"], pn["pane"], (hz + " · ") if hz else "", title)
            key = ("pane", pn["id"])
            pane_rows.append((cpu, rss, (key, 1, label, "pane", cpu, rss, len(pids), st, {"pane": pn}), pids))
        cpu = sum(r[0] for r in pane_rows)
        rss = sum(r[1] for r in pane_rows)
        n = sum(r[2][6] for r in pane_rows)
        key = ("session", sid)
        row = (key, 0, "tmux · " + sname, "sesión", cpu, rss, n, "%d panes" % len(pane_rows),
               {"session_id": sid, "session": sname})

        def kids(pane_rows=pane_rows):
            out = []
            for c, r, prow, pids in sorted(pane_rows, key=lambda x: keyf(x)):
                out.append(prow)
                if prow[0] in expanded:
                    out.extend(proc_rows(pids, 2))
            return out
        top.append((cpu, rss, row, kids))

    named = {("vm",): "Colima / Docker (VM)", ("infra",): "tmux + workmux (infra)",
             ("sys",): "macOS (sistema)", ("other",): "Otros procesos tuyos"}
    for g, pids in members.items():
        if g[0] == "pane":
            continue
        cpu, rss = agg(pids)
        if g[0] == "app":
            label, kind, extra = g[1], "app", ""
        else:
            label, kind = named[g], g[0]
            extra = ""
            if g == ("vm",) and containers:
                tc = sum(1 for c in containers if c["tc"])
                extra = "%d contenedores%s" % (len(containers), (" (%d testcontainers)" % tc) if tc else "")
            if g == ("other",):
                orph = sum(1 for p in pids if procs[p]["ppid"] == 1)
                extra = ("⚠ %d huérfanos" % orph) if orph else ""
        row = (g, 0, label, kind, cpu, rss, len(pids), extra, {"app": g[1]} if g[0] == "app" else {})

        def kids(g=g, pids=pids):
            out = []
            if g == ("vm",):
                for c in containers:
                    out.append((("ctr", c["id"]), 1, "%s  %s" % (c["name"], c["image"]), "contenedor",
                                c["cpu"], 0, 1, ("testcontainers · " if c["tc"] else "") + c["age"] +
                                ("  " + c["mem"] if c["mem"] else ""), {"ctr": c}))
            return out + proc_rows(pids, 1, flag_orphans=g == ("other",))
        top.append((cpu, rss, row, kids))

    rows = []
    for cpu, rss, row, kids in sorted(top, key=keyf):
        if cpu < 0.05 and rss < 20000 and row[3] not in ("sesión",):
            continue
        rows.append(row)
        if row[0] in expanded:
            rows.extend(kids())
    return rows


def flat_rows(data, sort_key):
    procs, owner, panes = data["procs"], data["owner"], {p["id"]: p for p in data["panes"]}
    key = (lambda p: -p["cpu"]) if sort_key == "cpu" else (lambda p: -p["rss"])
    rows = []
    for p in sorted(procs.values(), key=key)[:120]:
        g = owner.get(p["pid"], ("sys",))
        if g[0] == "pane" and g[1] in panes:
            pn = panes[g[1]]
            where = "%s:%s.%s" % (pn["session"], pn["win"], pn["pane"])
        elif g[0] == "app":
            where = g[1]
        else:
            where = {"vm": "colima", "infra": "tmux", "sys": "sistema", "other": "otros"}[g[0]]
        orphan = p["ppid"] == 1 and p["user"] == ME and not APP_RE.search(p["comm"]) and g[0] == "other"
        rows.append((("proc", p["pid"]), 0, short_cmd(p), str(p["pid"]), p["cpu"], p["rss"], 1,
                     ("⚠ " if orphan else "") + where + " · " + p["etime"], {"pid": p["pid"]}))
    return rows


def detail_of(data, row):
    """(título, pids) de lo que hay bajo un renglón de la vista principal."""
    key, label, meta = row[0], row[2], row[8]
    owner, procs = data["owner"], data["procs"]
    if key[0] == "session":
        ids = {("pane", pn["id"]) for pn in data["panes"] if pn["session_id"] == key[1]}
        return "sesión " + meta["session"], [p for p, g in owner.items() if g in ids]
    if key[0] == "more":
        key = owner.get(key[2], ("sys",))
        label = "%s (todos)" % label
    if key[0] == "proc":
        kids = {}
        for p in procs.values():
            kids.setdefault(p["ppid"], []).append(p["pid"])
        out, stack = [], [key[1]]
        while stack:
            x = stack.pop()
            if x in procs:
                out.append(x)
                stack.extend(kids.get(x, []))
        return label, out
    if key[0] == "ctr":
        return label, []
    return label, [p for p, g in owner.items() if g == key]


def detail_rows(data, pids, sort_key):
    """Árbol padre→hijos dentro del conjunto: [(pid, depth)]; ramas ordenadas por CPU/RAM del subárbol."""
    procs, inset = data["procs"], set(pids)
    kids = {}
    for p in pids:
        kids.setdefault(procs[p]["ppid"], []).append(p)
    val = "cpu" if sort_key == "cpu" else "rss"
    memo = {}

    def weight(p):
        if p not in memo:
            memo[p] = procs[p][val] + sum(weight(c) for c in kids.get(p, []))
        return memo[p]

    out = []

    def walk(p, depth):
        out.append((p, depth))
        for c in sorted(kids.get(p, []), key=lambda c: -weight(c)):
            walk(c, depth + 1)

    for r in sorted((p for p in pids if procs[p]["ppid"] not in inset), key=lambda p: -weight(p)):
        walk(r, 0)
    return out


# ------------------------------------------------------------------ acciones
def kill_tree(pid, sig):
    try:
        root = psutil.Process(pid)
        tree = root.children(recursive=True) + [root]
    except psutil.Error:
        return
    for p in tree:
        try:
            p.send_signal(sig)
        except psutil.Error:
            pass
    if sig == signal.SIGTERM:
        def reap():
            _, alive = psutil.wait_procs(tree, timeout=4)
            for p in alive:
                try:
                    p.kill()
                except psutil.Error:
                    pass
        threading.Thread(target=reap, daemon=True).start()


class Confirm(ModalScreen):
    BINDINGS = [("y", "yes", "sí"), ("s", "yes", "sí"), ("n", "no", "no"), ("escape", "no", "no")]
    DEFAULT_CSS = """
    Confirm { align: center middle; background: rgba(0,0,0,0.55); }
    #box { width: 72; height: auto; border: round #ff6464; background: #111111; padding: 1 2; }
    """

    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    def compose(self):
        with Vertical(id="box"):
            yield Static(Text.from_markup(self.msg + "\n\n[#8a8a8a]y = sí · n / esc = no[/]"))

    def action_yes(self):
        self.dismiss(True)

    def action_no(self):
        self.dismiss(False)


# ------------------------------------------------------------------ app
KIND = {"vm": "docker", "infra": "infra", "sys": "sistema", "other": "otros"}


class Table(DataTable):
    # DataTable usa ←/→/enter para sí; aquí expanden/colapsan y saltan al pane.
    BINDINGS = [Binding("right,l", "app.expand", show=False), Binding("left,h", "app.collapse", show=False),
                Binding("enter", "app.enter", "ir al pane"), Binding("space", "app.toggle", "expandir"),
                Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False)]


class DetailTable(DataTable):
    BINDINGS = [Binding("enter", "app.enter", "ir al pane"), Binding("escape,left,h", "app.focus_main", "volver"),
                Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False)]


class TaskMon(App):
    CSS = """
    Screen { background: #0d0d0d; }
    #head { height: auto; padding: 0 1; background: #1a1a1a; color: #d0d0d0; }
    DataTable { height: 1fr; background: #0d0d0d; }
    DataTable > .datatable--cursor { background: #2e2e2e; }
    DataTable > .datatable--header { background: #0d0d0d; color: #8a8a8a; }
    Footer { background: #1a1a1a; }
    #side { width: 46%; display: none; border-left: tall #2e2e2e; }
    #side.on { display: block; }
    #side-head { height: auto; padding: 0 1; background: #1a1a1a; }
    #detail:focus > .datatable--cursor { background: #3a3a3a; }
    #main { width: 1fr; }
    """
    BINDINGS = [
        Binding("q", "quit", "salir"), Binding("escape", "quit", show=False),
        Binding("c", "close", "cerrar"), Binding("K", "force", "forzar"),
        Binding("t", "testcontainers", "borrar testcontainers"),
        Binding("p", "mode", "agrupado/plano"), Binding("m", "sort", "cpu/ram"),
        Binding("d", "detail", "panel de procesos"), Binding("tab", "swap_focus", "cambiar panel"),
    ]

    def __init__(self):
        super().__init__()
        self.data = None
        self.rows = []
        self.expanded = set()
        self.first = True
        self.mode, self.sort_key = "group", "cpu"
        self.hist = deque(maxlen=40)
        self.containers, self.sys = [], None
        self.lock = threading.Lock()

    def compose(self) -> ComposeResult:
        yield Static("cargando…", id="head")
        with Horizontal():
            yield Table(cursor_type="row", zebra_stripes=False, id="main")
            with Vertical(id="side"):
                yield Static("", id="side-head")
                yield DetailTable(cursor_type="row", zebra_stripes=False, id="detail")
        yield Footer()

    def on_mount(self):
        dt = self.query_one("#detail", DataTable)
        dt.add_column("proceso", key="label", width=44)
        dt.add_column("PID", key="pid", width=6)
        dt.add_column("CPU", key="cpu", width=6)
        dt.add_column("RAM", key="ram", width=6)
        dt.add_column("tiempo", key="etime")
        self.drows = []
        t = self.query_one("#main", DataTable)
        t.add_column("", key="label", width=58)
        t.add_column("tipo", key="kind", width=10)
        t.add_column("CPU", key="cpu", width=7)
        t.add_column("RAM", key="ram", width=7)
        t.add_column("proc", key="n", width=5)
        t.add_column("", key="extra")
        psutil.cpu_percent(None)
        self.slow_loop()
        self.collect()
        self.set_interval(2.0, self.collect)

    # -- datos (en hilos para no congelar la UI)
    def slow_loop(self):
        def run():
            while True:
                try:
                    c = docker_containers()
                    with self.lock:
                        self.containers = c
                except Exception:
                    pass
                time.sleep(10)
        threading.Thread(target=run, daemon=True).start()

    def collect(self):
        def run():
            procs, panes = read_procs(), read_panes()
            with self.lock:
                containers = list(self.containers)
            data = dict(procs=procs, panes=panes, owner=classify(procs, panes), states=radar_states(),
                        containers=containers, sys=system_stats())
            self.call_from_thread(self.show, data)
        threading.Thread(target=run, daemon=True).start()

    # -- render
    def show(self, data):
        self.data = data
        if self.first:  # al abrir: expandir las sesiones de tmux
            self.expanded |= {("session", p["session_id"]) for p in data["panes"]}
            self.first = False
        self.hist.append(data["sys"]["cpu"])
        self.render_head()
        self.render_table()

    def render_head(self):
        s, d = self.data["sys"], self.data
        t = Text()
        bar = int(s["cpu"] / 100 * 20)
        t.append(" CPU ", style="bold " + HEAD)
        t.append("█" * bar, style=cpu_style(s["cpu"]))
        t.append("░" * (20 - bar), style="#2e2e2e")
        t.append(" %3.0f%%  " % s["cpu"], style=cpu_style(s["cpu"]))
        t.append("".join(SPARK[min(8, int(v / 12.5))] for v in self.hist), style="#8a8a8a")
        t.append("   carga %.1f %.1f %.1f / %d núcleos" % (*s["load"], s["ncpu"]),
                 style="#ff6464" if s["load"][0] > s["ncpu"] else DIM)
        t.append("\n RAM ", style="bold " + HEAD)
        t.append("%.1f/%.0f GB" % (s["mem_used"] / 2**30, s["mem_total"] / 2**30), style=TXT)
        if s["memp"] in MEMP:
            lbl, col = MEMP[s["memp"]]
            t.append("  presión ", style=DIM)
            t.append(lbl, style=col)
        swap_pct = s["swap_used"] / s["swap_total"] if s["swap_total"] else 0
        t.append("   swap ", style=DIM)
        t.append("%.1f/%.1f GB" % (s["swap_used"] / 2**30, s["swap_total"] / 2**30),
                 style="#ff6464" if swap_pct > 0.7 else "#e8a33d" if swap_pct > 0.4 else TXT)
        if s["thermal"] is not None:
            lbl, col = THERMAL.get(s["thermal"], ("?", DIM))
            t.append("   temperatura ", style=DIM)
            t.append(lbl, style="bold " + col)
        if s["batt"]:
            t.append("   batería %s%% %s" % s["batt"], style=DIM)
        # los 3 que más CPU usan (agrupados)
        culprits = [r for r in build_rows(d, set(), "cpu") if r[1] == 0][:3]
        t.append("\n más CPU: ", style="bold " + HEAD)
        for i, r in enumerate(culprits):
            if i:
                t.append("  ·  ", style=DIM)
            t.append(r[2][:30], style=TXT)
            t.append(" %.0f%%" % r[4], style=cpu_style(r[4]))
        t.append("   [%s · orden %s]" % ("agrupado" if self.mode == "group" else "plano", self.sort_key.upper()),
                 style=DIM)
        self.query_one("#head", Static).update(t)

    def render_table(self):
        tbl = self.query_one("#main", DataTable)
        cur_key = self.rows[tbl.cursor_row][0] if self.rows and 0 <= tbl.cursor_row < len(self.rows) else None
        self.rows = (build_rows(self.data, self.expanded, self.sort_key) if self.mode == "group"
                     else flat_rows(self.data, self.sort_key))
        scroll = tbl.scroll_y
        tbl.clear()
        for i, (key, depth, label, kind, cpu, rss, n, extra, meta) in enumerate(self.rows):
            has_kids = depth == 0 or kind == "pane"
            mark = ("▾ " if key in self.expanded else "▸ ") if (has_kids and self.mode == "group") else "  "
            style = ("bold " + HEAD) if depth == 0 and self.mode == "group" else TXT if depth == 1 else "#9a9a9a"
            lab = Text("  " * depth + mark, style=DIM)
            lab.append(label[: 56 - 2 * depth], style=style)
            ext = Text(extra, style="#ff6464" if "⚠" in extra else
                       next((c for l, c in STATE.values() if l == extra), DIM))
            tbl.add_row(lab, Text(KIND.get(kind, kind), style=DIM), Text("%.0f%%" % cpu, style=cpu_style(cpu)),
                        Text(gb(rss) if rss else "", style=DIM), Text(str(n), style=DIM), ext, key=str(i))
        if cur_key is not None:
            for i, r in enumerate(self.rows):
                if r[0] == cur_key:
                    tbl.move_cursor(row=i, animate=False, scroll=False)
                    break
        tbl.scroll_to(y=scroll, animate=False)
        self.render_detail()

    def main_row(self):
        tbl = self.query_one("#main", DataTable)
        if self.rows and 0 <= tbl.cursor_row < len(self.rows):
            return self.rows[tbl.cursor_row]
        return None

    def current(self):
        """El renglón sobre el que actúan c / K / enter: el del panel que tiene el foco."""
        dt = self.query_one("#detail", DataTable)
        if dt.has_focus and self.drows and 0 <= dt.cursor_row < len(self.drows):
            pid = self.drows[dt.cursor_row]
            p = self.data["procs"].get(pid)
            if p:
                return (("proc", pid), 2, short_cmd(p), "proceso", p["cpu"], p["rss"], 1, "", {"pid": pid})
            return None
        return self.main_row()

    # -- panel de detalle
    def render_detail(self):
        side = self.query_one("#side")
        if not side.has_class("on") or not self.data:
            return
        dt = self.query_one("#detail", DataTable)
        row = self.main_row()
        cur_pid = self.drows[dt.cursor_row] if self.drows and 0 <= dt.cursor_row < len(self.drows) else None
        title, pids = detail_of(self.data, row) if row else ("", [])
        procs = self.data["procs"]
        tree = detail_rows(self.data, pids, self.sort_key)
        head = Text(" ", style=DIM)
        head.append(title[:60], style="bold " + HEAD)
        head.append("\n %d procesos · CPU " % len(pids), style=DIM)
        cpu = sum(procs[p]["cpu"] for p in pids)
        head.append("%.0f%%" % cpu, style=cpu_style(cpu))
        head.append(" · RAM %s" % gb(sum(procs[p]["rss"] for p in pids)), style=DIM)
        if row and row[0][0] == "ctr":
            c = row[8]["ctr"]
            head.append("\n contenedor %s · %s · %s · %s" % (c["id"][:12], c["image"], c["age"], c["mem"]), style=TXT)
        self.query_one("#side-head", Static).update(head)
        scroll = dt.scroll_y
        dt.clear()
        self.drows = []
        for pid, depth in tree:
            p = procs[pid]
            orphan = p["ppid"] == 1 and p["user"] == ME and self.data["owner"].get(pid) == ("other",)
            lab = Text(("  " * min(depth, 8)) + ("└ " if depth else ""), style="#4a4a4a")
            lab.append(short_cmd(p)[: 42 - 2 * min(depth, 8)], style=TXT if depth == 0 else "#a8a8a8")
            dt.add_row(lab, Text(str(pid), style=DIM), Text("%.0f%%" % p["cpu"], style=cpu_style(p["cpu"])),
                       Text(gb(p["rss"]), style=DIM),
                       Text(("⚠ " if orphan else "") + p["etime"], style="#ff6464" if orphan else DIM))
            self.drows.append(pid)
        if cur_pid in self.drows:
            dt.move_cursor(row=self.drows.index(cur_pid), animate=False, scroll=False)
        dt.scroll_to(y=scroll, animate=False)

    def on_data_table_row_highlighted(self, ev):
        if ev.data_table.id == "main" and self.query_one("#side").has_class("on"):
            dt = self.query_one("#detail", DataTable)
            row = self.main_row()
            key = row[0] if row else None
            if key == getattr(self, "detail_key", None):
                return  # mismo renglón (refresco): no mover el panel
            self.detail_key = key
            if not dt.has_focus:  # otro renglón → el panel arranca desde arriba
                self.drows = []
                dt.move_cursor(row=0, animate=False)
                dt.scroll_to(y=0, animate=False)
            self.render_detail()

    def action_detail(self):
        side = self.query_one("#side")
        side.toggle_class("on")
        if side.has_class("on"):
            self.render_detail()
        else:
            self.action_focus_main()

    def action_swap_focus(self):
        side = self.query_one("#side")
        if not side.has_class("on"):
            side.add_class("on")
            self.render_detail()
        if self.query_one("#detail").has_focus:
            self.action_focus_main()
        else:
            self.query_one("#detail").focus()

    def action_focus_main(self):
        self.query_one("#main").focus()

    # -- navegación
    def action_toggle(self):
        r = self.current()
        if r and self.mode == "group":
            self.expanded.symmetric_difference_update({r[0]})
            self.render_table()

    def action_expand(self):
        r = self.current()
        if r and r[0] not in self.expanded and self.mode == "group":
            self.expanded.add(r[0])
            self.render_table()

    def action_collapse(self):
        r = self.current()
        if r and r[0] in self.expanded:
            self.expanded.discard(r[0])
            self.render_table()

    def action_mode(self):
        self.mode = "flat" if self.mode == "group" else "group"
        self.render_head()
        self.render_table()

    def action_sort(self):
        self.sort_key = "rss" if self.sort_key == "cpu" else "cpu"
        self.render_head()
        self.render_table()

    def pane_of(self, r):
        if r[3] == "pane":
            return r[8]["pane"]["id"]
        if "pid" in r[8]:
            g = self.data["owner"].get(r[8]["pid"])
            if g and g[0] == "pane":
                return g[1]
        return None

    def action_enter(self):
        r = self.current()
        if not r:
            return
        pane = self.pane_of(r)
        if pane:
            sh(TMUX, "switch-client", "-t", pane, ";", "select-window", "-t", pane, ";", "select-pane", "-t", pane)
            self.exit()
        else:
            self.action_toggle()

    # -- acciones de cierre
    def ask(self, msg, fn):
        self.push_screen(Confirm(msg), lambda ok: (fn(), self.notify("hecho", timeout=2)) if ok else None)

    def action_close(self):
        r = self.current()
        if not r:
            return
        key, kind, label, meta = r[0], r[3], r[2], r[8]
        if kind == "pane":
            pn = meta["pane"]
            self.ask("¿Cerrar el pane [b]%s:%s.%s[/b]?\n%s\n\n[#8a8a8a]Cierra bien: a Claude le manda SIGTERM para que guarde "
                     "y apague sus MCP, y luego mata lo que quede vivo.[/]" % (pn["session"], pn["win"], pn["pane"], label),
                     lambda: subprocess.Popen([CLOSE_AGENT, "pane", pn["id"]]))
        elif kind == "sesión":
            self.ask("¿Cerrar la sesión [b]%s[/b] completa?\nTodos sus panes y agentes (%d procesos)."
                     % (meta["session"], r[6]), lambda: subprocess.Popen([CLOSE_AGENT, "session", meta["session_id"]]))
        elif kind == "app":
            app = meta["app"]
            self.ask("¿Cerrar la app [b]%s[/b]? (Quit normal, como ⌘Q)" % app,
                     lambda: sh("osascript", "-e", 'quit app "%s"' % app.replace('"', '')))
        elif kind == "vm":
            self.ask("¿Detener Colima? ([b]colima stop[/b])\nSe detienen TODOS los contenedores de Docker.",
                     lambda: subprocess.Popen(["colima", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        elif kind == "contenedor":
            c = meta["ctr"]
            self.ask("¿Detener el contenedor [b]%s[/b] (%s)?" % (c["name"], c["image"]),
                     lambda: subprocess.Popen(["docker", "stop", "-t", "5", c["id"]],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        elif "pid" in meta:
            self.kill_proc(meta["pid"], signal.SIGTERM)
        else:
            self.notify("Esto no se cierra desde aquí (macOS / grupo). Expándelo y elige un proceso.", timeout=4)

    def action_force(self):
        r = self.current()
        if r and "pid" in r[8]:
            self.kill_proc(r[8]["pid"], signal.SIGKILL)
        else:
            self.notify("K (forzar) solo aplica a procesos.", timeout=3)

    def kill_proc(self, pid, sig):
        p = self.data["procs"].get(pid)
        if not p:
            return
        if p["user"] != ME:
            self.notify("%s es de %s (sistema): no se toca." % (p["name"], p["user"]), severity="warning")
            return
        if pid in {pn["pid"] for pn in self.data["panes"]}:
            self.notify("Es la shell del pane: usa c sobre el pane para cerrarlo bien.", severity="warning")
            return
        n = sum(1 for _ in self._tree(pid))
        how = "SIGTERM (y SIGKILL a los 4 s si no sale)" if sig == signal.SIGTERM else "[#ff6464]SIGKILL inmediato[/]"
        self.ask("¿Terminar [b]%s[/b] (pid %d) y sus %d hijos?\n%s\n\n%s" % (p["name"], pid, n - 1, short_cmd(p)[:200], how),
                 lambda: kill_tree(pid, sig))

    def _tree(self, pid):
        procs = self.data["procs"]
        stack = [pid]
        while stack:
            x = stack.pop()
            yield x
            stack.extend(q for q, p in procs.items() if p["ppid"] == x)

    def action_testcontainers(self):
        with self.lock:
            ids = [c["id"] for c in self.containers if c["tc"]]
        if not ids:
            self.notify("No hay contenedores de testcontainers corriendo.", timeout=3)
            return
        self.ask("¿Borrar %d contenedores de testcontainers?\n[#8a8a8a]Si hay tests corriendo ahora mismo, esos tests "
                 "van a fallar.[/]" % len(ids),
                 lambda: subprocess.Popen(["docker", "rm", "-f", *ids], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))


if __name__ == "__main__":
    TaskMon().run()
