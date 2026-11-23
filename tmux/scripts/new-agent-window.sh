#!/bin/sh
# Abre una ventana nueva (junto a la actual) en el path dado y arranca el arnés que le toca.
# Al salir del arnés te quedas en la shell de esa carpeta.
path="${1:-$HOME}"
cmd="$("$HOME/.config/harness/harness-for" "$path")"
win=$(tmux new-window -a -c "$path" -P -F '#{window_id}')
tmux send-keys -t "$win" "$cmd" Enter
