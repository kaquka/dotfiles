# /// script
# requires-python = ">=3.10"
# dependencies = ["textual>=0.80"]
# ///
"""Mission control de claude-radar: tablero de sesiones de Claude y servidores.

Se abre con prefix + a (display-popup). Teclas:
  flechas/hjkl mover · enter ir al pane · 1-9 ir a tarjeta · w solo los que esperan/trabajan · q salir
"""
import os
import subprocess
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import radar  # noqa: E402

from rich.console import Group  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Grid, VerticalScroll  # noqa: E402
from textual.widgets import Static  # noqa: E402

C = radar.C
STATE_STYLE = {"waiting": C["wait"], "done": C["done"], "working": C["work"], "idle": C["idle"]}
SPARK = " ▁▂▃▄▅▆▇█"
ORDER = {"waiting": 0, "done": 1, "working": 2, "idle": 3}
_branch_cache = {}


def branch(path):
    hit = _branch_cache.get(path)
    if hit and time.time() - hit[1] < 30:
        return hit[0]
    try:
        b = subprocess.run(["git", "-C", path, "branch", "--show-current"], capture_output=True,
                           text=True, timeout=1).stdout.strip()
    except Exception:
        b = ""
    _branch_cache[path] = (b, time.time())
    return b


def timeline(pane_id, events, now, cells=30):
    """Estado por minuto en los últimos `cells` minutos."""
    evs = events.get(pane_id, [])
    out = Text(no_wrap=True, overflow="crop")
    start = now - cells * 60
    state = "idle"
    for ts, st in evs:
        if ts < start:
            state = st
    i = 0
    for c in range(cells):
        b0, b1 = start + c * 60, start + (c + 1) * 60
        seen = {state}
        while i < len(evs) and evs[i][0] < b1:
            if evs[i][0] >= b0:
                seen.add(evs[i][1])
                state = evs[i][1]
            i += 1
        cell = "waiting" if "waiting" in seen else "working" if "working" in seen else "idle"
        out.append("▆", style=STATE_STYLE[cell] if cell != "idle" else "#2f2f2f")
    return out


def read_events():
    ev = {}
    try:
        with open(radar.EVENTS) as f:
            for line in f.readlines()[-3000:]:
                parts = line.split()
                if len(parts) == 3:
                    ev.setdefault(parts[1], []).append((float(parts[0]), parts[2]))
    except OSError:
        pass
    return ev


class Card(Static):
    can_focus = False


