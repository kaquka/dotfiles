---
name: pr-review-triage
description: "Triage de los comentarios de review RECIBIDOS en uno o más PRs (humanos o bots): verifica cada comentario contra el código, separa triviales de los que requieren análisis, da escenario/problema/posible fix de cada uno y recomienda cuáles atacar ya. Úsala SIEMPRE que el usuario comparta un PR (URL o número) diciendo que recibió comentarios, o pida verificarlos, atenderlos, priorizarlos o resolverlos. Trigger: `/pr-review-triage`, 'obtuvimos comentarios en el PR', 'revisa los comentarios del PR', 'qué comentarios son triviales', 'atiende el review'. NO es para hacer review de un PR ajeno (eso es /code-review)."
---

# Triage de comentarios recibidos en un PR

Aplica cuando el usuario comparte uno o más PRs con comentarios de review (humanos o bots)
y pide verificarlos, atenderlos o priorizarlos.

## 1. Recolectar
- Leer TODOS los comentarios:
  - `gh pr view <n> --repo <owner>/<repo> --comments` (conversación general)
  - `gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate` (inline)
  - `gh api repos/<owner>/<repo>/pulls/<n>/reviews --paginate` (cuerpos de review)
- Ignorar los hilos ya resueltos/outdated, salvo que sigan aplicando al código actual.
- Agrupar comentarios duplicados o que apuntan al mismo problema.

## 2. Verificar contra el código (no aceptar el comentario a ciegas)
- Abrir el archivo/línea en la rama del PR (`gh pr diff <n>` o hacer checkout/fetch de la
  rama) y confirmar si el problema es real.
- Clasificar cada uno como: ✅ válido · ⚠️ parcialmente válido · ❌ no aplica (explicar por qué).

## 3. Clasificar por esfuerzo/riesgo
- **Trivial**: cambio local, sin impacto en contrato/BD/comportamiento (nombres, typos,
  formato, nil-check obvio, log, test faltante simple).
- **Requiere análisis**: toca contrato de API, migraciones, concurrencia, seguridad/scoping,
  lógica de negocio, o tiene más de un fix posible con trade-offs.

## 4. Reportar (formato fijo)
Tabla resumen:

| # | Autor | Archivo:línea | Tipo (trivial / análisis) | Veredicto (✅/⚠️/❌) |
|---|-------|---------------|---------------------------|----------------------|

Luego, por cada comentario:
- **Escenario**: en qué situación concreta se dispara.
- **Problema**: qué sale mal (dato incorrecto, crash, fuga, deuda).
- **Posible fix**: el cambio concreto (y alternativas, si las hay).

## 5. Recomendación
- Lista de los que se pueden atacar ya sin riesgo (triviales + válidos).
- Lista de los que necesitan decisión del usuario o del equipo, con la pregunta concreta.
- Los ❌ que conviene responder en el hilo, con un borrador de la respuesta.

## Reglas
- No modificar código, no responder en GitHub y no resolver hilos sin aprobación explícita.
- Si hay varios PRs, reportar por PR y cerrar con una recomendación global.
- Todo el reporte en español.
