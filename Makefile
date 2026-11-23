SHELL := /bin/bash

.PHONY: bootstrap-macos brew-bundle dev-dirs links tmux-plugins claude fish-shell doctor

bootstrap-macos:
	./scripts/bootstrap-macos.sh

brew-bundle:
	brew bundle --file ./Brewfile

dev-dirs:
	./scripts/install-dev-dirs.sh

links:
	./scripts/install-home-links.sh

tmux-plugins:
	./scripts/install-tmux-plugins.sh

claude:
	./scripts/install-claude.sh

fish-shell:
	./scripts/set-default-shell-fish.sh

doctor:
	@echo "Repo: $$(pwd)"
	@echo "Git status:"
	@git status --short --branch
	@echo
	@echo "Key tools:"
	@command -v nvim >/dev/null 2>&1 && nvim --version | head -n 1 || echo "nvim: missing"
	@command -v tmux >/dev/null 2>&1 && tmux -V || echo "tmux: missing"
	@command -v gh >/dev/null 2>&1 && gh --version | head -n 1 || echo "gh: missing"
	@command -v fish >/dev/null 2>&1 && fish --version || echo "fish: missing"
	@command -v claude >/dev/null 2>&1 && claude --version || echo "claude: missing"
	@command -v ghostty >/dev/null 2>&1 && echo "ghostty: $$(ghostty --version 2>/dev/null | head -n 1)" || echo "ghostty: missing (instala el cask en Brewfile)"
