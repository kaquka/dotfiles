#!/usr/bin/env bash
set -euo pipefail

# Instala la configuración de Claude Code del repo en ~/.claude:
#   - statusline.sh, keybindings.json y cada skill de claude/skills -> symlinks
#     (si ya existe algo distinto con ese nombre, se respeta y se avisa)
#   - settings.json y CLAUDE.md -> se copian solo si no existen
#     (si existen, revisa las plantillas y mezcla a mano)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/claude"
DEST="${HOME}/.claude"

mkdir -p "${DEST}/skills"

link_if_free() {
  local source="$1" target="$2"
  if [ -L "${target}" ] && [ "$(readlink "${target}")" = "${source}" ]; then
    return
  fi
  if [ -e "${target}" ] || [ -L "${target}" ]; then
    echo "  skip ${target} (ya existe; compáralo con ${source})"
    return
  fi
  ln -s "${source}" "${target}"
  echo "  linked ${target}"
}

link_if_free "${SRC}/statusline.sh" "${DEST}/statusline.sh"
link_if_free "${SRC}/keybindings.json" "${DEST}/keybindings.json"

for skill in "${SRC}"/skills/*/; do
  name="$(basename "${skill}")"
  link_if_free "${SRC}/skills/${name}" "${DEST}/skills/${name}"
done

copy_if_missing() {
  local source="$1" target="$2"
  if [ -e "${target}" ]; then
    echo "  keep ${target} (mezcla a mano con ${source} si quieres)"
  else
    cp "${source}" "${target}"
    echo "  copied ${target}"
  fi
}

copy_if_missing "${SRC}/settings.example.json" "${DEST}/settings.json"
copy_if_missing "${SRC}/CLAUDE.md" "${DEST}/CLAUDE.md"

echo "Claude Code config ready."
