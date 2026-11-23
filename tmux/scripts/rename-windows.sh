#!/bin/sh

helper="$HOME/.config/tmux/scripts/window-label.sh"

tmux list-windows -a -F '#{?#{@workmux_token},wm,-}	#{session_name}:#{window_index}	#{pane_title}	#{pane_current_path}	#{window_name}	#{pane_current_command}' |
while IFS="$(printf '\t')" read -r wm_flag target title path current_name current_cmd; do
  [ "$wm_flag" = wm ] && continue  # ventanas de workmux: su nombre lo controla workmux
  label="$("$helper" "$title" "$path" "$current_name" "$current_cmd" "bulk")"
  [ -n "$label" ] || continue
  [ "$label" = "$current_name" ] && continue
  tmux rename-window -t "$target" "$label" >/dev/null 2>&1
done
