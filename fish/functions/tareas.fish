function tareas --description 'Administrador de tareas en la terminal: quién calienta la laptop (tmux/arneses/apps/docker)'
    /opt/homebrew/bin/uv run --quiet --script ~/.config/tmux/scripts/radar/taskmon.py $argv
end
