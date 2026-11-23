#!/usr/bin/env bash
# Claude Code — custom status line
INPUT=$(cat)

# Model
DISPLAY=$(printf '%s' "$INPUT" | jq -r '.model.display_name // ""')
MODEL_ID=$(printf '%s' "$INPUT" | jq -r '.model.id // ""')
VERSION=$(echo "$MODEL_ID" | grep -oE '[0-9]+-[0-9]+$' | tr '-' '.')
# Anthropic incluye " (1M context)" / " (200k context)" en display_name — lo quito para no duplicar
DISPLAY=$(printf '%s' "$DISPLAY" | sed -E 's/[[:space:]]*\((1M|[0-9]+k) context\)$//')
if [ -n "$DISPLAY" ] && [ -n "$VERSION" ]; then
    MODEL="${DISPLAY} ${VERSION}"
elif [ -n "$DISPLAY" ]; then
    MODEL="$DISPLAY"
else
    MODEL="Claude"
fi

# Context window size: 200000 → 200k, 1000000 → 1M
CTX_SIZE=$(printf '%s' "$INPUT" | jq -r '.context_window.context_window_size // 0')
CTX_SIZE_STR=$(echo "$CTX_SIZE" | awk '{
    if ($1 >= 1000000) printf "%.0fM", $1/1000000
    else if ($1 >= 1000) printf "%.0fk", $1/1000
    else printf "%d", $1
}')

# Usage & cost
CTX_PCT=$(printf '%s' "$INPUT" | jq -r '.context_window.used_percentage // 0' | awk '{printf "%d", $1+0}')
COST=$(printf '%s' "$INPUT" | jq -r '.cost.total_cost_usd // 0' | awk '{printf "$%.2f", $1+0}')
LINES_ADD=$(printf '%s' "$INPUT" | jq -r '.cost.total_lines_added // 0')
LINES_DEL=$(printf '%s' "$INPUT" | jq -r '.cost.total_lines_removed // 0')

# Workspace
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // "."')
REPO_NAME=$(printf '%s' "$INPUT" | jq -r '.workspace.repo.name // ""')
PR_NUM=$(printf '%s' "$INPUT" | jq -r 'if .pr.number then "#\(.pr.number)" else "" end')

# Git branch + dirty indicator
BRANCH=""
DIRTY=""
if git -C "$CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    BRANCH=$(git -C "$CWD" branch --show-current 2>/dev/null || true)
    [ -n "$(git -C "$CWD" status --porcelain 2>/dev/null)" ] && DIRTY="*"
    [ -z "$REPO_NAME" ] && REPO_NAME=$(basename "$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)")
fi

# ANSI
R='\033[0m'
DIM='\033[2m'
GREEN='\033[32m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'

# Color por nivel (truecolor): verde <50, amarillo <75, naranja <90, rojo >=90
lvl_rgb() {
    v=$1
    if   [ "$v" -ge 90 ]; then echo "255;100;100"
    elif [ "$v" -ge 75 ]; then echo "232;150;60"
    elif [ "$v" -ge 50 ]; then echo "230;200;80"
    else                       echo "98;196;138"
    fi
}

# Barra con precisión de 1/8 de celda: bar <pct> <ancho>
bar() {
    pct=$1; w=$2; rgb=$(lvl_rgb "$pct")
    awk -v p="$pct" -v w="$w" -v rgb="$rgb" 'BEGIN{
        split("▏ ▎ ▍ ▌ ▋ ▊ ▉", part, " ");
        if (p > 100) p = 100; if (p < 0) p = 0;
        e = int(p * w * 8 / 100 + 0.5); full = int(e / 8); rem = e % 8;
        out = "\033[38;2;" rgb "m\033[48;2;48;48;48m";
        for (i = 0; i < full; i++) out = out "█";
        n = full;
        if (rem > 0 && n < w) { out = out part[rem]; n++ }
        for (; n < w; n++) out = out " ";
        printf "%s\033[0m", out
    }'
}

# pct coloreado: pctc <pct>
pctc() { printf '\033[38;2;%sm%s%%\033[0m' "$(lvl_rgb "$1")" "$1"; }

SEP="${DIM} | ${R}"

# Backend activo (según ANTHROPIC_BASE_URL heredado del entorno)
case "$ANTHROPIC_BASE_URL" in
  *:3456*)            BACKEND="⚡ KIRO";      BC='\033[38;5;214m' ;;
  *:3457*)            BACKEND="🌊 OPENCODE";  BC='\033[38;5;45m'  ;;
  *:3458*)            BACKEND="🐙 COPILOT";   BC='\033[38;5;170m' ;;
  *:3459*)            BACKEND="🧠 MINIMAX";   BC='\033[38;5;201m'; MODEL="MiniMax-M2" ;;
  *anthropic.com*|"") BACKEND="☁️ ANTHROPIC"; BC='\033[38;5;39m'  ;;
  *)                  BACKEND="? backend";    BC='\033[2m'        ;;
esac

# Build line
LINE="${BC}${BACKEND}${R}${SEP}${GREEN}${MODEL} (${CTX_SIZE_STR} context)${R}"

SHORT_DIR=$(printf '%s' "$CWD" | sed "s|${HOME}|~|")
LINE="${LINE}${SEP}${DIM}${SHORT_DIR}${R}"

if [ -n "$BRANCH" ]; then
    BRANCH_PART="\\ ${BRANCH}${DIRTY}"
    [ -n "$PR_NUM" ] && BRANCH_PART="${BRANCH_PART} ${YELLOW}${PR_NUM}${R}"
    LINE="${LINE}${SEP}${BRANCH_PART}"
fi

LINE="${LINE}${SEP}${DIM}ctx${R} $(bar "$CTX_PCT" 10) $(pctc "$CTX_PCT")"
LINE="${LINE}${SEP}${DIM}${COST}${R}"

if [ "$LINES_ADD" -gt 0 ] || [ "$LINES_DEL" -gt 0 ]; then
    LINE="${LINE}${SEP}${GREEN}+${LINES_ADD}${R} ${RED}-${LINES_DEL}${R}"
fi

# Rate limits (solo Claude.ai Pro/Max)
rl_5h=$(printf '%s' "$INPUT" | jq -r '.rate_limits.five_hour.used_percentage // empty')
rl_7d=$(printf '%s' "$INPUT" | jq -r '.rate_limits.seven_day.used_percentage // empty')

if [ -n "$rl_5h" ] || [ -n "$rl_7d" ]; then
    RL_PART=""
    if [ -n "$rl_5h" ]; then
        pct=$(echo "$rl_5h" | awk '{printf "%d", $1+0}')
        RL_PART="${DIM}5h${R} $(bar "$pct" 6) $(pctc "$pct")"
    fi
    if [ -n "$rl_7d" ]; then
        pct=$(echo "$rl_7d" | awk '{printf "%d", $1+0}')
        [ -n "$RL_PART" ] && RL_PART="${RL_PART}  "
        RL_PART="${RL_PART}${DIM}7d${R} $(bar "$pct" 6) $(pctc "$pct")"
    fi
    LINE="${LINE}${SEP}${RL_PART}"
fi

printf '%b\n' "$LINE"
