#!/usr/bin/env python3
"""prt: radar de PRs para la barra lateral y la barra de estado de tmux.

  prt.py fetch        consulta GitHub (una sola llamada GraphQL) y guarda el cache
  prt.py sum          recalcula @prt_sum (tercera línea de estado) desde el cache
  prt.py seen KEY     marca un PR como visto (KEY = repo#número)
  prt.py dump [mine|review]   imprime el estado derivado, para depurar

Archivos:
  ~/.config/prt/config.json        alias de repos y scopes, PRs ocultos, notas, Linear
  ~/.cache/prt/state.json          última foto de GitHub
  ~/.local/state/prt/known.json    PRs tuyos ya vistos (para seguir mergeados y cerrados)
  ~/.local/state/prt/seen.json     último commit que marcaste como visto por PR
  ~/.local/state/prt/ui.json       pestaña, plegados y selección de la barra lateral

Usa tu sesión de `gh`. Compatible con /usr/bin/python3 (3.9).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cache", "prt")
STATE_F = os.path.join(CACHE, "state.json")
ATTEMPT_F = os.path.join(CACHE, "last_attempt")
ERROR_F = os.path.join(CACHE, "last_error")
LOCK = os.path.join(CACHE, "fetch.lock")
STATE_DIR = os.path.join(HOME, ".local", "state", "prt")
KNOWN_F = os.path.join(STATE_DIR, "known.json")
SEEN_F = os.path.join(STATE_DIR, "seen.json")
UI_F = os.path.join(STATE_DIR, "ui.json")
CONFIG_F = os.path.join(HOME, ".config", "prt", "config.json")

TMUX = "/opt/homebrew/bin/tmux"
GH = shutil.which("gh") or "/opt/homebrew/bin/gh"

KEEP_DONE_DAYS = 14     # una feature terminada sale del panel 14 días después de su último merge/cierre
KNOWN_MAX_DAYS = 90     # mergeados más viejos se olvidan
BOOT_DAYS = 30          # primera carga: mergeados y cerrados de los últimos 30 días
RECENT_DAYS = 3         # en cada refresco: cerrados de los últimos 3 días (atrapa los que nacieron y murieron entre refrescos)
NEW_HOURS = 24          # ★ mientras el PR tenga menos de 24 h en el radar y no lo marques visto

# Colores (mismos tonos que claude-radar)
COL = dict(
    foreign="#e8a33d", dismissed="#c79bf0", changes="#ff6464", conflict="#ff6464",
    waiting="#b5b5b5", approved="#62c48a", draft="#777777", new="#5fb3dc",
    merged="#7ab4f0", closed="#c46a6a", fg="#d0d0d0", dim="#777777", faint="#4a4a4a", white="#f2f2f2",
)
GLYPH = dict(
    foreign="↻", dismissed="↺", changes="✎", conflict="⚠", waiting="◷", approved="✓",
    draft="◌", new="★", merged="✔", closed="✕",
    rv_pending="◷", rv_new="↻", rv_changes="✎", rv_approved="✓", rv_commented="◷",
    rel_other="⇡",
)
GCOL = dict(rv_pending="foreign", rv_new="foreign", rv_changes="waiting", rv_approved="approved",
            rv_commented="waiting", rel_other="waiting")
# Orden dentro de una feature: lo que te toca primero.
RANK = dict(changes=0, foreign=1, dismissed=2, approved=3, waiting=4, draft=5, closed=6, merged=7,
            rv_pending=0, rv_new=1, rv_changes=3, rv_commented=4, rv_approved=5, rel_other=4)
MINE_ACTION = ("changes", "foreign", "dismissed", "approved")
REVIEW_ACTION = ("rv_pending", "rv_new")

DEFAULT_CONFIG = {
    "repos": {},
    "me_names": [],
    "alias": {},
    "pins": {},
    "hidden": [],
    "notes": [],
    "linear": {"enabled": False, "workspace": "", "teams": []},
}

FRAGMENT = """
fragment F on PullRequest {
  id number title url state isDraft createdAt updatedAt mergedAt closedAt
  mergeable reviewDecision headRefName baseRefName body
  headRef { name }
  author { login }
  repository { name nameWithOwner }
  reviewRequests(first: 10) { nodes { requestedReviewer { __typename ... on User { login } ... on Team { name } } } }
  reviews(last: 40) { nodes { author { login } state submittedAt } }
  commits(last: 100) { totalCount nodes { commit { oid committedDate messageHeadline author { name user { login } } } } }
  lastCommit: commits(last: 1) { nodes { commit { statusCheckRollup { state
    contexts(first: 50) { nodes { __typename ... on CheckRun { name conclusion status } ... on StatusContext { context state } } } } } } }
}
"""
LIGHT = """
fragment L on PullRequest {
  id number title url state isDraft createdAt updatedAt mergedAt closedAt headRefName body
  headRef { name }
  author { login }
  repository { name nameWithOwner }
}
"""
QUERY = FRAGMENT + LIGHT + """
query($open: String!, $revreq: String!, $revby: String!, $merged: String!, $closed: String!, $ids: [ID!]!) {
  viewer { login }
  open: search(query: $open, type: ISSUE, first: 50) { nodes { ...F } }
  revreq: search(query: $revreq, type: ISSUE, first: 50) { nodes { ...F } }
  revby: search(query: $revby, type: ISSUE, first: 50) { nodes { ...F } }
  merged: search(query: $merged, type: ISSUE, first: 100) { nodes { ...L } }
  closed: search(query: $closed, type: ISSUE, first: 50) { nodes { ...L } }
  known: nodes(ids: $ids) { ...L }
  rateLimit { cost remaining resetAt }
}
"""

ME_NAMES = set()
REL_FRAGMENT = """
fragment RM on PullRequest {
  id number title url state isDraft createdAt updatedAt mergedAt closedAt headRefName baseRefName
  labels(first: 10) { nodes { name } }
  author { login }
  repository { name nameWithOwner }
  commits(last: 100) { totalCount nodes { commit { oid committedDate messageHeadline author { name user { login } } } } }
}
"""
REL_QUERY = FRAGMENT + REL_FRAGMENT + """
fragment RL on PullRequest { labels(first: 10) { nodes { name } } }

