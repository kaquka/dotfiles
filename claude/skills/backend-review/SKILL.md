---
name: backend-review
description: Estándares de calidad y arquitectura para escribir y revisar cambios de backend/APIs (código acotado y coherente con el repo, comentarios mínimos, arquitectura hexagonal pragmática, manejo de archivos de entorno y Markdown temporal, checklist previo a entregar o aprobar). Úsala SIEMPRE que vayas a implementar, modificar o revisar un endpoint, servicio, handler, repositorio o cualquier cambio backend, antes de commitear/abrir un PR o al hacer code review de uno. Trigger: `/backend-review`, 'revisa este cambio de backend', 'implementa este endpoint', 'review del PR del API', 'antes de subir el cambio'.
---

# Backend — Estándares de calidad y arquitectura

Aplica estas reglas en cualquier tarea de implementación, modificación o revisión de APIs y servicios backend. Sirven igual para **escribir** un cambio (lo que debes hacer) que para **revisarlo** (lo que debes señalar si falta o sobra).

---

## Principio base

Antes de escribir o juzgar código, analiza el patrón existente en el repositorio y mantén coherencia con él. El objetivo es un cambio limpio, revisable y alineado al contexto actual — no una arquitectura ideal en el vacío.

Al revisar, la vara de medir es la misma: ¿el cambio encaja con lo que ya hay en el repo? Un diff "teóricamente mejor" pero incoherente con el resto del proyecto es un hallazgo, no una virtud.

---

## Código

- Cambios simples, claros y acotados al alcance solicitado.
- Sin abstracciones prematuras, capas innecesarias ni patrones aplicados por teoría.
- Sin refactors no solicitados alrededor del cambio.
- Sin modificar naming conventions, estructura de carpetas ni patrones existentes sin necesidad clara.
- Cuando detectes una inconsistencia importante, repórtala antes de modificar comportamiento sensible.
- Prioriza cambios incrementales y fáciles de revisar.

## Comentarios

- Omitir por defecto. Solo agregar cuando la intención del código no sea evidente por sí sola.
- Nunca describir qué hace el código — los nombres deben hacer eso.
- Sin docstrings multi-línea ni bloques explicativos extensos.

---

## Arquitectura

Usa **arquitectura hexagonal** (puertos y adaptadores) como guía, con pragmatismo:

- Adapta el nivel de separación al tamaño y complejidad real del módulo.
- No fuerces interfaces, adaptadores o capas si no aportan valor en el contexto actual.
- Responsabilidades bien separadas, pero sin fragmentar lógica cuando no hay beneficio claro.
- Favorece coherencia con el ecosistema existente del proyecto sobre pureza arquitectónica.

Si el repo ya sigue otra arquitectura (capas, MVC, etc.), respeta la del repo: la coherencia gana.

---

## Archivos de entorno y Markdown

### Archivos sensibles de entorno
- Los archivos `mise.*`, `.mise.*`, `.env`, `.env.*` **nunca deben incluirse en staging ni commits**, independientemente del contexto (excepción habitual: plantillas sin secretos como `.env.example`, solo si el repo ya las versiona).
- Si se detecta alguno en staging, retirarlo (`git restore --staged <archivo>`) y notificar al usuario antes de continuar.
- En una revisión, cualquiera de estos archivos en el diff es un hallazgo bloqueante.

### Markdown temporal (análisis, debugging, investigación, notas)
- Crear **únicamente** dentro de `docs/analisis/`.
- Esta carpeta **nunca** debe incluirse en commits, PRs ni staging.
- Agregar `docs/analisis/` al `.gitignore` si no está ya.

### Documentación oficial
- Crear fuera de `docs/analisis/`, en la ubicación que corresponda según el repositorio.
- Antes de agregar un `.md` nuevo, validar si realmente forma parte de la documentación oficial del proyecto.
- No agregar referencias a `.md`, documentación adicional ni servicios de terceros salvo que:
  - Se solicite explícitamente, o
  - Sea estrictamente necesario por integración o comunicación con servicios externos al API trabajada.

---

## Al revisar un cambio

1. Lee el diff completo y, para cada archivo tocado, el código circundante para entender el patrón existente.
2. Pasa el checklist de abajo sobre el diff.
3. Reporta cada hallazgo con: archivo/línea, qué regla incumple y la corrección mínima sugerida.
4. Distingue bloqueantes (archivos de entorno en el diff, cambios fuera de alcance que alteran comportamiento, inconsistencias sensibles) de sugerencias menores (comentarios redundantes, naming).
5. No propongas refactors ni arquitecturas alternativas que excedan el alcance del cambio revisado.

---

## Checklist antes de entregar (o aprobar) un cambio

- [ ] ¿El cambio es coherente con los patrones existentes en el repo?
- [ ] ¿Se introdujo alguna abstracción o capa no solicitada?
- [ ] ¿Hay comentarios que solo describen lo que ya dice el código?
- [ ] ¿Se modificó algo fuera del alcance solicitado?
- [ ] ¿Algún `.md` temporal quedó fuera de `docs/analisis/`?
- [ ] ¿Hay archivos `mise.*`, `.mise.*`, `.env` o `.env.*` en staging o en el diff?
- [ ] ¿Se detectó alguna inconsistencia que deba reportarse antes de continuar?
