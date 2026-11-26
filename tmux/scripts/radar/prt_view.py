#!/usr/bin/env python3
"""Pestañas "Mis PRs" y "Reviewer" de la barra lateral de claude-radar.

sidebar.py llama a render() para dibujar y a key()/click() para la interacción. Lee el cache que
escribe `prt.py fetch`; nunca llama a GitHub por su cuenta salvo cuando pides refrescar (r).
Compatible con /usr/bin/python3 (3.9).
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prt  # noqa: E402
import radar  # noqa: E402

R = "\033[0m"
B = "\033[1m"
C = prt.COL
SEL_BG = "#2c2c2c"
TAB_BG = "#3a3a3a"
FEATURE = "#9ec3e6"
TABS = [("claude", "Claude"), ("mine", "Mis PRs"), ("review", "Reviewer"), ("release", "Releases")]
TAB_REQUEST = os.path.join(prt.STATE_DIR, "tab_request")


def fg(h):
    h = h.lstrip("#")
    return "\033[38;2;%d;%d;%dm" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bg(h):
    h = h.lstrip("#")
    return "\033[48;2;%d;%d;%dm" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mk(segs, W, right=(), hl=None):
    """Arma una línea: segmentos a la izquierda (se recortan) y a la derecha (se respetan)."""
    rplain = "".join(t for t, _, _ in right)
    room = W - radar.width(rplain) - (1 if right else 0)
    out, used = "", 0
    for t, c, b in segs:
        if used >= room:
            break
        if radar.width(t) > room - used:
            t = radar.fit(t, room - used, pad=False)
        out += (B if b else "") + fg(c) + t + R
        used += radar.width(t)
    out += " " * max(0, W - used - radar.width(rplain))
    for t, c, b in right:
        out += (B if b else "") + fg(c) + t + R
    if hl:
        out = bg(hl) + out.replace(R, R + bg(hl)) + R
    return out


def wrap(text, n, max_lines=3):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        if radar.width(cur + " " + w) > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = radar.fit(lines[-1] + " …", n, pad=False)
    return lines


# ───────────────────────── estado de la interfaz ─────────────────────────

class UI:
    def __init__(self):
        d = prt.load_json(prt.UI_F, {})
        self.tab = d.get("tab", "claude")
        self.sel = d.get("sel", {})
        self.open = d.get("open", {})          # {tab: {fila: bool}} plegados elegidos a mano
        self.detail = d.get("detail", True)
        self.group = d.get("group", "feature")
        self.scroll = {}
        self.rows = []
        self.tab_x = []
        self.cache = (0, None)
        self.flash = ("", 0)
        self.pending = None   # momento en que se pidió un refresco con `r`
        self.check_request()

    def save(self):
        prt.save_json(prt.UI_F, {"tab": self.tab, "sel": self.sel, "open": self.open,
                                 "detail": self.detail, "group": self.group})

    def check_request(self):
        """radar-sidebar.sh deja aquí la pestaña pedida con prefix P."""
        try:
            with open(TAB_REQUEST) as f:
                t = f.read().strip()
            os.remove(TAB_REQUEST)
        except OSError:
            return False
        if t in dict(TABS):
            self.tab = t
            self.save()
            return True
        return False

    def state(self):
        try:
            m = os.path.getmtime(prt.STATE_F)
        except OSError:
            return {}
        if self.cache[0] != m:
            self.cache = (m, prt.load_json(prt.STATE_F, {}))
        return self.cache[1] or {}

    def is_open(self, rid, default):
        return self.open.get(self.tab, {}).get(rid, default)

    def set_open(self, rid, val):
        self.open.setdefault(self.tab, {})[rid] = val
        self.save()

    def say(self, msg):
        self.flash = (msg, time.time() + 3)


# ───────────────────────── árbol ─────────────────────────

def glyph(st):
    col = C.get(prt.GCOL.get(st, st), C["fg"])
    return prt.GLYPH.get(st, "·"), col


def summary(lst):
    segs = []
    c = prt.counts(lst)
    for k in ("changes", "foreign", "dismissed", "conflict", "approved", "waiting", "draft",
              "rv_pending", "rv_new", "rv_changes", "rv_commented", "rv_approved", "rel_other", "new"):
        if c.get(k):
            g, col = glyph(k)
            segs.append(("%s%d " % (g, c[k]), col, k in prt.MINE_ACTION + prt.REVIEW_ACTION))
    merged = sum(1 for i in lst if i["kind"] == "merged")
    closed = sum(1 for i in lst if i["kind"] == "closed")
    if closed:
        segs.append(("✕%d " % closed, C["closed"], False))
    if merged:
        segs.append(("✔%d" % merged, C["merged"], False))
        segs.append(("/%d" % len(lst), C["dim"], False))
    return segs


def pr_row(it, prefix):
    g, col = glyph(it["status"])
    segs = [(prefix, C["faint"], False), (g + " ", col, False)]
    if "new" in it["flags"]:
        segs[-1] = (g, col, False)
        segs.append(("★", C["new"], False))
    done = it["kind"] != "open"
    segs.append((it["short"], C["dim"] if done else C["fg"], False))
    right = []
    if "conflict" in it["flags"] and it["status"] != "conflict":
        right.append(("⚠ ", C["conflict"], False))
    rcol = C["dim"] if it["status"] in ("waiting", "draft", "merged", "rv_commented") else col
    right.append((it["reason"], rcol, False))
    return segs, right


def build(ui, now):
    st = ui.state()
    tab = ui.tab
    its = prt.items(st, tab, now=now) if st else []
    if ui.group == "repo":
        for it in its:
            it["feature"] = it["short"].split("#")[0]
    active, done = prt.features(its, now)
    rows = []

    def add(rid, segs, right=(), item=None, lst=None, toggle=None, opened=False):
        rows.append({"id": rid, "segs": segs, "right": list(right), "item": item, "lst": lst,
                     "toggle": toggle, "opened": opened})

    def feature_children(name, lst, indent):
        open_ = sorted([i for i in lst if i["kind"] == "open"],
                       key=lambda i: (prt.RANK.get(i["status"], 9), i["short"]))
        closed = [i for i in lst if i["kind"] == "closed"]
        merged = sorted([i for i in lst if i["kind"] == "merged"],
                        key=lambda i: -(prt.ts(i["node"].get("mergedAt")) or 0))
        kids = open_ + closed
        for n, it in enumerate(kids):
            last = n == len(kids) - 1 and not merged
            segs, right = pr_row(it, indent + ("└ " if last else "├ "))
            add("p:" + it["key"], segs, right, item=it)
        if merged:
            mid = "m:" + name
            mo = ui.is_open(mid, False)
            g = "▾" if mo else "▸"
            word = "liberado" if tab == "release" else "mergeado"
            add(mid, [(indent + "└ ", C["faint"], False), ("✔ ", C["merged"], False),
                      ("%d %s%s %s" % (len(merged), word, "" if len(merged) == 1 else "s", g), C["dim"], False)],
                lst=merged, toggle=mid, opened=mo)
            if mo:
                for n, it in enumerate(merged):
                    segs, right = pr_row(it, indent + "  " + ("└ " if n == len(merged) - 1 else "├ "))
                    add("p:" + it["key"], segs, right, item=it)

    for name, lst in active:
        fid = "f:" + name
        acts = any(i["status"] in prt.MINE_ACTION + prt.REVIEW_ACTION or "conflict" in i["flags"]
                   for i in lst if i["kind"] == "open")
        fo = ui.is_open(fid, acts or tab == "release")
        add(fid, [("▾ " if fo else "▸ ", C["dim"], False), (name, FEATURE if acts else C["dim"], acts)],
            summary(lst), lst=lst, toggle=fid, opened=fo)
        if fo:
            feature_children(name, lst, "  ")
    if done:
        rows.append(None)
        did = "d:"
        do = ui.is_open(did, False)
        add(did, [("▾ " if do else "▸ ", C["dim"], False), (("solo liberados (%d)" if tab == "release" else "terminadas (%d)") % len(done), C["dim"], False)],
            toggle=did, lst=[i for _, l in done for i in l], opened=do)
        if do:
            for name, lst in done:
                fid = "f:" + name
                fo = ui.is_open(fid, False)
                add(fid, [("  ", C["faint"], False), ("▾ " if fo else "▸ ", C["dim"], False), (name, C["dim"], False)],
                    summary(lst), lst=lst, toggle=fid, opened=fo)
                if fo:
                    feature_children(name, lst, "    ")
    hidden = [i for i in its if i["hidden"] and i["kind"] == "open"]
    if hidden:
        hid = "h:"
        ho = ui.is_open(hid, False)
        add(hid, [("▾ " if ho else "▸ ", C["dim"], False), ("ocultos (%d)" % len(hidden), C["dim"], False)],
            toggle=hid, lst=hidden, opened=ho)
        if ho:
            for n, it in enumerate(hidden):
                segs, right = pr_row(it, "  " + ("└ " if n == len(hidden) - 1 else "├ "))
                add("p:" + it["key"], segs, right, item=it)
    return _blank_aware(rows)


def _blank_aware(rows):
    out = []
    for r in rows:
        out.append(r if r is not None else {"id": None, "segs": [], "right": [], "item": None,
                                             "lst": None, "toggle": None})
    return out


# ───────────────────────── detalle ─────────────────────────

def detail(row, W, now, cfg, me=""):
    if not row or not row.get("id"):
        return []
    out = []
    it = row.get("item")
    if it:
        n = it["node"]
        g, col = glyph(it["status"])
        if it["kind"] == "open":
            age = "abierto " + prt.ago(n.get("createdAt"), now)
        elif it["kind"] == "merged":
            age = "merge " + prt.when(prt.ts(n.get("mergedAt")), now)
        else:
            age = "cerrado " + prt.when(prt.ts(n.get("closedAt")), now)
        out.append(mk([(it["short"], C["white"], True)], W, [("%s · %s" % (it["feature"], age), C["dim"], False)]))
        for line in wrap(n.get("title"), W - 1, 2):
            out.append(mk([(line, C["fg"], False)], W))
        out.append(mk([("estado   ", C["dim"], False), (g + " " + it["reason"], col, False)], W))
        if _CUR_TAB[0] == "release":
            out.append(mk([("promueve ", C["dim"], False), ("%s → %s" % (n.get("headRefName"), n.get("baseRefName")), C["fg"], False)], W))
            prs = n.get("_my_prs") or []
            if prs:
                out.append(mk([("tuyos    ", C["dim"], False), (" ".join(prs), C["foreign"], False)], W))
            elif n.get("_my_commits"):
                out.append(mk([("tuyos    ", C["dim"], False), ("%d commits" % n["_my_commits"], C["foreign"], False)], W))
            elif n.get("_authored"):
                out.append(mk([("tuyos    ", C["dim"], False), ("lo abriste tú", C["foreign"], False)], W))
            else:
                out.append(mk([("tuyos    ", C["dim"], False), ("servicio tuyo, sin commits tuyos", C["dim"], False)], W))
        if "conflict" in it["flags"]:
            out.append(mk([("         ", C["dim"], False), ("⚠ conflicto con " + (n.get("baseRefName") or "base"),
                                                          C["conflict"], False)], W))
        if "dismissed" in it["flags"] and it["status"] != "dismissed":
            out.append(mk([("         ", C["dim"], False), ("↺ aprobación descartada", C["dismissed"], False)], W))
        if it["kind"] == "open":
            if ui_tab_is_review(it):
                out.append(mk([("autor    ", C["dim"], False), ((n.get("author") or {}).get("login", "?"), C["fg"], False)], W))
            req = prt.requested(n)
            last_by = {}
            for r in prt.reviews_of(n):
                last_by[r["author"]["login"]] = r["state"]
            parts = [(r + " pendiente", C["waiting"]) for r in req]
            names = {"APPROVED": ("✓", C["approved"]), "CHANGES_REQUESTED": ("✎", C["changes"]),
                     "COMMENTED": ("comentó", C["dim"]), "DISMISSED": ("↺", C["dismissed"])}
            for a, s in last_by.items():
                if a in req or a == me or a in prt.ME_NAMES:
                    continue
                t, c = names.get(s, (s.lower(), C["dim"]))
                parts.append(("%s %s" % (a, t), c))
            if parts:
                segs = [("reviews  ", C["dim"], False)]
                for k, (t, c) in enumerate(parts[:3]):
                    segs.append((("" if k == 0 else " · ") + t, c, False))
                out.append(mk(segs, W))
            else:
                out.append(mk([("reviews  ", C["dim"], False), ("sin reviewer", C["changes"], False)], W))
            ch = prt.checks_of(n)
            if ch["total"]:
                dots = min(ch["total"], 10)
                okd = round(dots * ch["ok"] / ch["total"])
                segs = [("checks   ", C["dim"], False), ("●" * okd, C["approved"], False),
                        ("●" * len(ch["failed"][:dots - okd]), C["changes"], False),
                        ("●" * max(0, dots - okd - len(ch["failed"][:dots - okd])), C["faint"], False),
                        (" %d/%d" % (ch["ok"], ch["total"]), C["dim"], False)]
                if ch["failed"]:
                    segs.append((" · falló " + ch["failed"][0], C["changes"], False))
                out.append(mk(segs, W))
            else:
                out.append(mk([("checks   ", C["dim"], False), ("sin checks", C["dim"], False)], W))
        branch = n.get("headRefName") or ""
        alive = n.get("headRef") is not None or it["kind"] == "open"
        out.append(mk([("rama     ", C["dim"], False), (branch, C["fg"] if alive else C["dim"], False)]
                      + ([] if alive else [(" (borrada)", C["dim"], False)]), W))
        ids = n.get("_linear") or []
        lin = (cfg.get("linear") or {})
        if ids:
            segs = [("linear   ", C["dim"], False), (" ".join(ids), C["new"], False)]
            if not lin.get("enabled"):
                segs.append((" · estado sin consultar", C["faint"], False))
            out.append(mk(segs, W))
        else:
            out.append(mk([("linear   ", C["dim"], False), ("sin issue", C["dim"], False)], W))
        commits = [] if _CUR_TAB[0] == "release" else (it.get("foreign") or [])
        label = "commits ajenos" if commits else "últimos commits"
        if not commits and it["kind"] == "open" and _CUR_TAB[0] != "release":
            commits = prt.commits_of(n)[-3:]
        if commits:
            out.append(mk([(label, C["dim"], False)], W))
            for c in commits[-4:]:
                t = prt.when(prt.ts(c.get("committedDate")), now).replace("hoy ", "")
                a = prt.who(c)
                a = "tú" if a in ("@me", me) else a
                out.append(mk([(t + " ", C["dim"], False), (a + " ", C["foreign"] if a != "tú" else C["fg"], False),
                               (c.get("messageHeadline") or "", C["fg"], False)], W))
        return out
    lst = row.get("lst") or []
    title = row["id"].split(":", 1)[1] or {"d:": "terminadas", "h:": "ocultos"}.get(row["id"], "")
    if row["id"].startswith("m:"):
        title = ("liberados de " if _CUR_TAB[0] == "release" else "mergeados de ") + title
    out.append(mk([(title, FEATURE, True)], W, summary(lst)))
    opn = [i for i in lst if i["kind"] == "open"]
    mer = [i for i in lst if i["kind"] == "merged"]
    clo = [i for i in lst if i["kind"] == "closed"]
    word = "liberados" if _CUR_TAB[0] == "release" else "mergeados"
    out.append(mk([("abiertos %d · %s %d · cerrados %d" % (len(opn), word, len(mer), len(clo)), C["dim"], False)], W))
    act = [i for i in opn if i["status"] in prt.MINE_ACTION + prt.REVIEW_ACTION]
    if act:
        out.append(mk([("te toca  ", C["dim"], False), (", ".join(i["short"] for i in act), C["foreign"], False)], W))
    wait = [i for i in opn if i["status"] in ("waiting", "rv_commented", "rv_changes", "rv_approved", "rel_other", "draft")]
    if wait:
        out.append(mk([("esperan  ", C["dim"], False), (", ".join(i["short"] for i in wait), C["fg"], False)], W))
    ids = []
    for i in lst:
        for x in i["node"].get("_linear") or []:
            if x not in ids:
                ids.append(x)
    out.append(mk([("linear   ", C["dim"], False), (" ".join(ids) if ids else "sin issues", C["new"] if ids else C["dim"], False)], W))
    if lst:
        last = max(lst, key=lambda i: prt.ts(i["node"].get("updatedAt")) or 0)
        out.append(mk([("último   ", C["dim"], False), ("%s %s" % (last["short"], prt.ago(last["node"].get("updatedAt"), now)), C["fg"], False)], W))
    return out


_CUR_TAB = ["mine"]


def ui_tab_is_review(it):
    return _CUR_TAB[0] == "review"


# ───────────────────────── dibujo ─────────────────────────

def tab_bar(ui, W):
    st = ui.state()
    segs, x, ui.tab_x = [], 0, []
    badges = {}
    if st:
        for t in ("mine", "review", "release"):
            c = prt.counts(prt.items(st, t))
            n = sum(v for k, v in c.items() if k in prt.MINE_ACTION + prt.REVIEW_ACTION)
            if n:
                badges[t] = n
    line = ""
    for key, label in TABS:
        txt = " %s%s " % (label, (" %d" % badges[key]) if key in badges else "")
        w = radar.width(txt)
        ui.tab_x.append((x, x + w, key))
        if key == ui.tab:
            line += bg(TAB_BG) + fg(C["white"]) + B + txt + R
        else:
            line += fg(C["foreign"] if key in badges else C["dim"]) + txt + R
        x += w
    return line + " " * max(0, W - x)


def footer(ui, W, now):
    msg, until = ui.flash
    if msg and now < until:
        return mk([(" " + msg, C["approved"], False)], W)
    # Consulta a GitHub en curso (la de `r` o la automática): se ve mientras dure.
    try:
        busy = now - os.path.getmtime(prt.LOCK)
    except OSError:
        busy = None
    if busy is not None:
        return mk([(" ⟳ actualizando… %ds" % busy, C["foreign"], False)], W)
    if ui.pending:
        if now - ui.pending < 3:   # el proceso aún no toma el lock
            return mk([(" ⟳ actualizando…", C["foreign"], False)], W)
        ui.pending = None
        if os.path.exists(prt.ERROR_F):
            with open(prt.ERROR_F) as f:
                ui.flash = ("✗ " + f.read().strip()[:W - 4], now + 5)
            return mk([(" " + ui.flash[0], C["changes"], False)], W)
        ui.say("✓ actualizado")
        return mk([(" ✓ actualizado", C["approved"], False)], W)
    st = ui.state()
    age = ""
    if st.get("fetched_at"):
        s = now - st["fetched_at"]
        age = "ahora" if s < 60 else ("hace %d min" % (s // 60) if s < 3600 else "hace %d h" % (s // 3600))
    err = os.path.exists(prt.ERROR_F)
    keys = " ⏎ abrir d diff v visto L linear D detalle g agrupar r ⟳"
    return mk([(keys, C["faint"], False)], W, [(("✗ " if err else "") + age + " ", C["changes"] if err else C["faint"], False)])


def render(ui, W, H):
    now = time.time()
    _CUR_TAB[0] = ui.tab
    cfg = prt.config()
    rows = build(ui, now)
    ui.rows = rows
    lines, targets = [tab_bar(ui, W), mk([("─" * W, C["faint"], False)], W)], [("tabs", None), None]
    st = ui.state()
    if not st:
        msg = "Cargando PRs…" if not os.path.exists(prt.ERROR_F) else "No se pudo leer GitHub: " + \
            open(prt.ERROR_F).read().strip()
        for line in wrap(msg, W - 2, 4):
            lines.append(mk([(" " + line, C["dim"], False)], W))
            targets.append(None)
        lines += [""] * (H - len(lines) - 1)
        targets += [None] * (H - len(targets) - 1)
        lines.append(footer(ui, W, now))
        targets.append(None)
        return lines, targets
    sel_ids = [r["id"] for r in rows if r["id"]]
    sel = ui.sel.get(ui.tab)
    if sel not in sel_ids:
        sel = next((r["id"] for r in rows if r["id"] and r["id"].startswith("p:")), sel_ids[0] if sel_ids else None)
        ui.sel[ui.tab] = sel
    selrow = next((r for r in rows if r["id"] == sel), None)
    det = detail(selrow, W, now, cfg, st.get("me", "")) if ui.detail else []
    dh = min(len(det), max(6, int(H * 0.45))) if det else 0
    tree_h = max(3, H - 3 - (dh + 1 if dh else 0))
    idx = next((i for i, r in enumerate(rows) if r["id"] == sel), 0)
    top = ui.scroll.get(ui.tab, 0)
    if idx < top:
        top = idx
    elif idx >= top + tree_h:
        top = idx - tree_h + 1
    top = max(0, min(top, max(0, len(rows) - tree_h)))
    ui.scroll[ui.tab] = top
    for r in rows[top:top + tree_h]:
        lines.append(mk(r["segs"], W, r["right"], hl=SEL_BG if r["id"] == sel and r["id"] else None))
        targets.append(("row", r["id"]) if r["id"] else None)
    pad = tree_h - len(rows[top:top + tree_h])
    lines += [" " * W] * pad
    targets += [None] * pad
    if dh:
        lines.append(mk([("─" * W, C["faint"], False)], W))
        targets.append(None)
        lines += det[:dh]
        targets += [None] * dh
    while len(lines) < H - 1:
        lines.append(" " * W)
        targets.append(None)
    lines = lines[:H - 1]
    targets = targets[:H - 1]
    lines.append(footer(ui, W, now))
    targets.append(None)
    return lines, targets


# ───────────────────────── interacción ─────────────────────────

def open_url(url):
    if url:
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def refresh(ui):
    if os.path.isdir(prt.LOCK):
        ui.pending = time.time()
        ui.say("ya se está actualizando…")
        return
    subprocess.Popen(["/usr/bin/python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prt.py"), "fetch"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    ui.pending = time.time()
    ui.flash = ("", 0)


def selected(ui):
    sel = ui.sel.get(ui.tab)
    return next((r for r in ui.rows if r["id"] == sel), None)


def move(ui, d):
    ids = [r["id"] for r in ui.rows if r["id"]]
    if not ids:
        return
    cur = ui.sel.get(ui.tab)
    i = ids.index(cur) if cur in ids else 0
    ui.sel[ui.tab] = ids[max(0, min(len(ids) - 1, i + d))]
    ui.save()


def key(ui, k):
    """Devuelve True si hay que redibujar."""
    tabs = [t for t, _ in TABS]
    if k in ("1", "2", "3", "4"):
        ui.tab = tabs[int(k) - 1]
    elif k == "\t":
        ui.tab = tabs[(tabs.index(ui.tab) + 1) % len(tabs)]
    elif k == "BTAB":
        ui.tab = tabs[(tabs.index(ui.tab) - 1) % len(tabs)]
    elif ui.tab == "claude":
        return False
    elif k in ("j", "DOWN"):
        move(ui, 1)
    elif k in ("k", "UP"):
        move(ui, -1)
    elif k == "J":
        move(ui, 10)
    elif k == "K":
        move(ui, -10)
    elif k in ("h", "LEFT", "l", "RIGHT", " ", "\r", "\n"):
        r = selected(ui)
        if not r:
            return False
        if r.get("toggle"):
            cur = r["opened"]
            want = {"h": False, "LEFT": False, "l": True, "RIGHT": True}.get(k, not cur)
            ui.set_open(r["toggle"], want)
        elif r.get("item") and k in ("\r", "\n"):
            open_url(r["item"]["node"].get("url"))
        elif r.get("item") and k in ("h", "LEFT"):
            # subir a la feature que lo contiene
            i = ui.rows.index(r)
            for p in reversed(ui.rows[:i]):
                if p.get("toggle") and p["id"].startswith(("f:", "m:")):
                    ui.sel[ui.tab] = p["id"]
                    break
    elif k == "d":
        r = selected(ui)
        it = r and r.get("item")
        if it:
            n = it["node"]
            fo = it.get("foreign") or []
            base = it.get("base_oid")
            if fo and base:
                open_url("%s/files/%s..%s" % (n["url"], base, fo[-1]["oid"]))
            else:
                open_url(n["url"] + "/files")
    elif k == "v":
        r = selected(ui)
        if r:
            keys = [r["item"]["key"]] if r.get("item") else [i["key"] for i in (r.get("lst") or []) if i["kind"] == "open"]
            prt.mark_seen(keys)
            ui.say("marcado visto: %d PR%s" % (len(keys), "" if len(keys) == 1 else "s"))
    elif k == "L":
        r = selected(ui)
        ids = []
        for i in ([r["item"]] if r and r.get("item") else (r or {}).get("lst") or []):
            ids += [x for x in i["node"].get("_linear") or [] if x not in ids]
        ws = (prt.config().get("linear") or {}).get("workspace")
        if ids and ws:
            open_url("https://linear.app/%s/issue/%s" % (ws, ids[0]))
        else:
            ui.say("sin issue de Linear")
    elif k == "D":
        ui.detail = not ui.detail
    elif k == "g":
        ui.group = "repo" if ui.group == "feature" else "feature"
        ui.say("agrupado por " + ("repo" if ui.group == "repo" else "feature"))
    elif k == "r":
        refresh(ui)
    else:
        return False
    ui.save()
    return True


def click(ui, x, y, targets, button):
    """y empieza en 1. Devuelve True si hay que redibujar."""
    if button in (64, 65):
        if ui.tab != "claude":
            move(ui, -3 if button == 64 else 3)
            return True
        return False
    if not (0 < y <= len(targets)):
        return False
    t = targets[y - 1]
    if t and t[0] == "tabs":
        for a, b, k in ui.tab_x:
            if a <= x - 1 < b:
                ui.tab = k
                ui.save()
                return True
        return False
    if t and t[0] == "row":
        if ui.sel.get(ui.tab) == t[1]:
            r = selected(ui)
            if r and r.get("toggle"):
                return key(ui, " ")
            if r and r.get("item"):
                open_url(r["item"]["node"].get("url"))
            return False
        ui.sel[ui.tab] = t[1]
        ui.save()
        return True
    return False
