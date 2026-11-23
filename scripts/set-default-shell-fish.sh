#!/usr/bin/env bash
set -euo pipefail

# Asegura que fish exista, esté listado en /etc/shells y sea el shell
# por defecto del usuario actual. La parte de chsh y la edición de
# /etc/shells requieren la contraseña de macOS del usuario.

if ! command -v fish >/dev/null 2>&1; then
  echo "fish no está instalado. Corre 'brew install fish' o 'make brew-bundle' primero." >&2
  exit 1
fi

FISH_PATH="$(command -v fish)"

# Agregar fish a /etc/shells si falta (requiere sudo)
if ! grep -qx "${FISH_PATH}" /etc/shells; then
  echo "Agregando ${FISH_PATH} a /etc/shells (sudo)..."
  echo "${FISH_PATH}" | sudo tee -a /etc/shells >/dev/null
fi

CURRENT_SHELL="$(dscl . -read "/Users/${USER}" UserShell 2>/dev/null | awk '{print $2}' || true)"

if [ "${CURRENT_SHELL}" = "${FISH_PATH}" ]; then
  echo "fish ya es tu shell por defecto."
  exit 0
fi

echo "Cambiando shell a ${FISH_PATH} con chsh (te pedirá tu contraseña)..."
chsh -s "${FISH_PATH}"

echo "Listo. Cierra y abre Ghostty para que tome efecto."
