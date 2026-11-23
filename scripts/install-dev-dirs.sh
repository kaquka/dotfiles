#!/usr/bin/env bash
set -euo pipefail

# Crea las carpetas base de proyectos para que abrir una sesión de sesh o un
# alias nunca falle por una carpeta inexistente.
# Carpetas extra propias de la máquina: una por línea en scripts/dev-dirs.local
# (no versionado; usa ~ para el home).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

dirs=(
  "${HOME}/dev/work"
  "${HOME}/dev/personal"
  "${HOME}/bin"
)

if [ -f "${ROOT}/dev-dirs.local" ]; then
  while IFS= read -r line; do
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    dirs+=("${line/#\~/${HOME}}")
  done < "${ROOT}/dev-dirs.local"
fi

for d in "${dirs[@]}"; do
  if [ ! -d "${d}" ]; then
    mkdir -p "${d}"
    echo "  created ${d}"
  fi
done

echo "Dev directories ready."
