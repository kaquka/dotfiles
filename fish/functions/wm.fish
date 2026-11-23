# wm — una sesión de tmux por repo + worktrees de workmux
#
#   wm                         → sesiones "hub" (preguntas sin rama) y "servicios" (localhost); te lleva al hub
#   wm <repo>                  → sesión del repo (ventana "main" en el checkout principal)
#   wm <repo> <tarea> [flags]  → worktree + ventana con agente en la sesión del repo
#                                flags van directo a `workmux add` (ej. -a pi, -p "...", --base main)
#   wm rm <repo> <tarea>       → borra worktree, ventana y rama local (cuando ya se mergeó el PR)
#
# <repo> es el nombre de la carpeta dentro de $WM_ROOT o un alias de $WM_ALIASES.
# Se configura en fish/local.fish (no versionado), por ejemplo:
#
#   set -g WM_ROOT ~/dev/work/acme              # carpeta con tus repos (default ~/dev/work)
#   set -g WM_HUB acme                          # sesión para preguntas (default hub)
#   set -g WM_SERVICES servicios                # sesión para servidores locales (default servicios)
#   set -g WM_ALIASES api=acme-api web=acme-web # alias=carpeta
#   set -g WM_SESSIONS acme-web=web             # carpeta=nombre de sesión (default: la carpeta)
#
# Si no pasas -a/--agent, el agente sale de ~/.config/harness/map.conf (harness-for).

function __wm_root
    set -q WM_ROOT; and echo $WM_ROOT; or echo $HOME/dev/work
end

# Busca key en una lista "key=valor"; imprime el valor
function __wm_lookup --argument-names key
    for pair in $argv[2..-1]
        set -l kv (string split -m1 = -- $pair)
        if test "$kv[1]" = "$key"
            echo $kv[2]
            return 0
        end
    end
    return 1
end

function __wm_resolve --argument-names name
    set -l real (__wm_lookup $name $WM_ALIASES); and set name $real
    set -l dir (__wm_root)/$name
    if not test -d $dir/.git; and not test -f $dir/.git
        echo "wm: '$name' no es un repo en "(__wm_root) >&2
        return 1
    end
    echo $name
end

# Nombre de la sesión de tmux para cada repo (respeta las sesiones que ya usas)
function __wm_session --argument-names repo
    __wm_lookup $repo $WM_SESSIONS; or string replace -a . _ $repo
end

function __wm_ensure_session --argument-names sess dir
    tmux has-session -t "=$sess" 2>/dev/null
    or tmux new-session -d -s $sess -c $dir -n main
end

function __wm_go --argument-names sess
    if set -q TMUX
        tmux switch-client -t "=$sess"
    else
        tmux attach -t "=$sess"
    end
end

function wm
    set -l root (__wm_root)
    set -l hub hub
    set -q WM_HUB; and set hub $WM_HUB
    set -l services servicios
    set -q WM_SERVICES; and set services $WM_SERVICES

    # wm → hub
    if test (count $argv) -eq 0
        __wm_ensure_session $hub $root
        __wm_ensure_session $services $root
        __wm_go $hub
        return
    end

    # wm rm <repo> <tarea>
    if test "$argv[1]" = rm
        if test (count $argv) -lt 3
            echo "uso: wm rm <repo> <tarea>" >&2
            return 1
        end
        set -l repo (__wm_resolve $argv[2]); or return 1
        pushd $root/$repo
        workmux remove $argv[3..-1]
        popd
        return
    end

    set -l repo (__wm_resolve $argv[1]); or return 1
    set -l dir $root/$repo
    set -l sess (__wm_session $repo)
    __wm_ensure_session $sess $dir

    # wm <repo>
    if test (count $argv) -eq 1
        __wm_go $sess
        return
    end

    # wm <repo> <tarea> [flags]  — si no pasas -a/--agent, usa el arnés de ~/.config/harness/map.conf
    set -l agent_flag
    if not contains -- -a $argv; and not string match -qr -- '^--agent' $argv
        set agent_flag -a ($HOME/.config/harness/harness-for $dir)
    end
    pushd $dir
    workmux add $argv[2..-1] $agent_flag --parent-session $sess --open-if-exists
    set -l rc $status
    popd
    test $rc -eq 0; or return $rc
    set -q TMUX; or tmux attach -t "=$sess"
end
