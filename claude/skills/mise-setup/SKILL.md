---
name: mise-setup
description: Crea o reforma los archivos de entorno y tasks de mise de un proyecto (mise.local.toml, mise.dev.toml, mise.prod.toml opcional y un mise.toml central con tasks por perfil), migrando variables de .env existentes y dejándolos todos en .gitignore. Úsala SIEMPRE que el usuario pida configurar mise, crear archivos mise, migrar un .env a mise o armar tasks para correr el proyecto por ambiente. Trigger: `/mise-setup`, 'crea los archivos mise', 'configura mise en este repo', 'pasa el .env a mise', 'tasks de mise para local y dev'.
---

# Estándar mise — Crear archivos de entorno

Cuando el usuario pida crear archivos mise para un proyecto, sigue estas reglas **siempre**.

---

## Paso 0 — Detectar si ya existen archivos de entorno

Antes de crear nada, busca:
- `mise.toml`, `mise.local.toml`, `mise.dev.toml`, `mise.prod.toml`
- `.env`, `.env.local`, `.env.dev`, `.env.prod`, `.env.example`, `.env.template`
- Cualquier archivo `.envrc` o `docker-compose.yml` con variables de entorno

Si alguno existe, **léelo** y úsalo como referencia para los nombres y valores de las variables. Reformatea al estándar de abajo preservando todos los keys.

---

## Archivos a crear

### 1. `mise.local.toml` — entorno local (siempre)

```toml
# mise.local.toml — gitignored
# Variables de entorno LOCAL — no compartir, no commitear
[env]
KEY = "valor_local"
```

### 2. `mise.dev.toml` — entorno desarrollo (siempre)

```toml
# mise.dev.toml — gitignored
# Variables de entorno DESARROLLO
[env]
KEY = "valor_dev"
```

### 3. `mise.prod.toml` — entorno producción (SOLO si se pide explícitamente)

```toml
# mise.prod.toml — gitignored
# Variables de entorno PRODUCCIÓN — manejo restringido
[env]
KEY = "valor_prod"
```

### 4. `mise.toml` — archivo central de tasks (siempre, gitignored)

El nombre del proyecto en los tasks debe ser el mismo que el directorio raíz del repo, en kebab-case (p. ej. repo `my-service` → tasks `local:my-service` y `dev:my-service`).

```toml
# mise.toml — gitignored
# Ejecutor central de tasks. NO contiene valores de entorno.
# Uso:
#   mise run local:<proyecto>   → corre con mise.local.toml
#   mise run dev:<proyecto>     → corre con mise.dev.toml

[tasks."local:<proyecto>"]
description = "Corre <proyecto> con variables de entorno local"
run = "mise --profile local run _run"

[tasks."dev:<proyecto>"]
description = "Corre <proyecto> con variables de entorno de desarrollo"
run = "mise --profile dev run _run"

[tasks._run]
hide = true
run = "<comando para correr el proyecto>"
```

Sustituye `<proyecto>` con el nombre real del proyecto y `<comando>` con el comando de arranque detectado (ej. `go run ./cmd/api`, `npm run dev`, `python -m uvicorn app.main:app`).

Si `mise.toml` ya existe, **agrega** los tasks sin borrar lo que ya hay.

### Ejemplo completo

Para un repo `my-service` con un `.env` que contiene `DATABASE_URL` y `API_BASE_URL`, arrancado con `npm run dev`:

```toml
# mise.local.toml — gitignored
[env]
DATABASE_URL = "postgres://localhost:5432/my_service"
API_BASE_URL = "http://localhost:8080"
```

```toml
# mise.dev.toml — gitignored
[env]
DATABASE_URL = "postgres://dev-db.example.com:5432/my_service"
API_BASE_URL = "https://api.dev.example.com"
```

```toml
# mise.toml — gitignored
[tasks."local:my-service"]
description = "Corre my-service con variables de entorno local"
run = "mise --profile local run _run"

[tasks."dev:my-service"]
description = "Corre my-service con variables de entorno de desarrollo"
run = "mise --profile dev run _run"

[tasks._run]
hide = true
run = "npm run dev"
```

---

## .gitignore

Agrega estas líneas al `.gitignore` del proyecto si aún no están:

```
# mise — never commit
mise.toml
mise.local.toml
mise.dev.toml
mise.prod.toml
```

Si no existe `.gitignore`, créalo.

---

## Cómo funciona el profile de mise

- `mise --profile local` carga `mise.toml` + `mise.local.toml`
- `mise --profile dev` carga `mise.toml` + `mise.dev.toml`
- Las variables del archivo de perfil sobreescriben el bloque `[env]` base de `mise.toml`
- El task `_run` (hide = true) ejecuta el comando real con las variables ya cargadas en el contexto

---

## Reglas fijas

1. `mise.local.toml` y `mise.dev.toml` se crean **siempre**, incluso si el usuario solo menciona uno.
2. `mise.prod.toml` se crea **únicamente** si el usuario lo pide de forma explícita.
3. **Todos** los archivos mise van en `.gitignore`: `mise.toml`, `mise.local.toml`, `mise.dev.toml`, `mise.prod.toml`.
4. Ningún archivo mise se commitea nunca.
5. Si ya hay tasks en `mise.toml`, **no los borres**: agrega los nuevos.
6. Si ya existen env files de cualquier tipo, **migra sus variables** al formato TOML `[env]`, preservando nombres y valores.
7. No agregues variables inventadas; usa solo las que detectes o las que el usuario especifique.
