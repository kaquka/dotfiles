# dotfiles

Mi entorno de trabajo en macOS: **Ghostty → fish → tmux → Claude Code**, más un par de
paneles hechos a mano para seguir sesiones de Claude, servidores locales y PRs sin salir
de la terminal.

Sirve para dos cosas:

1. **Restaurar todo en una Mac nueva** con un solo comando.
2. **Guía** para quien quiera adoptar una parte de esta forma de trabajo. Cada pieza es
   independiente: puedes tomar solo el radar de tmux, solo las skills o solo el tema de Ghostty.

> Todo lo propio de la máquina (identidad de git, aliases de trabajo, proyectos de sesh,
> repos que sigue el panel de PRs) vive en archivos **locales no versionados**. El repo
> trae una plantilla `.example` de cada uno.

---

## Instalación rápida (Mac nueva)

```bash
git clone https://github.com/kaquka/dotfiles ~/dev/personal/dotfiles
cd ~/dev/personal/dotfiles
make bootstrap-macos
```

`bootstrap-macos` hace, en orden:

1. Instala Homebrew (si falta) y todo el `Brewfile`.
2. Crea las carpetas base `~/dev/work`, `~/dev/personal`, `~/bin` (+ las de `scripts/dev-dirs.local`).
3. Enlaza (`ln -s`) cada carpeta a `~/.config/<herramienta>`, más `~/.tmux.conf` y `~/.gitconfig`.
4. Copia las plantillas `.example` a sus archivos locales **solo si no existen**.
5. Instala los plugins de tmux (TPM) y la config de Claude Code.
6. Pone fish como shell por defecto.

Después edita tus datos en los archivos locales (tabla abajo) y corre `gh auth login`.

Targets sueltos: `make brew-bundle`, `make dev-dirs`, `make links`, `make tmux-plugins`,
`make claude`, `make fish-shell`, `make doctor`.

### Archivos locales (no versionados)

| Archivo local | Plantilla | Para qué |
|---|---|---|
| `git/personal.gitconfig` | `git/personal.gitconfig.example` | Nombre y correo por defecto |
| `git/work.gitconfig` | `git/work.gitconfig.example` | Identidad para repos bajo `~/dev/work/` |
| `fish/local.fish` | `fish/local.example.fish` | Aliases de trabajo, rutas, variables de la máquina |
| `gh/config.yml` | `gh/config.example.yml` | Aliases de `gh` (`gh me` / `gh work` para cambiar de cuenta) |
| `sesh/sesh.toml` | `sesh/sesh.example.toml` | Tus proyectos como sesiones de tmux |
| `~/.config/prt/config.json` | `prt/config.example.json` | Repos y PRs que sigue el panel de PRs |
| `scripts/dev-dirs.local` | — | Carpetas extra a crear (una por línea) |
| `~/.config/workmux/config.yaml` | `workmux/config.example.yaml` | Config de workmux (dónde caen los worktrees, panel) |
| `harness/map.conf` | `harness/map.example.conf` | Qué agente (claude, pi…) abre cada carpeta |

**Credenciales:** ninguna vive en este repo. `gh` usa el Keychain; las API keys van como
variables de entorno en `fish/local.fish` leyendo de archivos `.env` con permisos `600`
o del Keychain (`security find-generic-password`).

---

## Las piezas

### Ghostty — `ghostty/`
Tema monocromático en escala de grises con transparencia y blur, fuente Nerd Font y un
shader de cursor (`shaders/cursor.glsl`). Al abrir Ghostty, fish entra solo a tmux
(`fish/conf.d/20_auto_tmux_ghostty.fish`).

### fish — `fish/`
- `config.fish`: mise, starship, zoxide, OrbStack, Android SDK y la carga de `local.fish`.
- `conf.d/`: tema Kanagawa para la UI de fish, autocompletado con carapace, títulos de
  ventana de tmux según el comando que corre, limpieza de direnv.
- `functions/`: `awslogin` / `awslogout` / `awsprofiles` / `awswho` para cambiar de perfil
  AWS SSO sin pensar; `fish_mode_prompt` para el modo vi.

Prompt con **starship** (`starship.toml`). Versiones de runtimes con **mise** (`mise/config.toml`).

### tmux — `tmux/`
Prefijo `Ctrl+Space`. Navegación estilo vim (`h j k l`, también con `Alt` sin prefijo),
splits con `|` y `-` en la carpeta actual. Plugins: sensible, yank, resurrect, continuum,
fzf-url, thumbs.

