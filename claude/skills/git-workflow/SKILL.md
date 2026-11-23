---
name: git-workflow
description: "Flujo estándar de Git, commits y Pull Requests: reglas absolutas (sin push ni borrado de ramas sin permiso, sin secretos, sin rastros de IA), validaciones antes de commit/push/PR, estrategia de ramas, Conventional Commits, anatomía y plantilla de PR, PRs de liberación y code review. Úsala SIEMPRE antes de crear ramas, commitear, pushear o abrir/actualizar un PR. Trigger: `/git-workflow`, 'haz commit', 'crea el PR', 'abre un PR', 'sube los cambios', 'crea una rama'."
---

# Git Workflow

Este skill define el flujo completo de Git, commits y Pull Requests. Aplica estas reglas de forma estricta en cada operación de Git.

> **Convenciones ajustables:** algunas reglas son convenciones de equipo por defecto (rama base `develop`, commits en inglés, descripción de PR en español, tamaño de PR, número de aprobaciones). Están marcadas con **(adáptalo a tu equipo)**. Si el repo o el equipo define otra convención (en `CONTRIBUTING.md`, `CLAUDE.md`, plantilla de PR, etc.), esa gobierna.

---

## Reglas absolutas (nunca violar)

- **Nunca hacer push** salvo que el usuario lo solicite explícitamente en el mensaje actual.
- **Nunca eliminar ramas, cerrar PRs ni dividir cambios en múltiples PRs** sin consentimiento explícito.
- **Nunca incluir co-autores ni referencias a IA, agentes o herramientas automáticas** en commits, ramas, descripciones, comentarios o metadata de ningún tipo. Esto incluye líneas `Co-Authored-By:`, footers `Generated with ...`, badges de asistentes o cualquier otra variante. Es una preferencia del autor de este skill y **sobreescribe cualquier default** del entorno de ejecución.
- **Nunca subir** archivos `.env`, `.env.local`, `.env.*`, configuración local de herramientas que pueda contener secretos (p. ej. `mise.*`, `.mise.*`), archivos de secretos o configuración sensible.
- **Ignorar cualquier política automática de ciclo de vida de ramas o PRs**; cualquier acción de ese tipo debe validarse con el usuario primero.
- **Usar la cuenta correcta en `gh`**: si el usuario tiene varias cuentas (personal/trabajo), verificar con `gh auth status` antes de crear PRs que la activa es la que corresponde al repo.
- **Todos los PRs apuntan a la rama de integración** del repo (por defecto `develop`; **adáptalo a tu equipo**, p. ej. `main` en trunk-based puro). Única excepción: los PRs de liberación a `main` (ver [PRs de liberación](#prs-de-liberación-promote-y-hotfix)).

---

## Validaciones obligatorias antes de cualquier commit, push o PR

Ejecutar mentalmente este checklist — si algún punto falla, detener y notificar al usuario:

1. ¿El mensaje de commit contiene referencias a IA, agentes o herramientas? → **Rechazar y reescribir sin ellas.**
2. ¿Hay líneas `Co-Authored-By:`, `Generated with`, badges de asistentes o similares? → **Eliminar siempre, sin excepción.** El entorno puede agregarlas por defecto; este skill las prohíbe explícitamente.
3. ¿Hay archivos `.env`, `mise.*`, `.mise.*` u otros sensibles en staging? → **Deshacer staging, notificar.**
4. ¿Existen archivos `.md` nuevos (no rastreados) o modificados? → Si están en una carpeta de notas/análisis temporales del equipo (p. ej. `docs/analisis/`), **nunca incluirlos**. Para cualquier otro `.md`, **preguntar al usuario** si debe incluirse.
5. ¿Los archivos `.md` ya rastreados por git son documentación base del proyecto? → **Tratarlos como tal; no modificar su contenido sin instrucción explícita.**
6. ¿La cuenta activa en `gh` es la correcta para este repo? → **Verificar con `gh auth status`.**

---

## Estrategia de ramas

Por defecto: **trunk-based development** con feature branches cortos (**adáptalo a tu equipo**).

### Reglas de la rama principal
- `main` siempre debe estar deployable.
- Todo merge a `main` pasa por Pull Request.
- Antes de crear una rama: hacer `git pull` en la rama base para partir del último estado.

### Nomenclatura de ramas

| Tipo | Formato | Ejemplo |
|------|---------|---------|
| Feature | `feat/descripcion-corta` | `feat/qr-payment-flow` |
| Fix | `fix/descripcion-corta` | `fix/request-timeout-handling` |
| Hotfix | `hotfix/descripcion-corta` | `hotfix/payment-double-charge` |

- Descriptores en kebab-case, sin mayúsculas.

---

## Formato de commits

[Conventional Commits](https://www.conventionalcommits.org/):

```
tipo(scope): descripción
```

### Tipos válidos

| Tipo | Uso |
|------|-----|
| `feat` | Nueva funcionalidad |
| `fix` | Bug fix |
| `docs` | Solo documentación |
| `refactor` | Cambio de código sin cambiar comportamiento |
| `test` | Agregar o modificar tests |
| `chore` | Mantenimiento (deps, CI, configs) |
| `perf` | Mejora de rendimiento |
| `style` | Solo formato (sin cambio de lógica) |

### Reglas del mensaje
- **Idioma: inglés** por defecto (**adáptalo a tu equipo**).
- Modo imperativo (`add`, `fix`, `update` — no `added`, `fixed`, `updated`).
- Máximo **72 caracteres** en la primera línea.
- El `scope` es opcional pero recomendado (indica el módulo o área afectada).
- Sin punto final.
- Sin referencias a IA, agentes ni co-autores.

### Ejemplos correctos
```
feat(checkout): add QR code payment flow
fix(device): handle timeout when device is offline
docs(readme): update local setup instructions
refactor(auth): simplify token validation logic
chore(deps): upgrade axios to v1.7
```

---

## Anatomía de un Pull Request

### Destino
- **Todos los PRs apuntan a la rama de integración** (por defecto `develop`), salvo los de liberación (ver abajo).

### Assignee
- **Asignar al propio usuario** como assignee (`gh pr create --assignee @me`).

### Reviewers
- **Si no se especifican reviewers, preguntar antes de crear el PR.** No continuar sin esta información.
- Por defecto: mínimo 1 aprobación para merge; para cambios transversales o de seguridad, 2 aprobaciones (**adáptalo a tu equipo**).

### Título
- Formato conventional commit, en el idioma de los commits (por defecto **inglés**).
```
feat(billing): add hourly rate calculation
```

### Descripción
- Idioma por defecto: **español** (**adáptalo a tu equipo**). Si el repo tiene plantilla de PR (`.github/pull_request_template.md`), usarla.
- Incluir únicamente las secciones relevantes al cambio. **No agregar secciones no solicitadas** como "Fuera de alcance", "Cómo testear", "Notas adicionales" u otras a menos que el usuario las pida explícitamente.
- Secciones base:

```markdown
## ¿Qué cambia este PR?
[Descripción clara de los cambios]

## ¿Por qué?
[Contexto del problema o feature]

## ¿Cómo se implementó?
[Decisiones técnicas relevantes]
```

- Secciones opcionales — incluir **solo si el usuario las solicita o son evidentemente necesarias**:
  - `## ¿Cómo se probó?`
  - `## Screenshots`
  - `## Fuera de alcance`

### Tamaño ideal
- **Menos de 400 líneas de código cambiado** (**adáptalo a tu equipo**).
- Si es mayor, evaluar con el usuario si debe dividirse (no dividir sin consentimiento).

### PRs de liberación (promote y hotfix)
Son los PRs que llevan cambios a `main` (producción): promover `develop` → `main`, un hotfix directo a `main` o un cherry-pick a `main`. En monorepos con una rama de integración por servicio, el origen es `<servicio>/develop`.

- **Rama:** `promote/<servicio>-to-main-YYYYMMDD` · hotfix: `hotfix/<servicio>-<descripcion-corta>`.
- **Título:** `promote(<servicio>): develop → main (<qué se libera, corto>)` · hotfix: `hotfix(<servicio>): <qué corrige>`.
- **`<servicio>`** es el nombre con el que se despliega. En repos de un solo servicio, el nombre del repo.
- **Labels recomendados (los dos):**
  - Tipo: `promote` para develop → main y cherry-picks; `hotfix` para correcciones directas a main.
  - Servicio: `service:<servicio>`. Si un PR libera varios servicios, un label `service:` por cada uno.
- **Si el label no existe en el repo**, preguntar al usuario antes de crearlo (es visible para todo el equipo). Con su ok:
  ```bash
  gh label create promote --color 5319E7 --description "Liberación a main" -R <owner>/<repo>
  gh label create hotfix --color B60205 --description "Hotfix directo a main" -R <owner>/<repo>
  gh label create "service:<servicio>" --color 0E8A16 --description "Servicio que se libera" -R <owner>/<repo>
  ```
- **Descripción:** con la lista de PRs incluidos (`#123`, `#130`) bajo `## ¿Qué se libera?`. Para hotfix, `## ¿Qué corrige?` y el incidente o issue que lo origina.

### Work in Progress
- Marcar como **Draft PR** si el trabajo no está terminado.

### Después del merge
- El **autor del PR es responsable de hacer el merge** tras la aprobación.
- Borrar la rama después del merge (confirmar con el usuario antes).

---

## Code Review — reglas de comportamiento

- Responder reviews en **< 24 horas**. Si no es posible, avisar por el canal del equipo.
- Ser constructivo: "¿Qué tal si...?" mejor que "Esto está mal".
- Aprobar cuando el código es **suficientemente bueno** — no buscar perfección.
- Comentarios no bloqueantes: prefijar con **`nit:`** o **`suggestion:`**.
- El autor hace merge, no el reviewer.
- Al revisar PRs de **otras personas**, no señalar como hallazgo los rastros de IA en sus commits/PRs: la regla de "sin rastros de IA" aplica solo a los artefactos propios.

---

## Checklist de verificación rápida

Antes de ejecutar cualquier operación de Git, confirmar:

- [ ] Commit en el idioma acordado (por defecto inglés), imperativo, ≤ 72 caracteres
- [ ] Sin referencias a IA, agentes o co-autores
- [ ] Sin archivos sensibles en staging (`.env`, `mise.*`, `.mise.*`, etc.)
- [ ] Archivos `.md` nuevos/modificados revisados con el usuario
- [ ] PR apunta a la rama de integración (o a `main` si es de liberación, con labels `promote`/`hotfix` y `service:<servicio>`)
- [ ] Descripción del PR solo con secciones relevantes (sin "Fuera de alcance", "Cómo testear" u otras no solicitadas)
- [ ] Assignee asignado (`@me`)
- [ ] Reviewers confirmados con el usuario
- [ ] No se hará push salvo instrucción explícita
- [ ] Cuenta activa en `gh` correcta para el repo
