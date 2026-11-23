#!/usr/bin/env bash
set -euo pipefail

# Crea symlinks desde el repo de dotfiles hacia ~/.config y ~ para cada
# herramienta tracked en el repo. Si ya existe un archivo/dir distinto se
# respalda con sufijo .backup.<timestamp> antes de crear el link.

link_file() {
  local source="$1"
  local target="$2"

  mkdir -p "$(dirname "${target}")"

  if [ -L "${target}" ] || [ -e "${target}" ]; then
    if [ "$(readlink "${target}" 2>/dev/null || true)" = "${source}" ]; then
      return
    fi
    mv "${target}" "${target}.backup.$(date +%Y%m%d%H%M%S)"
  fi

  ln -s "${source}" "${target}"
  echo "  linked $(basename "${target}") -> ${source}"
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}"

mkdir -p "${CONFIG_DIR}"

echo "Linking config directories into ${CONFIG_DIR}..."

# Directorios completos de configuración
for dir in fish gh ghostty git mise nvim opencode sesh tmux; do
  if [ -d "${ROOT}/${dir}" ]; then
    link_file "${ROOT}/${dir}" "${CONFIG_DIR}/${dir}"
  fi
done

# Archivos sueltos
if [ -f "${ROOT}/starship.toml" ]; then
  link_file "${ROOT}/starship.toml" "${CONFIG_DIR}/starship.toml"
fi

# Compatibilidad: muchas herramientas siguen leyendo ~/.tmux.conf y ~/.gitconfig
link_file "${ROOT}/tmux/tmux.conf" "${HOME}/.tmux.conf"
link_file "${ROOT}/git/config" "${HOME}/.gitconfig"

echo "Home links installed."
