if status is-interactive
# Commands to run in interactive sessions can go here
end

mise activate fish | source
starship init fish | source

source ~/.config/fish/functions/fish_mode_prompt.fish
set -g fish_greeting

fish_add_path ~/bin
fish_add_path $HOME/.local/bin
fish_add_path $HOME/.opencode/bin

# OrbStack: command-line tools and integration
source ~/.orbstack/shell/init2.fish 2>/dev/null || :

# zoxide initialization
zoxide init fish | source

# Android SDK (Flutter)
set -gx ANDROID_HOME $HOME/Library/Android/sdk
fish_add_path $ANDROID_HOME/platform-tools
fish_add_path $ANDROID_HOME/emulator

# Configuración propia de la máquina (aliases de trabajo, rutas, etc.). No versionada.
test -f ~/.config/fish/local.fish; and source ~/.config/fish/local.fish
