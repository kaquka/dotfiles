#!/bin/sh
# Barra lateral de claude-radar (pestañas Claude · Mis PRs · Reviewer).
#   radar-sidebar.sh toggle [window_id]   prende/apaga (prefix b)
#   radar-sidebar.sh follow [window_id]   la mueve a la ventana actual (hooks)
#   radar-sidebar.sh prs [window_id]      la abre en "Mis PRs" y le da el foco (prefix P)
#   radar-sidebar.sh focus                le da el foco (Alt-p); Esc lo regresa
# El ancho es un porcentaje de la ventana. Si la redimensionas, se recuerda en @radar_sidebar_pct.
T=/opt/homebrew/bin/tmux
DIR="$HOME/.config/tmux/scripts/radar"
REQ="$HOME/.local/state/prt/tab_request"
DEFAULT_PCT=30

on() { [ "$($T show -gv @radar_sidebar_on 2>/dev/null)" = "1" ]; }
sidebar() { $T list-panes -a -F '#{pane_id} #{window_id} #{window_panes} #{@radar_sidebar}' | awk '$4==1{print $1, $2, $3; exit}'; }
current() { $T display -p '#{window_id}'; }
pct() { p=$($T show -gv @radar_sidebar_pct 2>/dev/null); echo "${p:-$DEFAULT_PCT}"; }

# Guarda el ancho actual de la barra como porcentaje de su ventana (entre 15 y 60).
remember() {
  set -- $($T display -p -t "$1" '#{pane_width} #{window_width}' 2>/dev/null)
  [ -n "$2" ] && [ "$2" -gt 0 ] || return 0
  p=$(( ($1 * 100 + $2 / 2) / $2 ))
  [ "$p" -lt 15 ] && p=15
  [ "$p" -gt 60 ] && p=60
  $T set -g @radar_sidebar_pct "$p"
}

follow() {
  on || return 0
  target="${1:-$(current)}"
  sb=$(sidebar)
  if [ -z "$sb" ]; then
    id=$($T split-window -d -fh -l "$(pct)%" -t "$target" -P -F '#{pane_id}' "/usr/bin/python3 $DIR/sidebar.py")
    [ -n "$id" ] && $T set -p -t "$id" @radar_sidebar 1
    return 0
  fi
  set -- $sb   # $1 pane  $2 ventana  $3 panes en esa ventana
  if [ "$2" != "$target" ]; then
    remember "$1"
    $T join-pane -d -fh -l "$(pct)%" -s "$1" -t "$target" 2>/dev/null
  elif [ "$3" = "1" ]; then
    # quedó sola en la ventana (cerraste los demás panes): se cierra y reaparece donde estés
    $T kill-pane -t "$1"
    sleep 0.2
    follow "$(current)"
  fi
}

focus() {
  sb=$(sidebar)
  [ -n "$sb" ] && $T select-pane -t "${sb%% *}"
}

case "$1" in
  toggle)
    if on; then
      $T set -g @radar_sidebar_on 0
      $T list-panes -a -F '#{pane_id} #{@radar_sidebar}' | awk '$2==1{print $1}' |
        while read -r id; do remember "$id"; $T kill-pane -t "$id"; done
    else
      $T set -g @radar_sidebar_on 1
      follow "$2"
    fi ;;
  follow) follow "$2" ;;
  prs)
    mkdir -p "$(dirname "$REQ")" && echo mine > "$REQ"
    if ! on; then $T set -g @radar_sidebar_on 1; fi
    follow "$2"
    sleep 0.1
    focus ;;
  focus) focus ;;
esac
"$DIR/radar-scan" >/dev/null 2>&1 &
exit 0
