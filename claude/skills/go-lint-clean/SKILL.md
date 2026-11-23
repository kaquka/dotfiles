---
name: go-lint-clean
description: "Estándar para que golangci-lint (gofmt/goimports/errcheck/govet) NO se rompa al tocar código Go: igualar la versión del CI, formatear antes de commitear y evitar los rompe-lint típicos. Úsala SIEMPRE antes de commitear/pushear cambios en un repo Go, cuando el CI de Lint falla, o cuando haya errores de gofmt/goimports/golangci-lint. Trigger: `/go-lint-clean`, 'se rompió el lint', 'errores de gofmt', 'File is not properly formatted', o antes de subir cambios a un repo Go."
---

# /go-lint-clean

Estándar para no introducir errores de lint en proyectos **Go** que usan golangci-lint en CI. El objetivo es que **el job de `Lint` pase siempre** sin sorpresas y sin alinear código a mano.

## Contexto: cómo corre el CI

Antes de nada, **lee la config del repo**:

- `.golangci.yml` (o `.golangci.yaml` / `.golangci.toml`): linters habilitados, formatters, exclusiones.
- El workflow de CI que corre el lint (p. ej. `.github/workflows/*lint*.yml`, `.gitlab-ci.yml`, `Makefile`): versión pinneada de golangci-lint, comandos exactos y en qué ramas corre.

Un setup típico con **golangci-lint v2** tiene dos pasos (el segundo es el que más se rompe):

1. `golangci-lint run` — linters habilitados en `.golangci.yml` (frecuentemente `errcheck`, `govet`).
2. `golangci-lint fmt --diff` — **falla si el formato no es idempotente** (gofmt + goimports). Un solo espacio mal alineado rompe este paso.

Si el CI solo corre en push a las ramas principales (p. ej. `main`/`develop`) y no en ramas feature, el error aparece cuando ya se mergeó → hay que atraparlo **antes de commitear**.

## Regla de oro (obligatoria antes de cada commit)

Nunca commitees Go sin correr el formateador. En la raíz del repo:

```bash
golangci-lint fmt          # aplica gofmt + goimports in-place (arregla ~99% de los fallos)
golangci-lint run          # verifica errcheck/govet y demás
golangci-lint fmt --diff   # debe salir vacío (exit 0) — esto es lo que valida el CI
```

Si `fmt --diff` sale vacío y `run` dice `0 issues`, el CI de lint pasará. **No inspecciones ni alinees a mano**: deja que `golangci-lint fmt` lo haga. Si el CI usa otros comandos, replica exactamente los del workflow.

## Instalar golangci-lint en la versión del CI

No confíes en la versión global; usa la **fijada en el workflow de CI** (p. ej. `version:` de `golangci/golangci-lint-action`). Versiones distintas pueden formatear o reportar distinto.

```bash
# localiza la versión pinneada en los workflows
grep -rn -A3 'golangci-lint' .github/workflows/ | grep -i version

# instálala en el GOPATH/bin
curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh \
  | sh -s -- -b "$(go env GOPATH)/bin" vX.Y.Z
```

Luego usa `$(go env GOPATH)/bin/golangci-lint ...` (o agrega `$(go env GOPATH)/bin` al `PATH`) y confirma con `golangci-lint version`.

## Los 2 rompe-lint más comunes (gofmt/goimports)

Casi todos los fallos son de **formato**, no de lógica. Los dos que más aparecen:

### 1. Orden de imports (goimports)
Al agregar un import nuevo hay que dejarlo en **orden alfabético dentro de su grupo**. Es fácil colocarlo "donde parece que va" y romperlo:

```go
// ❌ mal — sourcepaymentmethodrepo fuera de orden
"github.com/acme/app/repositories/paymentrepo"
"github.com/acme/app/repositories/sourcepaymentmethodrepo"
"github.com/acme/app/repositories/permissionauditrepo"

// ✅ bien — goimports lo ordena así
"github.com/acme/app/repositories/paymentrepo"
"github.com/acme/app/repositories/permissionauditrepo"
...
"github.com/acme/app/repositories/sourcepaymentmethodrepo"
```

### 2. Alineación de struct/const literals (gofmt)
Al agregar un campo con nombre **más largo** a un struct literal (o un bloque `const`/`var` alineado), gofmt re-alinea **toda** la columna de `:` o `=`. Si editas a mano solo tu línea, rompes la alineación del resto:

```go
// ❌ el campo nuevo LegacyTransactionID desalinea el bloque
payment := &domain.Payment{
    ID:            uuid.New(),
    TransactionID: txID,
    LegacyTransactionID: legacyTxIDPtr,   // ← rompe la columna
}

// ✅ gofmt re-alinea TODO el bloque a la clave más larga
payment := &domain.Payment{
    ID:                  uuid.New(),
    TransactionID:       txID,
    LegacyTransactionID: legacyTxIDPtr,
}
```

La lección: **cualquier** cambio en un bloque alineado (agregar/quitar/renombrar un campo) obliga a re-formatear todo el bloque. No lo hagas a mano — corre `golangci-lint fmt`.

## Otras cosas a revisar en `.golangci.yml`

- `gofmt.simplify: true` y rewrite-rules frecuentes: `interface{}` → `any` y `a[b:len(a)]` → `a[b:]`. Si están activas, escribe `any` directamente.
- Directorios excluidos (código generado como `ent/`, `vendor/`, `docs/`, `examples/`, mocks): no toques código generado para "arreglar" lint; se regenera.
- Si `errcheck` está activo: **no ignores errores** silenciosamente. Maneja el `err` o asígnalo explícitamente a `_ =` solo cuando sea intencional y justificado.
- Linters comentados/desactivados (`staticcheck`, `revive`, `unused`, `gosec`…) suelen estar pendientes de activación incremental. No los actives salvo que se pida.

## Checklist rápido

Antes de `git commit` en cualquier proyecto Go:

- [ ] Versión local de golangci-lint = versión pinneada en el CI.
- [ ] `golangci-lint fmt` corrido en la raíz.
- [ ] `golangci-lint run` → `0 issues`.
- [ ] `golangci-lint fmt --diff` → salida vacía.
- [ ] Import nuevo en orden alfabético dentro de su grupo.
- [ ] Bloques struct/const/var re-alineados (no a mano).

> Si un fallo de lint viene de un archivo que **no** tocaste (llegó por un merge de la rama base), sigue siendo válido corregirlo con `golangci-lint fmt` en un commit `style:` aparte; deja tu commit de feature limpio.
