#!/bin/sh

title="$1"
path="$2"
window_name="$3"
current_cmd="$4"
title_source="${5:-pane}"

first_token() {
  printf '%s' "$1" | awk '{print $1}'
}

basename_or_home() {
  case "$1" in
    "" ) printf '%s' "$window_name" ;;
    "$HOME" ) printf '~' ;;
    * ) basename "$1" ;;
  esac
}

# El sidebar de workmux no debe renombrar la ventana: conserva el nombre actual
if [ "$current_cmd" = "workmux" ]; then
  printf '%s' "$window_name"
  exit 0
fi

token="$(first_token "$title")"

if [ -z "$token" ] && [ -n "$current_cmd" ]; then
  token="$(first_token "$current_cmd")"
fi

if [ -z "$title" ] && [ -z "$current_cmd" ]; then
  printf '%s' "$window_name"
  exit 0
fi

if [ "$title_source" = "current" ]; then
  case "$current_cmd" in
    fish|zsh|bash|sh)
      printf '%s %s' "" "$(basename_or_home "$path")"
      exit 0
      ;;
  esac
fi

case "$token" in
  :[0-9]*)
    # servidor marcado por el radar (título ":puerto · tarea"): icono + carpeta
    printf '%s %s' "▲" "$(basename_or_home "$path")"
    ;;
  "✳"|"✻"|"✽"|"✶"|"✢"|"·"|Claude*)
    # Claude Code: icono + carpeta, para distinguir ventanas (y tarjetas del sidebar de workmux)
    printf '%s %s' "✳" "$(basename_or_home "$path")"
    ;;
  "π"|pi)
    printf '%s %s' "π" "$(basename_or_home "$path")"
    ;;
  OC*|OpenCode*|opencode*)
    printf '%s' " OpenCode"
    ;;
  KIRO*|Kiro*|kiro-cli*)
    printf '%s' "󰒓 Kiro"
    ;;
  nvim*|vim*)
    printf '%s %s' "" "$token"
    ;;
  lazygit*|gitui*)
    printf '%s %s' "󰊢" "$token"
    ;;
  atac*)
    printf '%s %s' "󱂛" "$token"
    ;;
  rainfrog*)
    printf '%s %s' "󱘖" "$token"
    ;;
  docker*|orb*|colima*)
    printf '%s %s' "" "$token"
    ;;
  python*|python3*|ipython*)
    printf '%s %s' "" "$token"
    ;;
  node*|nodejs*|npm*|pnpm*|yarn*|bun*)
    printf '%s %s' "" "$token"
    ;;
  fish|zsh|bash|sh)
    printf '%s %s' "" "$(basename_or_home "$path")"
    ;;
  *@*|*.local*)
    printf '%s %s' "󰣀" "$token"
    ;;
  *)
    case "$title" in
      "~"*|/*)
        printf '%s %s' "" "$(basename_or_home "$path")"
        ;;
      *)
        printf '%s %s' "" "$token"
        ;;
    esac
    ;;
esac