**Sesiones por proyecto con [sesh](https://github.com/joshmedeski/sesh):**

| Tecla | Acción |
|---|---|
| `prefix s` | Popup con fzf para saltar a cualquier sesión/proyecto |
| `prefix S` | Abrir sesión por nombre o ruta |
| `prefix O` | Volver a la sesión anterior |
| `prefix 9` | Sesión en la raíz del repo actual |

Cada proyecto de `sesh.toml` abre ventanas `ai` (Claude Code) y `run` (shell libre).

#### Radar de sesiones de Claude — `tmux/radar.conf`, `tmux/scripts/radar/`
Para cuando tienes varias sesiones de Claude Code y servidores locales en ventanas distintas:

- **Barra de estado abajo, una sola línea**: PRs a la izquierda (ver prt), sesión ·
  ventana · hora a la derecha. El nombre de la sesión se resalta en ámbar con el prefijo.
- **Panel de [workmux](https://workmux.dev) a la izquierda** como vista principal (se
  enciende al cargar tmux): una tarjeta por agente agrupada por repo, con su estado y
  colores (● trabajando ámbar, ◆ esperando rojo, ◉ terminó verde) y el conteo por estado
  en el encabezado de cada repo.
- **Servidores locales en el mismo panel**: el escáner (`radar.py`) detecta panes que
  escuchan un puerto, les pone el título `:puerto · tarea` y los registra en workmux como
  tarjeta (▲ azul arriba, ✗ rojo caído). También registra sesiones de Claude abiertas
  antes de los hooks. Usa el formato interno de `~/.local/state/workmux/agents/` (no es
  API pública de workmux); si una versión lo cambia, solo se pierden esas tarjetas.
- **Barra de título por pane** en ventanas con 2+ panes, y estado "terminó sin que lo
  vieras" hasta que enfocas el pane.
- **Mission control** (`prefix a`): popup en Textual con todo junto (`uv run --script`,
  sin instalar dependencias a mano). `prefix b`: barra lateral propia del radar.
- Los estados llegan por **hooks de Claude Code** (`claude-state.sh` y `workmux
  set-window-status`, configurados en `claude/settings.example.json`) y por lo que se ve
  en pantalla.
- Opcional: `RADAR_STRIP_PREFIXES="acme- myorg-"` recorta prefijos de repo en los títulos.

**Cerrar sin dejar procesos vivos** (`tmux/scripts/close-agent.py`):

| Tecla | Cierra | Confirma |
|---|---|---|
| `prefix x` | el pane | solo si corre un Claude |
| `prefix X` | la ventana | sí |
| `prefix K` | la sesión | sí |

Manda SIGTERM a Claude y lo espera (guarda la conversación y apaga sus MCP), cierra en
tmux y luego mata lo que quede del árbol de procesos (tareas en segundo plano, MCP
colgados). Si en la ventana solo queda el panel de workmux, la cierra también.

#### Agentes en worktrees — workmux, `wm` y harness
- **`wm`** (`fish/functions/wm.fish`): una sesión de tmux por repo. `wm <repo> <tarea>`
  crea worktree + ventana con agente vía `workmux add`; `wm rm <repo> <tarea>` limpia.
  `wm` solo abre las sesiones hub y servicios. Raíz, alias y nombres de sesión se definen
  en `fish/local.fish` (`WM_ROOT`, `WM_ALIASES`, `WM_SESSIONS`, ver la plantilla).
- **harness** (`harness/`): `harness-for <path>` dice qué agente abre cada carpeta según
  `harness/map.conf` (prefijo más largo gana). `prefix n` abre una ventana nueva en la
  carpeta actual con ese agente; `wm` lo usa si no pasas `-a`.
- **workmux** (`workmux/config.example.yaml`): paleta monocromática a juego con Ghostty,
  panel agrupado por repo, íconos de estado del radar. `prefix W` dashboard, `prefix T`
  muestra/oculta el panel.

#### Panel de PRs (prt) — `tmux/scripts/radar/prt*.py`
Radar de pull requests en la barra lateral (`prefix P`, foco con `Alt+p`) y en la barra de
estado: tus PRs y los que te piden revisar, con CI, reviews, commits nuevos desde la última
vez que lo viste, y seguimiento de lo que se mergeó para releases. Una sola llamada GraphQL
con tu sesión de `gh`. Se configura en `~/.config/prt/config.json` (alias de repos, PRs
fijados a un tema, ocultos, notas).

### Claude Code — `claude/`
- `settings.example.json`: hooks del radar y de workmux, statusline, tema, modo de permisos.
- `statusline.sh`: modelo, rama y barras de uso (contexto, ventana de 5 h y de 7 días)
  coloreadas por nivel.
- `keybindings.json`: `Shift+Enter` = salto de línea.
- `CLAUDE.md`: instrucciones globales (sin rastros de IA en commits/PRs propios).
- `skills/` — skills reutilizables:

| Skill | Cuándo |
|---|---|
| `pr-review-triage` | Recibiste comentarios en un PR: verifica cada uno contra el código, separa triviales y prioriza |
| `backend-review` | Escribir o revisar cambios de backend/APIs |
| `flutter-review` | Checklist de lo que las reviews de Flutter detectan una y otra vez |
| `git-workflow` | Ramas, Conventional Commits, anatomía de un PR, reglas de review |
| `go-lint-clean` | No romper golangci-lint (gofmt/goimports) antes de push |
| `analytics-contract` | Instrumentar eventos de producto en PostHog sin desordenar la taxonomía |
| `mise-setup` | Crear o reformar archivos de entorno con mise y perfiles |

`make claude` enlaza las skills y `statusline.sh` a `~/.claude`, y copia `settings.json` y
`CLAUDE.md` solo si no existen (si ya tienes los tuyos, mezcla a mano).

Skills de terceros que también uso (se instalan desde su fuente, no se copian aquí):
[graphify](https://github.com/safishamsi/graphify) (`uv tool install graphifyy`) y las skills de búsqueda de Brave
(requieren `BRAVE_SEARCH_API_KEY` en el entorno).

### Neovim — `nvim/`
LazyVim con ajustes de UI, dashboard, Flutter y Swift.

### git — `git/`
`config` incluye `common.gitconfig` y cambia la identidad según la carpeta
(`~/dev/work/` → `work.gitconfig`, `~/dev/personal/` → `personal.gitconfig`).
`ignore` es el gitignore global (`.env`, archivos `mise.*` locales, etc.).

---

## Adoptar solo una parte

- **Solo Ghostty:** copia `ghostty/` a `~/.config/ghostty/`.
- **Solo tmux + radar:** copia `tmux/` a `~/.config/tmux/`, enlaza `~/.tmux.conf`, corre
  `make tmux-plugins` y añade los hooks de `claude/settings.example.json` a tu `settings.json`.
- **Solo skills:** copia la carpeta de la skill a `~/.claude/skills/<nombre>/`.
