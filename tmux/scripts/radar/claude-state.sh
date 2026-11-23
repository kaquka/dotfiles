#!/bin/sh
# Hook de Claude Code -> opciones del pane de tmux para claude-radar.
# Uso (desde ~/.claude/settings.json): claude-state.sh prompt|pretool|posttool|notify|stop|end
# Nunca falla ni imprime: no debe interferir con Claude.
input=$(cat)
[ -n "$TMUX_PANE" ] || exit 0
T=/opt/homebrew/bin/tmux
JQ=/usr/bin/jq
P="$TMUX_PANE"
now=$(date +%s)

case "$1" in
  prompt)
    $T set -p -t "$P" @claude_state working \; set -p -t "$P" @claude_doing "pensando…" \
       \; set -pu -t "$P" @claude_msg \; set -p -t "$P" @claude_ts "$now" 2>/dev/null ;;
  pretool)
    doing=$(printf '%s' "$input" | $JQ -r '
      (.tool_name // "") as $t | (.tool_input // {}) as $i |
      (if ($t|startswith("mcp__")) then ($t|split("__")|.[1:]|join("·")) else $t end) as $n |
      if $t == "Bash" then "Bash: " + (($i.command // "")|split("\n")[0]|.[0:70])
      elif $i.file_path then $n + " " + ($i.file_path|split("/")|last)
      elif $i.pattern then $n + " " + ($i.pattern|tostring|.[0:40])
      elif $i.url then $n + " " + ($i.url|.[0:50])
      elif $i.description then $n + ": " + ($i.description|.[0:50])
      elif $i.query then $n + ": " + ($i.query|tostring|split("\n")[0]|.[0:50])
      else $n end' 2>/dev/null)
    $T set -p -t "$P" @claude_state working \; set -p -t "$P" @claude_doing "$doing" \
       \; set -pu -t "$P" @claude_msg \; set -p -t "$P" @claude_ts "$now" 2>/dev/null ;;
  posttool)
    $T set -p -t "$P" @claude_state working \; set -pu -t "$P" @claude_msg \
       \; set -p -t "$P" @claude_ts "$now" 2>/dev/null ;;
  notify)
    ntype=$(printf '%s' "$input" | $JQ -r '.notification_type // ""' 2>/dev/null)
    msg=$(printf '%s' "$input" | $JQ -r '.message // ""' 2>/dev/null)
    case "$ntype$msg" in
      idle_prompt*|*"waiting for your input"*|auth_success*) exit 0 ;;
    esac
    $T set -p -t "$P" @claude_state waiting \; set -p -t "$P" @claude_msg "$msg" \
       \; set -p -t "$P" @claude_ts "$now" 2>/dev/null ;;
  stop)
    $T set -p -t "$P" @claude_state idle \; set -pu -t "$P" @claude_doing \
       \; set -pu -t "$P" @claude_msg \; set -p -t "$P" @claude_ts "$now" 2>/dev/null ;;
  end)
    $T set -pu -t "$P" @claude_state \; set -pu -t "$P" @claude_doing \
       \; set -pu -t "$P" @claude_msg \; set -pu -t "$P" @claude_ts 2>/dev/null ;;
esac

# refresco inmediato de la barra (con antirrebote de 1s)
( /usr/bin/python3 "$HOME/.config/tmux/scripts/radar/radar.py" scan --soft >/dev/null 2>&1 & )
exit 0
