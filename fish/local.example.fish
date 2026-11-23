# Copia este archivo a ~/.config/fish/local.fish y ajústalo.
# local.fish está en .gitignore: aquí van aliases de trabajo, rutas de
# proyectos y variables propias de la máquina. NUNCA tokens en claro:
# usa el Keychain de macOS o archivos .env con permisos 600.

# Prefijos de repos que el radar de tmux recorta en los títulos de las pestañas
# set -gx RADAR_STRIP_PREFIXES "acme- myorg-"

# Atajos a carpetas de proyectos
# alias work="cd ~/dev/work"
# alias notes="cd ~/notes"

# wm: una sesión de tmux por repo + worktrees de workmux (fish/functions/wm.fish)
# set -g WM_ROOT ~/dev/work/acme                # carpeta con tus repos (default ~/dev/work)
# set -g WM_HUB acme                            # sesión para preguntas sin rama (default hub)
# set -g WM_SERVICES servicios                  # sesión para servidores locales
# set -g WM_ALIASES api=acme-api web=acme-web   # alias=carpeta
# set -g WM_SESSIONS acme-web=web               # carpeta=nombre de sesión
