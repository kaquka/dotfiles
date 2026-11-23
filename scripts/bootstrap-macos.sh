#!/usr/bin/env bash
set -euo pipefail

# Bootstrap completo para una Mac nueva:
#   1. Instala Homebrew si no está
#   2. Instala todo lo del Brewfile (incluye ghostty, fish, neovim, etc.)
#   3. Crea las carpetas de proyectos referenciadas por los configs
#   4. Enlaza los dotfiles a ~/.config
#   5. Copia las plantillas .example a sus archivos locales (si no existen)
#   6. Instala plugins de tmux y la config de Claude Code
#   7. Pone fish como shell por defecto

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf "\n\033[1;34m==>\033[0m %s\n" "$*"
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi

  log "Homebrew no está instalado. Instalando..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
}

load_brew_env() {
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

seed_local() {
  local source="$1" target="$2"
  if [ ! -e "${target}" ]; then
    mkdir -p "$(dirname "${target}")"
    cp "${source}" "${target}"
    echo "  created ${target} (edítalo con tus datos)"
  fi
}

seed_local_files() {
  log "Creando archivos locales desde plantillas..."
  seed_local "${ROOT}/fish/local.example.fish" "${ROOT}/fish/local.fish"
  seed_local "${ROOT}/git/personal.gitconfig.example" "${ROOT}/git/personal.gitconfig"
  seed_local "${ROOT}/git/work.gitconfig.example" "${ROOT}/git/work.gitconfig"
  seed_local "${ROOT}/gh/config.example.yml" "${ROOT}/gh/config.yml"
  seed_local "${ROOT}/sesh/sesh.example.toml" "${ROOT}/sesh/sesh.toml"
  seed_local "${ROOT}/prt/config.example.json" "${HOME}/.config/prt/config.json"
  seed_local "${ROOT}/harness/map.example.conf" "${ROOT}/harness/map.conf"
  seed_local "${ROOT}/workmux/config.example.yaml" "${HOME}/.config/workmux/config.yaml"
}

run_script() {
  local script="$1"
  log "Corriendo ${script}..."
  "${ROOT}/scripts/${script}"
}

main() {
  log "Bootstrap dotfiles para macOS"

  ensure_homebrew
  load_brew_env

  log "Actualizando Homebrew..."
  brew update

  log "Instalando paquetes del Brewfile..."
  brew bundle --file "${ROOT}/Brewfile"

  run_script "install-dev-dirs.sh"
  run_script "install-home-links.sh"
  seed_local_files
  run_script "install-tmux-plugins.sh"
  run_script "install-claude.sh"
  run_script "set-default-shell-fish.sh"

  log "Bootstrap completo."
  cat <<'EOF'

Siguientes pasos:
  1. Abre Ghostty (Cmd+Space -> "Ghostty") para que cargue el theme y la fuente.
  2. Lanza Neovim (nvim) una vez para que se sincronicen los plugins.
  3. Autentícate en GitHub:   gh auth login
  4. Edita tus datos en git/personal.gitconfig, fish/local.fish, sesh/sesh.toml
     y ~/.config/prt/config.json (no se versionan).
  5. Si abriste una terminal antes del chsh, cierra y vuelve a abrir Ghostty.
EOF
}

main "$@"