query($open: String!, $merged: String!) {
  open: search(query: $open, type: ISSUE, first: 40) { nodes { ...F ...RL } }
  merged: search(query: $merged, type: ISSUE, first: 60) { nodes { ...RM } }
}
"""
REL_DAYS = 14   # releases mergeados que se siguen mostrando
REL_LABELS = ("promote", "release", "hotfix")
REL_HEAD_RE = re.compile(r"(^|/)develop$|^promote/|(^|/)release/|^hotfix/|^cherry-pick/", re.I)
REL_TITLE_RE = re.compile(r"^\s*(\[hotfix\]|release\s*:|(promote|release|hotfix)(\(|:|\s)|chore\((promote|release)\))", re.I)
MY_PR_RE = re.compile(r"\(#(\d+)\)|pull request #(\d+)")
MARKER_RE = re.compile(r"<!--\s*feature:\s*([a-z0-9][a-z0-9-]*)\s*-->", re.I)
SCOPE_RE = re.compile(r"^\s*[a-z]+(?:\(([^)]+)\))?!?:", re.I)


# ───────────────────────── archivos ─────────────────────────

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_F, {}))
    ME_NAMES.clear()
    ME_NAMES.update(cfg.get("me_names") or [])
    return cfg


def ts(iso):
    if not iso:
        return None
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


# ───────────────────────── recolección ─────────────────────────

def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables})
    p = subprocess.run([GH, "api", "graphql", "--input", "-"], input=body, capture_output=True,
                       text=True, timeout=60)
    try:
        data = json.loads(p.stdout or "{}")
    except ValueError:
        data = {}
    if p.returncode != 0 and not data.get("data"):
        msg = (data.get("errors") or [{}])[0].get("message") or p.stderr.strip() or "gh falló"
        raise RuntimeError(msg)
    return data


def linear_ids(cfg, *texts):
    teams = [t.upper() for t in (cfg.get("linear") or {}).get("teams") or []]
    if not teams:
        return []
    rx = re.compile(r"(?<![A-Za-z0-9])(%s)-(\d{1,6})(?!\d)" % "|".join(map(re.escape, teams)), re.I)
    out = []
    for t in texts:
        for m in rx.finditer(t or ""):
            i = "%s-%s" % (m.group(1).upper(), m.group(2))
            if i not in out:
                out.append(i)
    # "(PV-2611/2612/2613)": números sueltos que siguen a un id con barra
    for t in texts:
        for m in re.finditer(r"\b([A-Z]{2,7})-(\d+)((?:/\d+)+)", t or ""):
            if m.group(1).upper() in teams:
                for n in m.group(3).strip("/").split("/"):
                    i = "%s-%s" % (m.group(1).upper(), n)
                    if i not in out:
                        out.append(i)
    return out


def slim(n, cfg):
    """Quita el body (puede ser grande) y deja lo que se usa de él."""
    body = n.pop("body", "") or ""
    m = MARKER_RE.search(body)
    n["_marker"] = m.group(1).lower() if m else None
    n["_linear"] = linear_ids(cfg, n.get("headRefName"), n.get("title"), body)
    return n


def take_lock():
    os.makedirs(CACHE, exist_ok=True)
    try:
        os.mkdir(LOCK)
        return True
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK) > 120:
            os.rmdir(LOCK)
            return take_lock()
        return False


def fetch():
    if not take_lock():
        return 0
    try:
        with open(ATTEMPT_F, "w") as f:
            f.write(str(int(time.time())))
        cfg = config()
        known = load_json(KNOWN_F, {})
        now = time.time()
        days = RECENT_DAYS if known else BOOT_DAYS
        since = datetime.fromtimestamp(now - days * 86400, timezone.utc).strftime("%Y-%m-%d")
        ids = sorted(known, key=lambda i: -(known[i].get("_first_seen") or 0))[:100]
        data = gql(QUERY, {
            "open": "is:pr is:open author:@me archived:false",
            "revreq": "is:pr is:open archived:false review-requested:@me",
            "revby": "is:pr is:open archived:false reviewed-by:@me -author:@me",
            "merged": "is:pr author:@me is:merged merged:>=%s" % since,
            "closed": "is:pr author:@me is:closed is:unmerged closed:>=%s" % since,
            "ids": ids,
        })
        d = data.get("data") or {}
        me = d["viewer"]["login"]

        def nodes(key):
            v = d.get(key) or {}
            return [n for n in (v.get("nodes") if isinstance(v, dict) else v) or [] if n and n.get("id")]

        mine = {}
        for key in ("known", "merged", "closed", "open"):   # "open" al final: es la foto más confiable del estado
            for n in nodes(key):
                if (n.get("author") or {}).get("login") == me:
                    mine[n["id"]] = n
        # PRs conocidos que esta vez no regresaron (borrados o sin acceso): se olvidan.
        # En la primera carga nada cuenta como nuevo (★).
        boot = not known
        new_known = {}
        for i, n in mine.items():
            slim(n, cfg)
            prev = known.get(i) or {}
            n["_first_seen"] = prev["_first_seen"] if prev.get("_first_seen") is not None else (0 if boot else now)
            if n["state"] == "MERGED" and now - (ts(n.get("mergedAt")) or now) > KNOWN_MAX_DAYS * 86400:
                continue
            if n["state"] == "CLOSED" and not n.get("headRef"):
                continue   # cerrado y con la rama borrada: deja de seguirse
            new_known[i] = n
        save_json(KNOWN_F, new_known)

        review = {}
        for key in ("revreq", "revby"):
            for n in nodes(key):
                if (n.get("author") or {}).get("login") != me:
                    prev = review.get(n["id"])
                    review[n["id"]] = slim(n, cfg) if not prev else prev
        old = load_json(STATE_F, {})
        first = {r["id"]: r.get("_first_seen") for r in old.get("review", [])}
        for i, n in review.items():
            n["_first_seen"] = first.get(i, 0 if not old else now)

        state = {"me": me, "fetched_at": now, "mine": list(new_known.values()),
                 "review": list(review.values()), "rate": d.get("rateLimit"),
                 "release": fetch_releases(cfg, me, new_known, old, now)}
        save_json(STATE_F, state)
        if os.path.exists(ERROR_F):
            os.remove(ERROR_F)
        set_sum(state)
        return 0
    except Exception as e:  # noqa: BLE001 — cualquier fallo queda visible en la barra
        os.makedirs(CACHE, exist_ok=True)
        with open(ERROR_F, "w") as f:
            f.write(str(e)[:200])
        set_sum(load_json(STATE_F, {}))
        return 1
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


def is_release(n):
    labels = {l["name"].lower() for l in ((n.get("labels") or {}).get("nodes") or []) if l}
    if labels & set(REL_LABELS):
        return True
    if (n.get("baseRefName") or "").split("/")[-1] not in ("main", "master"):
        return False
    return bool(REL_HEAD_RE.search(n.get("headRefName") or "") or REL_TITLE_RE.match(n.get("title") or ""))


def fetch_releases(cfg, me, known, old, now):
    """PRs de liberación/promote a main en los repos donde trabajas, que son tuyos o llevan commits tuyos."""
    repos = sorted({n["repository"]["nameWithOwner"] for n in known.values()} | set(cfg.get("release_repos") or []))
    if not repos:
        return old.get("release", [])
    rq = " ".join("repo:" + r for r in repos)
    since = datetime.fromtimestamp(now - REL_DAYS * 86400, timezone.utc).strftime("%Y-%m-%d")
    try:
        d = gql(REL_QUERY, {"open": "is:pr is:open base:main %s" % rq,
                            "merged": "is:pr is:merged base:main merged:>=%s %s" % (since, rq)}).get("data") or {}
    except RuntimeError:
        return old.get("release", [])
    first = {r["id"]: r.get("_first_seen") for r in old.get("release", [])}
    out = []
    for key in ("open", "merged"):
        for n in ((d.get(key) or {}).get("nodes") or []):
            if not n or not n.get("id") or not is_release(n):
                continue
            mine_c = [c["commit"] for c in (n.get("commits") or {}).get("nodes") or []
                      if c and c.get("commit") and who(c["commit"]) in (me, "@me")]
            authored = (n.get("author") or {}).get("login") in (me,) or (n.get("author") or {}).get("login") in ME_NAMES
            own_svc = service_of(cfg, n) in (cfg.get("my_services") or [])
            if not authored and not mine_c and not own_svc:
                continue
            prs = []
            for c in mine_c:
                m = MY_PR_RE.search(c.get("messageHeadline") or "")
                if m:
                    num = "#" + (m.group(1) or m.group(2))
                    if num not in prs:
                        prs.append(num)
            slim(n, cfg)
            n["_authored"] = authored
            n["_my_commits"] = len(mine_c)
            n["_my_prs"] = prs
            n["_own_service"] = own_svc
            n["_first_seen"] = first.get(n["id"], 0 if not old.get("release") else now)
            out.append(n)
    return out


def service_of(cfg, n):
    """Servicio que libera: label service:x > scope del título > rama > repo."""
    for l in ((n.get("labels") or {}).get("nodes") or []):
        if l and l["name"].lower().startswith("service:"):
            return l["name"].split(":", 1)[1].strip()
    t = n.get("title") or ""
    m = re.match(r"^\s*(?:\[hotfix\]\s*)?[a-z]+\(([^)]+)\)", t, re.I) or re.match(r"^\s*release\s*:\s*([\w.-]+)\s*(?:→|->|to\s)", t, re.I)
    if m and m.group(1).lower() not in ("promote", "release", "deps", "develop"):
        return m.group(1).strip()
    low = t.lower()
    for svc in sorted(cfg.get("my_services") or [], key=len, reverse=True):
        if svc.lower() in low:
            return svc
    h = n.get("headRefName") or ""
    m = re.match(r"^promote/(.+?)-to-main", h) or re.match(r"^([\w.-]+)/(?:develop|release/)", h) or \
        re.match(r"^release/prod-(.+)$", h)
    if m:
        return m.group(1)
    return short_repo(cfg, n["repository"]["name"])


def derive_release(n, me, seen, cfg, now):
    k = key_of(n)
    author = (n.get("author") or {}).get("login") or "?"
    mine = n.get("_authored")
    out = {"key": k, "short": "%s#%d" % (short_repo(cfg, n["repository"]["name"]), n["number"]),
           "feature": service_of(cfg, n), "node": n, "flags": [], "foreign": [],
           "kind": "merged" if n["state"] == "MERGED" else "open"}
    who_ = "tú" if mine else author
    mine_n = len(n.get("_my_prs") or []) or n.get("_my_commits", 0)
    if mine:
        extra = ""
    elif mine_n:
        extra = " · %d tuyo%s" % (mine_n, "" if mine_n == 1 else "s")
    else:
        extra = " · tu servicio"
    if out["kind"] == "merged":
        out.update(status="merged", reason="liberado " + when(ts(n.get("mergedAt")), now))
        return out
    if n.get("mergeable") == "CONFLICTING":
        out["flags"].append("conflict")
    if is_new(n, seen, now):
        out["flags"].append("new")
    dec = n.get("reviewDecision")
    if n.get("isDraft"):
        out.update(status="draft", reason="draft · " + who_ + extra)
    elif dec == "CHANGES_REQUESTED":
        out.update(status="changes" if mine else "rel_other", reason="cambios · " + who_ + extra)
    elif dec == "APPROVED":
        out.update(status="approved" if mine else "rel_other", reason="aprobado · " + who_ + extra)
    else:
        req = requested(n)
        if mine:
            out.update(status="waiting", reason="%s · %s" % (",".join(req) if req else "sin reviewer", ago(n.get("updatedAt"), now)))
        else:
            out.update(status="rel_other", reason=who_ + extra)
    return out


# ───────────────────────── derivación ─────────────────────────

def short_repo(cfg, repo):
    return (cfg.get("repos") or {}).get(repo, repo)


def key_of(n):
    return "%s#%d" % (n["repository"]["name"], n["number"])


def feature_of(cfg, n):
    alias = cfg.get("alias") or {}
    k = key_of(n)
    if (cfg.get("pins") or {}).get(k):
        return cfg["pins"][k]
    if n.get("_marker"):
        return alias.get(n["_marker"], n["_marker"])
    m = SCOPE_RE.match(n.get("title") or "")
    if m and m.group(1):
        scope = m.group(1).strip().lower()
        return alias.get(scope, scope)
    repo = short_repo(cfg, n["repository"]["name"])
    return alias.get(repo, repo)


def who(c):
    """Login del autor; un commit sin usuario ligado que lleva uno de tus nombres cuenta como tuyo."""
    a = (c.get("commit") or c).get("author") or {}
    login = (a.get("user") or {}).get("login")
    if login:
        return "@me" if login in ME_NAMES else login
    name = a.get("name") or "?"
    return "@me" if name in ME_NAMES else name


def commits_of(n):
    return [c["commit"] for c in (n.get("commits") or {}).get("nodes") or [] if c and c.get("commit")]


def head_oid(n):
    cs = commits_of(n)
    return cs[-1]["oid"] if cs else None


def requested(n):
    out = []
    for r in (n.get("reviewRequests") or {}).get("nodes") or []:
        rr = (r or {}).get("requestedReviewer") or {}
        out.append(rr.get("login") or rr.get("name") or "?")
    return out


def reviews_of(n):
    return [r for r in (n.get("reviews") or {}).get("nodes") or [] if r and r.get("author")]


def checks_of(n):
    try:
        roll = n["lastCommit"]["nodes"][0]["commit"]["statusCheckRollup"]
    except (KeyError, IndexError, TypeError):
        roll = None
    if not roll:
        return {"state": None, "total": 0, "ok": 0, "failed": []}
    ok, failed, total = 0, [], 0
    for c in (roll.get("contexts") or {}).get("nodes") or []:
        if not c:
            continue
        total += 1
        if c.get("__typename") == "CheckRun":
            res, name = (c.get("conclusion") or c.get("status") or ""), c.get("name")
        else:
            res, name = c.get("state") or "", c.get("context")
        res = res.upper()
        if res in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            ok += 1
        elif res in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"):
            failed.append(name)
    return {"state": roll.get("state"), "total": total, "ok": ok, "failed": failed}


def is_new(n, seen, now):
    k = key_of(n)
    fs = n.get("_first_seen")
    fs = now if fs is None else fs
    return now - fs < NEW_HOURS * 3600 and (seen.get(k) or {}).get("ts", 0) < fs


def derive_mine(n, me, seen, cfg, now):
    k = key_of(n)
    out = {"key": k, "short": "%s#%d" % (short_repo(cfg, n["repository"]["name"]), n["number"]),
           "feature": feature_of(cfg, n), "node": n, "flags": [], "foreign": []}
    if n["state"] == "MERGED":
        out.update(status="merged", reason="merge " + when(ts(n.get("mergedAt")), now), kind="merged")
        return out
    if n["state"] == "CLOSED":
        out.update(status="closed", reason="cerrado · rama viva", kind="closed")
        return out
    out["kind"] = "open"
    cs = commits_of(n)
    mine_ = (me, "@me")
    last_mine = max([i for i, c in enumerate(cs) if who(c) in mine_] or [-1])
    after = cs[last_mine + 1:]
    s = (seen.get(k) or {}).get("oid")
    oids = [c["oid"] for c in after]
    if s in oids:
        after = after[oids.index(s) + 1:]
    foreign = [c for c in after if who(c) not in mine_]
    out["foreign"] = foreign
    out["base_oid"] = cs[last_mine]["oid"] if last_mine >= 0 else None
    revs = reviews_of(n)
    last_by = {}
    for r in revs:
        last_by[r["author"]["login"]] = r
    dismissed = [a for a, r in last_by.items() if r["state"] == "DISMISSED"]
    if n.get("mergeable") == "CONFLICTING":
        out["flags"].append("conflict")
    if dismissed and n.get("reviewDecision") != "APPROVED":
        out["flags"].append("dismissed")
    if is_new(n, seen, now):
        out["flags"].append("new")
    my_last_ts = ts(cs[last_mine]["committedDate"]) if last_mine >= 0 else 0
    cr = [r for r in revs if r["state"] == "CHANGES_REQUESTED"]
    if n.get("isDraft"):
        out.update(status="draft", reason="draft")
    elif n.get("reviewDecision") == "CHANGES_REQUESTED" and cr and (ts(cr[-1]["submittedAt"]) or 0) > my_last_ts:
        out.update(status="changes", reason="cambios · " + cr[-1]["author"]["login"])
    elif foreign:
        authors = sorted({who(c) for c in foreign})
        more = "+" if last_mine < 0 and (n.get("commits") or {}).get("totalCount", 0) > len(cs) else ""
        out.update(status="foreign", reason="+%d%s %s" % (len(foreign), more, ",".join(authors)))
    elif "dismissed" in out["flags"]:
        out.update(status="dismissed", reason="re-aprobar · " + ",".join(dismissed))
    elif n.get("reviewDecision") == "APPROVED":
        out.update(status="approved", reason="aprobado · listo")
    else:
        req = requested(n)
        if req:
            out.update(status="waiting", reason="%s %s" % (",".join(req), ago(n.get("updatedAt"), now)))
        elif revs:
            out.update(status="waiting", reason="re-review %s" % ago(n.get("updatedAt"), now))
        else:
            out.update(status="waiting", reason="sin reviewer")
    return out


def derive_review(n, me, seen, cfg, now):
    k = key_of(n)
    out = {"key": k, "short": "%s#%d" % (short_repo(cfg, n["repository"]["name"]), n["number"]),
           "feature": feature_of(cfg, n), "node": n, "flags": [], "foreign": [], "kind": "open"}
    revs = [r for r in reviews_of(n) if r["author"]["login"] == me]
    mine = revs[-1] if revs else None
    author = (n.get("author") or {}).get("login") or "?"
    cs = commits_of(n)
    s = (seen.get(k) or {}).get("oid")
    if n.get("mergeable") == "CONFLICTING":
        out["flags"].append("conflict")
    if is_new(n, seen, now):
        out["flags"].append("new")
    if n.get("isDraft"):
        out.update(status="draft", reason="draft · " + author)
    elif me in requested(n):
        out.update(status="rv_pending", reason=("re-review · " if mine else "te pidieron · ") + author)
    elif mine:
        t = ts(mine["submittedAt"]) or 0
        newer = [c for c in cs if (ts(c["committedDate"]) or 0) > t and who(c) not in (me, "@me")]
        oids = [c["oid"] for c in newer]
        if s in oids:
            newer = newer[oids.index(s) + 1:]
        out["foreign"] = newer
        if newer:
            out.update(status="rv_new", reason="+%d desde tu review" % len(newer))
        elif mine["state"] == "APPROVED":
            out.update(status="rv_approved", reason="aprobaste · " + author)
        elif mine["state"] == "CHANGES_REQUESTED":
            out.update(status="rv_changes", reason="pediste cambios · " + author)
        else:
            out.update(status="rv_commented", reason="comentaste · " + author)
    else:
        out.update(status="rv_pending", reason="te pidieron · " + author)
    return out


def items(state, tab, cfg=None, seen=None, now=None):
    cfg = cfg or config()
    seen = load_json(SEEN_F, {}) if seen is None else seen
    now = now or time.time()
    me = state.get("me", "")
    hidden = set(cfg.get("hidden") or [])
    if tab == "review":
        out = [derive_review(n, me, seen, cfg, now) for n in state.get("review", [])]
    elif tab == "release":
        out = [derive_release(n, me, seen, cfg, now) for n in state.get("release", [])]
        now_ = now
        out = [i for i in out if i["kind"] == "open" or now_ - (ts(i["node"].get("mergedAt")) or 0) < REL_DAYS * 86400]
    else:
        out = [derive_mine(n, me, seen, cfg, now) for n in state.get("mine", [])]
    for it in out:
        it["hidden"] = it["key"] in hidden or it["short"] in hidden
    return out


def features(its, now):
    """Agrupa por feature y decide qué features siguen activas y cuáles están terminadas."""
    groups = {}
    for it in its:
        if it["hidden"]:
            continue
        groups.setdefault(it["feature"], []).append(it)
    active, done = [], []
    for name, lst in groups.items():
        open_ = [i for i in lst if i["kind"] == "open"]
        if open_:
            active.append((name, lst))
            continue
        ends = [ts(i["node"].get("mergedAt") or i["node"].get("closedAt")) or 0 for i in lst]
        has_live_branch = any(i["kind"] == "closed" for i in lst)
        if has_live_branch or now - max(ends or [0]) < KEEP_DONE_DAYS * 86400:
            done.append((name, lst))

    def prio(g):
        lst = g[1]
        act = sum(1 for i in lst if i["status"] in MINE_ACTION + REVIEW_ACTION or "conflict" in i["flags"])
        last = max(ts(i["node"].get("updatedAt")) or 0 for i in lst)
        return (0 if act else 1, -last)

    active.sort(key=prio)
    done.sort(key=lambda g: -max(ts(i["node"].get("updatedAt")) or 0 for i in g[1]))
    return active, done


# ───────────────────────── formato ─────────────────────────

def ago(iso, now):
    t = ts(iso)
    if not t:
        return ""
    s = max(0, now - t)
    if s < 3600:
        return "%d min" % (s // 60)
    if s < 86400:
        return "%d h" % (s // 3600)
    return "%d d" % (s // 86400)


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def when(t, now):
    if not t:
        return ""
    d = datetime.fromtimestamp(t)
    today = datetime.fromtimestamp(now).date()
    if d.date() == today:
        return "hoy " + d.strftime("%H:%M")
    if (today - d.date()).days == 1:
        return "ayer " + d.strftime("%H:%M")
    return "%d %s" % (d.day, MESES[d.month - 1])


def counts(its):
    c = {}
    for it in its:
        if it["hidden"] or it["kind"] != "open":
            continue
        c[it["status"]] = c.get(it["status"], 0) + 1
        for f in it["flags"]:
            if f in ("conflict", "new") or (f == "dismissed" and it["status"] != "dismissed"):
                c[f] = c.get(f, 0) + 1
    return c


def set_sum(state):
    """Escribe @prt_sum: la tercera línea de estado."""
    cfg = config()
    parts = []
    if state.get("me"):
        now = time.time()
        seen = load_json(SEEN_F, {})
        c = counts(items(state, "mine", cfg, seen, now))
        mine = []
        for k in ("foreign", "dismissed", "changes", "conflict", "approved", "waiting", "draft", "new"):
            if c.get(k):
                bold = ",bold" if k in MINE_ACTION or k == "conflict" else ""
                mine.append("#[fg=%s%s]%s%d#[nobold]" % (COL[k], bold, GLYPH[k], c[k]))
        parts.append("#[fg=%s,bold]PRs#[nobold] %s" % (COL["white"], " ".join(mine) or "#[fg=%s]al día" % COL["dim"]))
        r = counts(items(state, "review", cfg, seen, now))
        rv = []
        for k in ("rv_pending", "rv_new"):
            if r.get(k):
                rv.append("#[fg=%s,bold]%s%d#[nobold]" % (COL[GCOL[k]], GLYPH[k], r[k]))
        if rv:
            parts.append("#[fg=%s]review#[default] %s" % (COL["dim"], " ".join(rv)))
        rl = counts(items(state, "release", cfg, seen, now))
        rel = []
        for k in ("changes", "approved", "conflict", "waiting", "rel_other", "draft"):
            if rl.get(k):
                bold = ",bold" if k in ("changes", "approved", "conflict") else ""
                rel.append("#[fg=%s%s]%s%d#[nobold]" % (COL[GCOL.get(k, k)], bold, GLYPH[k], rl[k]))
        if rel:
            parts.append("#[fg=%s]release#[default] %s" % (COL["dim"], " ".join(rel)))
    for note in cfg.get("notes") or []:
        parts.append("#[fg=%s]⚑ %s" % (COL["foreign"], note.replace("#", "＃")))
    if os.path.exists(ERROR_F):
        with open(ERROR_F) as f:
            parts.append("#[fg=%s]sin actualizar: %s" % (COL["changes"], f.read().strip().replace("#", "＃")[:60]))
    sep = "#[fg=%s] │ " % COL["faint"]
    val = " " + sep.join(parts) if parts else ""
    subprocess.run([TMUX, "set", "-g", "@prt_sum", val], capture_output=True)


def mark_seen(keys):
    state = load_json(STATE_F, {})
    seen = load_json(SEEN_F, {})
    by = {key_of(n): n for n in state.get("mine", []) + state.get("review", [])}
    now = time.time()
    for k in keys:
        n = by.get(k)
        if n:
            seen[k] = {"oid": head_oid(n), "ts": now}
    save_json(SEEN_F, seen)
    set_sum(state)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "fetch"
    if cmd == "fetch":
        return fetch()
    if cmd == "sum":
        set_sum(load_json(STATE_F, {}))
        return 0
    if cmd == "seen":
        mark_seen(argv[2:])
        return 0
    if cmd == "dump":
        tab = argv[2] if len(argv) > 2 else "mine"
        st = load_json(STATE_F, {})
        active, done = features(items(st, tab), time.time())
        for title, groups in (("ACTIVAS", active), ("TERMINADAS", done)):
            print("== %s" % title)
            for name, lst in groups:
                print("  %s" % name)
                for it in sorted(lst, key=lambda i: RANK.get(i["status"], 9)):
                    print("    %s %-24s %-28s %s" % (GLYPH.get(it["status"], "?"), it["short"], it["reason"],
                                                 " ".join(GLYPH[f] for f in it["flags"])))
        hid = [i["short"] for i in items(st, tab) if i["hidden"]]
        if hid:
            print("== OCULTOS: " + ", ".join(hid))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
