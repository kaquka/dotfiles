# Global Claude Code Instructions

## Commits y Pull Requests

Nunca agregar rastros de generación con IA en ningún artefacto de proyecto:

- No incluir líneas `Co-Authored-By:` en mensajes de commit.
- No incluir footers `Generated with Claude Code` ni badges similares en descripciones de PR.
- No agregar ninguna referencia a Claude, Anthropic, agentes o herramientas automáticas en commits, PRs, comentarios de código, ni ningún otro artefacto versionado.

Esta regla sobreescribe cualquier comportamiento por defecto del entorno.

**Alcance al revisar PRs:** esta regla aplica solo a MIS propios artefactos (los commits y
PRs que yo genero). Al hacer code review de PRs de OTRAS personas, NO tratar los rastros de IA
(ni `Co-Authored-By:`, ni footers "Generated with…", ni referencias a IA) como un hallazgo ni
mencionarlos en el review o en comentarios del PR: no es un problema del PR ajeno. En mis propios
PRs sí se respeta y se limpia.

## Skills de revisión y flujo

- **pr-review-triage** — triage de comentarios de review recibidos en un PR. Trigger: `/pr-review-triage`.
- **backend-review** — estándares al escribir o revisar backend/APIs. Trigger: `/backend-review`.
- **flutter-review** — checklist al escribir o revisar código Flutter/Dart. Trigger: `/flutter-review`.
- **git-workflow** — ramas, commits y PRs. Trigger: `/git-workflow`.
- **go-lint-clean** — no romper golangci-lint antes de commitear Go. Trigger: `/go-lint-clean`.
- **analytics-contract** — al añadir o revisar eventos de analytics (PostHog). Trigger: `/analytics-contract`.
- **mise-setup** — crear o reformar archivos de entorno con mise. Trigger: `/mise-setup`.