class Mission(App):
    CSS = """
    Screen { background: #0f0f0f; }
    #head { height: 1; padding: 0 1; margin-bottom: 1; }
    #body { height: 1fr; }
    #cards { grid-size: 4; grid-gutter: 0 1; grid-rows: 10; height: auto; padding: 0 1; }
    #srvtitle { height: 1; padding: 0 2; margin-top: 1; color: #4a4a4a; text-style: bold; }
    #servers { grid-size: 3; grid-gutter: 0 1; grid-rows: 7; height: auto; padding: 0 1; }
    Card { height: 10; padding: 0 1; background: #1b1b1b; border: round #3a3a3a;
           border-title-color: #9a9a9a; border-subtitle-color: #9a9a9a; }
    Card.working { border: round #e8a33d; border-subtitle-color: #e8a33d; }
    Card.done { border: heavy #62c48a; border-subtitle-color: #62c48a; background: #14241a; }
    Card.waiting { border: heavy #ff6464; border-subtitle-color: #ff6464; background: #241414; }
    Card.srv { height: 7; border: round #2b5a70; border-subtitle-color: #5fb3dc; }
    Card.down { height: 7; border: heavy #ff6464; }
    Card.sel { background: #2c2c2c; border-title-color: #f2f2f2; border-title-style: bold; }
    Card.sel.idle { border: round #f2f2f2; }
    Card.sel.srv { border: round #f2f2f2; }
    #empty { padding: 1 2; color: #777777; }
    #keys { dock: bottom; height: 1; padding: 0 1; background: #161616; color: #777777; }
    """
    BINDINGS = [
        ("q", "quit", "salir"), ("escape", "quit", "salir"),
        ("left,h", "move(-1)", ""), ("right,l", "move(1)", ""),
        ("up,k", "move(-4)", ""), ("down,j", "move(4)", ""),
        ("enter", "jump", "ir"), ("w", "toggle_filter", "filtro"),
    ] + [(str(i), "jump_n(%d)" % i, "") for i in range(1, 10)]

    def __init__(self):
        super().__init__()
        self.items = []
        self.sel = 0
        self.only_active = False
        self.hist = {}
        self.last_hist = {}
        self.cols = 4

    def compose(self) -> ComposeResult:
        yield Static(id="head")
        with VerticalScroll(id="body"):
            yield Grid(id="cards")
            yield Static("SERVIDORES", id="srvtitle")
            yield Grid(id="servers")
        yield Static(
            Text.assemble(("enter", "bold #d0d0d0"), " ir al pane   ", ("←↑↓→ hjkl", "bold #d0d0d0"),
                          " mover   ", ("1-9", "bold #d0d0d0"), " ir a tarjeta   ", ("w", "bold #d0d0d0"),
                          " solo activos   ", ("q", "bold #d0d0d0"), " salir"), id="keys")

    def on_mount(self):
        self.refresh_data()
        self.set_interval(1.5, self.refresh_data)

    def on_resize(self, event):
        self.cols = max(1, min(5, (self.size.width - 2) // 40))
        self.query_one("#cards").styles.grid_size_columns = self.cols
        self.query_one("#servers").styles.grid_size_columns = max(1, min(4, (self.size.width - 2) // 50))

    def refresh_data(self):
        self.run_worker(self._collect, thread=True, exclusive=True)

    def _collect(self):
        panes = radar.collect(with_screen=True)
        events = read_events()
        for d in panes:
            if d["kind"] == "claude":
                d["branch"] = branch(d["path"])
        self.call_from_thread(self._render, panes, events)

    # ------------------------------------------------------------ render
    def _render(self, panes, events):
        now = time.time()
        claude = [d for d in panes if d["kind"] == "claude"]
        srvs = [d for d in panes if d["kind"] in ("srv", "down")]
        claude.sort(key=lambda d: (ORDER.get(d["state"], 3), d["session"], d["win"], d["pane"]))
        if self.only_active:
            claude = [d for d in claude if d["state"] in ("waiting", "done", "working")]
        for d in srvs:
            prev = self.last_hist.get(d["id"])
            q = self.hist.setdefault(d["id"], deque([0] * 30, maxlen=30))
            q.append(max(0, d["history"] - prev) if prev is not None else 0)
            self.last_hist[d["id"]] = d["history"]

        cnt = {}
        for d in panes:
            if d["state"]:
                cnt[d["state"]] = cnt.get(d["state"], 0) + 1
        head = Text.assemble((" MISSION CONTROL ", "bold #f2f2f2"), "  ")
        for st, label, style in (("waiting", "espera", "bold #1a0000 on #ff6464"),
                                 ("done", "sin revisar", "bold #04210f on #62c48a"),
                                 ("working", "trabajando", "#f5c06a on #3a2a10"),
                                 ("idle", "en reposo", "#8c8c8c on #262626"),
                                 ("srv", "servidores", "#5fb3dc on #11303f"),
                                 ("down", "caídos", "bold #1a0000 on #ff6464")):
            if cnt.get(st):
                head.append(" %s %d %s " % (radar.GLYPH[st], cnt[st], label), style=style)
                head.append(" ")
        if self.only_active:
            head.append("  filtro: solo activos", style="#e8a33d")
        head.append("   %s · actividad 30 min" % time.strftime("%H:%M:%S"), style="#4a4a4a")
        self.query_one("#head", Static).update(head)

        self._sync(self.query_one("#cards", Grid), claude, self._claude_card, "c")
        self._sync(self.query_one("#servers", Grid), srvs, self._srv_card, "s")
        self.query_one("#srvtitle").display = bool(srvs)
        self.items = claude + srvs
        self.sel = min(self.sel, max(0, len(self.items) - 1))
        self._mark()
        self.events = events

    def _sync(self, grid, items, fn, prefix):
        ids = ["%s%s" % (prefix, d["id"].lstrip("%")) for d in items]
        current = [w.id for w in grid.children]
        if current != ids:
            grid.remove_children()
            grid.mount(*[Card(id=i) for i in ids])
            self.call_after_refresh(self._fill, grid, items, fn)
        else:
            self._fill(grid, items, fn)

    def _fill(self, grid, items, fn):
        events = read_events()
        for w, d in zip(grid.children, items):
            fn(w, d, events)
        self._mark()

    def _claude_card(self, w, d, events):
        st = d["state"]
        w.set_classes({st} | ({"sel"} if "sel" in w.classes else set()))
        w.border_title = " %d.%d · %s " % (d["win"], d["pane"], d["repo"])
        w.border_subtitle = " %s %s " % (radar.GLYPH[st], radar.human(d["age"]))
        col = STATE_STYLE[st]
        topic = Text(d["topic"] or d["repo"], style="bold #f2f2f2", no_wrap=True, overflow="ellipsis")
        meta = Text(no_wrap=True, overflow="ellipsis")
        if d.get("branch"):
            meta.append("⎇ " + d["branch"], style="#777777")
        meta.append("  " + d["session"], style="#4a4a4a")
        if st == "waiting":
            now = Text("◆ " + (d["msg"] or "espera tu respuesta"), style="bold " + col, no_wrap=True,
                       overflow="ellipsis")
        elif st == "done":
            now = Text("◉ terminó · sin revisar", style="bold " + col, no_wrap=True, overflow="ellipsis")
        elif st == "working":
            now = Text("● " + (d["doing"] or "trabajando"), style=col, no_wrap=True, overflow="ellipsis")
        else:
            now = Text("○ " + (d["doing"] or "listo"), style="#777777", no_wrap=True, overflow="ellipsis")
        tail = Text("\n".join(l.strip()[:120] for l in d["tail"][-3:]), style="#5a5a5a", no_wrap=True,
                    overflow="ellipsis")
        w.update(Group(topic, meta, now, timeline(d["id"], events, time.time()), tail))

    def _srv_card(self, w, d, events):
        down = d["kind"] == "down"
        w.set_classes({"down" if down else "srv"} | ({"sel"} if "sel" in w.classes else set()))
        w.border_title = " %d.%d · %s " % (d["win"], d["pane"], d["repo"])
        if down:
            w.border_subtitle = " ✗ caído "
            top = Text.assemble(("✗ :%s" % d["port"], "bold #ff6464"), ("  " + d["task"], "#777777"))
        else:
            ok = d["healthy"]
            mark = ("✓ acepta conexiones", "#62c48a") if ok else (("✗ no acepta conexiones", "#ff6464") if ok is False
                                                         else ("…", "#777777"))
            w.border_subtitle = " ▲ %s " % radar.human(d["uptime"])
            ports = "" if len(d["ports"]) < 2 else "  +" + ",".join(map(str, d["ports"][1:4]))
            top = Text.assemble(("▲ :%s" % d["port"], "bold #5fb3dc"), ("  " + d["task"], "#a9dcf3"),
                                (ports, "#4a4a4a"), ("   ", ""), mark)
        q = self.hist.get(d["id"], [0])
        mx = max(q) or 1
        spark = Text("".join(SPARK[min(8, round(v / mx * 8))] for v in q), style="#5fb3dc", no_wrap=True)
        spark.append("  log", style="#3a3a3a")
        tail = Text("\n".join(l.strip()[:160] for l in d["tail"][-2:]), style="#5a5a5a", no_wrap=True,
                    overflow="ellipsis")
        w.update(Group(top, spark, tail))

    def _mark(self):
        cards = list(self.query_one("#cards").children) + list(self.query_one("#servers").children)
        for i, w in enumerate(cards):
            w.set_class(i == self.sel, "sel")
        if cards and self.sel < len(cards):
            cards[self.sel].scroll_visible(animate=False)

    # ------------------------------------------------------------ acciones
    def action_move(self, delta):
        if not self.items:
            return
        if abs(delta) > 1:
            delta = self.cols if delta > 0 else -self.cols
        self.sel = max(0, min(len(self.items) - 1, self.sel + delta))
        self._mark()

    def action_toggle_filter(self):
        self.only_active = not self.only_active
        self.sel = 0
        self.refresh_data()

    def action_jump_n(self, n):
        if n - 1 < len(self.items):
            self.sel = n - 1
            self.action_jump()

    def action_jump(self):
        if not self.items:
            return
        pid = self.items[self.sel]["id"]
        subprocess.run([radar.TMUX, "switch-client", "-t", pid, ";", "select-window", "-t", pid, ";",
                        "select-pane", "-t", pid], capture_output=True)
        self.exit()


if __name__ == "__main__":
    Mission().run()
