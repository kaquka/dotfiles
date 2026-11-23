---
name: flutter-review
description: "Checklist accionable para escribir y revisar código Flutter/Dart que evita los errores que el code review saca una y otra vez: i18n (textos hardcodeados), null-safety en render, fuente única de verdad (backend nuevo vs legacy / dos fuentes de datos), flujo offline, manejo de errores en repos (TypeError de fromJson), idempotency keys, estados terminales, serverTime vs reloj del dispositivo, guard anti doble-tap + feedback, layout/overflow/textScale, PII en logs y cobertura de tests. Úsala SIEMPRE que vayas a escribir, modificar o revisar código Dart/Flutter, antes de abrir un PR, al hacer code review de un PR Flutter, o al integrar un endpoint, un DTO, un repo, un cubit/bloc o un widget de estado. Trigger: `/flutter-review`, 'revisa este PR de Flutter', 'checklist Flutter', 'antes de abrir el PR', o cualquier tarea de código Dart/Flutter."
---

# /flutter-review — Checklist para escribir y revisar código Flutter

Checklist que **debes recorrer antes de dar por terminado** un cambio de código Flutter/Dart, y que
sirve igual como **guía de code review** de un PR ajeno. Cada punto nace de hallazgos reales y
recurrentes en reviews; trae el **porqué** y el **patrón correcto**. No es teoría: son errores que
ya se produjeron en apps en producción y no deben repetirse.

> Antes de cerrar: corre `flutter analyze` (0 issues) y `flutter test <carpetas tocadas>`
> (o su equivalente con `fvm` / tu task runner si el proyecto lo usa).

**Modo de uso**

- **Escribiendo código:** recorre el pre-flight (§0) antes de empezar y el checklist completo antes
  de abrir el PR.
- **Revisando un PR:** recorre el diff sección por sección; por cada hallazgo indica archivo/línea,
  el escenario que lo rompe, el impacto y el fix sugerido. Separa bloqueantes de sugerencias.

---

## 0. Pre-flight rápido (si solo lees una sección, lee esta)

Antes de escribir (o aprobar) una línea de UI o de integración, pregúntate:

- [ ] ¿Algún texto visible para el usuario? → **i18n en TODOS los locales** (§1).
- [ ] ¿Un `!` (force-unwrap) sobre algo que viene de red/estado async? → **protégelo** (§2).
- [ ] ¿La card/pantalla decide qué mostrar por una fuente y renderiza datos de OTRA? → **unifica** (§3).
- [ ] ¿Hay rama offline / caché local? → **puebla también el nuevo modelo ahí** (§4).
- [ ] ¿Repo nuevo que parsea JSON? → **catch genérico + limpia estado al fallar** (§5).
- [ ] ¿Mutación de pago/cancelación/reembolso? → **idempotency key estable + estado terminal** (§6, §7).
- [ ] ¿Timer / tiempo transcurrido? → **serverTime, no `DateTime.now()`** (§8).
- [ ] ¿Acción async con botón? → **guard anti doble-tap + feedback de error en ESTA pantalla** (§9).
- [ ] ¿`Row` con dos `Text`? → **`Flexible` + `softWrap`** (§10).
- [ ] ¿Logger HTTP o logs con datos del usuario? → **sin PII en release** (§11).
- [ ] ¿DTO / repo / cubit nuevos? → **tests** (§13). ¿Agregaste una llamada a una dependencia en un
      método muy usado? → **stub ese método en TODOS los mocks existentes** (§13).

---

## 1. i18n — jamás hardcodear texto visible

**Por qué:** textos en un idioma quemados en el widget. En otro locale salen mezclados
("2 hours **y** 5 minutes") o sin traducir. Es el error más repetido.

- Todo string que ve el usuario pasa por el mecanismo de i18n del proyecto (`.tr()`,
  `AppLocalizations.of(context)`, `context.l10n`, etc.), con clave en **todos** los archivos de
  idioma (`.arb`, `.yaml`, `.json`). Todos los locales deben tener **el mismo set de claves**.
- Agrupa por feature: `orders.detail.cancel.title`, `orders.detail.cancel.confirm`, etc.
- **No compongas frases concatenando palabras traducidas con conectores quemados.** El "y"/"and"
  también es una clave (`...time_join`), o mejor, usa una sola clave con placeholders/plurales.
  Mal: `"$h horas y $m minutos"`. Bien: `"$h $hoursStr $join $m $minStr"` o una clave ICU con plural.
- Interpolación con placeholders, no concatenación:
  ```dart
  'orders.detail.subtitle'.tr(namedArgs: {'store': store, 'code': code});
  // es: subtitle: "{store} · Pedido {code}"
  ```
- Si tu `.tr()` depende de un `BuildContext` global (navigatorKey), **no es testeable en unit tests
  puros**; valida la cobertura de i18n comparando los archivos de claves, no pumpeando el widget (§13).

---

## 2. Null-safety en render — nada de `!` sobre datos async

**Por qué:** `Image.memory(state.receiptImage!)` crasheaba cuando una llamada respondía pero la otra
(la que generaba esos bytes) fallaba o llegaba desincronizada.

- Nunca `!` sobre bytes de imagen, respuestas de red o estado que depende de **otra** llamada.
- Protege y degrada con un placeholder, no con un crash:
  ```dart
  if (state.receiptImage != null)
    Image.memory(state.receiptImage!)
  else
    const ReceiptPlaceholder(),
  ```
  o `state.receiptImage ?? Uint8List(0)` si el widget tolera vacío.
- Mejor aún: haz que el widget sea **autosuficiente** desde su fuente (§3).

---

## 3. Fuente única de verdad — no decidas por A y renderices de B

**Por qué:** una pantalla elegía qué card mostrar por `latestOrder.type` (backend nuevo) pero el QR y
el timer se generaban de `legacyStatusResponse` (endpoint legacy). Dos fuentes de datos =
desincronización = crash o datos viejos.

- Si la UI **decide qué mostrar** a partir de una fuente, que **todos los datos de esa card** salgan
  de la misma fuente.
- Patrón: el cubit deriva QR/código/timer **desde el mismo modelo** que discrimina la card
  (`latestOrder.qrCode`, `latestOrder.startedAt`) en un único `_applyLatestOrder(...)`, no mezclando
  con el modelo legacy.
- Al migrar de un endpoint viejo a uno nuevo, migra **todo el bloque de datos**, no solo el
  discriminador.

---

## 4. Offline — puebla también el modelo nuevo

**Por qué:** la rama sin conexión solo poblaba el modelo viejo; como la card ahora se decide por el
modelo nuevo, una operación abierta offline se pintaba como "sin operación".

- Si hay rama `if (!state.hasConnection) { ... return; }`, revisa que **sintetice el modelo nuevo**
  desde la caché/BD local (Drift, Hive, Isar, sqflite…), no solo el modelo viejo.
- Patrón: `_latestOrderFromLocalCache(cached)` → `LatestOrder(type: ..., startedAt: ...)`.
- Al reconectar, un `_onReconnected()` reemplaza con la data real. No rompas ese contrato.

---

## 5. Repos — manejo de error completo (incluido el `TypeError` de `fromJson`)

**Por qué:** los `fromJson` manuales hacen casts estrictos (`json['id'] as String?`). Si el backend
cambia un tipo (`id` numérico, `details` como lista), el `TypeError` escapaba porque el `try` solo
capturaba `DioException` (o `HttpException`). Con codegen (`json_serializable`/`freezed`) pasa lo mismo.

- Todo método de repo que mapea JSON captura **la excepción HTTP Y la genérica**:
  ```dart
  Future<Either<Failure, Order>> getOrder(String id) async {
    try {
      final res = await _client.get('/v1/orders/$id');
      return Right(Order.fromJson(res.data as Map<String, dynamic>));
    } on DioException catch (e) {
      return Left(mapDioException(e));
    } catch (e, st) {
      // TypeError / FormatException de parsing: nunca debe escapar al cubit
      return Left(ParsingFailure(e.toString(), st));
    }
  }
  ```
- Respeta la convención `Either`/`Result` del repo (sea cual sea el lado del error) y no la mezcles.
- **Limpia estado stale al fallar.** Si una card se alimenta de un endpoint y éste falla, emite
  `latestOrder: null` (no dejes una "tarjeta fantasma" con un id obsoleto) y deriva los errores de
  sesión/auth al manejador centralizado.

---

## 6. Idempotency keys — estables por operación lógica

**Por qué:** `completeOrder(id, const Uuid().v4())` generaba key nueva en cada llamada. Si el primer
intento llegaba al server pero el cliente hacía timeout, el reintento iba con otra key → dejaba de
ser replay idempotente → riesgo de **doble cobro/reembolso**.

- Para `complete`/`cancel`/`refund`/`pay`: **una key por intento lógico**, guardada (campo privado
  del cubit o estado), **reutilizada** en reintentos, **liberada** solo tras respuesta definitiva.
  ```dart
  String? _payKey;
  String? _payKeyOrderId;

  Future<void> pay(String orderId) async {
    if (_payKeyOrderId != orderId) {
      _payKey = const Uuid().v4();
      _payKeyOrderId = orderId;
    }
    final result = await _repo.pay(orderId, idempotencyKey: _payKey!);
    result.fold(
      (failure) { /* conserva la key: el retry la reutiliza */ },
      (ok) { _payKey = null; _payKeyOrderId = null; },
    );
  }
  ```
- Nunca `Uuid().v4()` inline en el request de una mutación reintentable.

---

## 7. Estados terminales — no todo response es éxito

**Por qué:** el fold de éxito trataba cualquier `CompleteOrderResponse` como "completado
correctamente", incluso `status == 'expired'` (que no genera reembolso).

- Ramifica por `status`: éxito solo para `completed`/`already_completed` (replay idempotente);
  `expired`/`rejected`/otros → copy distinto, sin afirmar algo que no ocurrió.
- Nunca asumas 2xx = operación feliz; lee el campo de estado del dominio. Usa un `enum` con valor
  `unknown` para estados no reconocidos en lugar de caer al caso feliz.

---

## 8. Tiempo — serverTime, no el reloj del dispositivo

**Por qué:** el timer usaba `DateTime.now()`. Un reloj adelantado terminaba la operación de
inmediato; uno atrasado la sobreestimaba. La respuesta traía `serverTime` y se estaba descartando.

- Persiste `serverTime` del response (o el offset `serverTime - now`) y deriva
  transcurrido/restante de él (`elapsedSecondsAt(serverNowMs)`), con fallback a `DateTime.now()` solo
  si no viene (p. ej. offline).
- Las duraciones basadas en dos epochs del server (`expiresAt - startedAt`) sí son seguras: no
  dependen del reloj local.
- Inyecta el reloj (`DateTime Function() now` o `package:clock`) para poder testearlo.

---

## 9. Robustez de UX en acciones async (doble-tap y feedback)

**Por qué:** al pulsar "Cancelar" y fallar, no pasaba nada visible (el error solo lo escuchaba otra
pantalla) y el botón permitía doble-tap (dos POST).

- **Guard anti doble-tap** en el cubit/bloc: `if (state.isLoading) return;` al inicio del método
  async, y botón deshabilitado mientras carga.
- **Feedback en LA pantalla actual:** escucha el error en el `BlocListener`/`BlocConsumer` de ese
  widget y muestra SnackBar/estado; resetea el flag de error tras mostrarlo. No asumas que otra
  pantalla lo maneja.
- **Respuesta vacía/null:** no infieras un motivo; muestra un error genérico.
- No re-consultes inmediatamente tras una mutación si el backend es **eventualmente consistente**
  (re-poblaría la card que acabas de limpiar); deja el refresh para la reentrada a la pantalla.

---

## 10. Layout — defiende contra textScale y pantallas chicas

**Por qué:** `Row(mainAxisAlignment: spaceBetween)` con dos `Text` sin `Flexible` desbordaba con
textScale grande o a 320dp.

- Filas etiqueta/valor: envuelve **ambos** en `Flexible`, valor con `textAlign: TextAlign.end` y
  `softWrap: true`, con un `SizedBox(width: 8)` entre ellos:
  ```dart
  Row(
    children: [
      Flexible(child: Text(label)),
      const SizedBox(width: 8),
      Flexible(child: Text(value, textAlign: TextAlign.end, softWrap: true)),
    ],
  )
  ```
- Diálogos y bottom sheets: `SingleChildScrollView` para que no se corten en pantallas bajas.
- Prueba con textScale 1.3–2.0 y ancho 320dp antes de dar por bueno un layout.

---

## 11. Detalles que el review siempre pilla (incl. PII en logs)

- **Logs con PII:** loggers HTTP (`PrettyDioLogger`, `LogInterceptor`) imprimen request/response
  completos. En clientes que transportan PII (email, teléfono, documento, dirección, montos, tokens)
  envuélvelos en `if (kDebugMode)`. Nunca en release. Lo mismo para `print`/`debugPrint` con datos
  del usuario.
- **copyWith con sentinel:** si usas un sentinel (`_undefined`) para permitir "limpiar con null
  explícito", **documéntalo** en el campo: cambia la semántica (antes null preservaba; ahora limpia).
- **`Image.network`:** siempre con `errorBuilder` + `loadingBuilder` (fallback mientras carga, sin
  parpadeo) + `cacheWidth` acotado al tamaño real. URLs remotas no confiables: considera validar host.
- **Código muerto:** elimina funciones/campos sin uso que agregaste (helpers "por si acaso").
- **Reutiliza componentes:** si el botón del design system ya tiene `isEnabled`/`isLoading`, úsalo
  para reflejar estados de carga en vez de reinventarlo.

---

## 12. Convenciones del repo (para no inventar)

Antes de escribir, identifica y **respeta** lo que el proyecto ya hace; en review, señala las
desviaciones:

- Toolchain: `flutter` directo, `fvm`, o un task runner (`mise`, `make`, `melos`).
- DTOs: `fromJson` manual vs `json_serializable`/`freezed`. Mantén el estilo existente y usa casts
  defensivos (factories que devuelven null o un valor por defecto ante tipos inesperados).
- Repos: el tipo de retorno estándar (`Either`/`Result`/excepciones) y qué lado es error.
- Clientes HTTP: si hay varios (backend nuevo vs legacy), usa el que corresponde al endpoint.
- Estado (bloc/cubit/riverpod): patrón de `copyWith` y de limpieza de nullables.
- i18n: ubicación de los archivos de idioma y la API de traducción.
- Commits/PRs: la convención del equipo (p. ej. conventional commits `fix(orders): ...`).

---

## 13. Cobertura — qué testear y cómo no romper lo existente

**Regresión típica:** agregar una llamada a una dependencia dentro de un método muy usado (p. ej.
`refreshStatus()` empieza a llamar `orderRepository.getLatestOrder()`) **rompe los mocks existentes**
que no lo stubbean (`type 'Null' is not a subtype of type 'Future<...>'`). → **Stubea el método nuevo
en TODOS los mocks afectados** (`setUp`):

```dart
when(() => orderRepository.getLatestOrder())
    .thenAnswer((_) async => const Right(null));
```

Al agregar features, crea tests para:

- **DTOs:** `fromJson` (campos, defaults, enum `fromValue`, casts defensivos ante tipo inesperado).
- **Extensiones de dominio** (p. ej. timers): límites/clamps y que usen el reloj inyectado, no
  `DateTime.now()`.
- **Repos:** éxito, error HTTP, respuesta null, y que un **`TypeError` genérico NO escape**:
  ```dart
  when(() => client.get(any())).thenThrow(TypeError());
  final result = await repo.getOrder('1');
  expect(result.isLeft(), isTrue); // o el lado de error de tu convención
  ```
  Verifica headers clave (p. ej. `Idempotency-Key`).
- **Cubits/blocs:** éxito/error de cada método, **guard anti doble-tap** (usa un `Completer` para
  dejar la 1ª llamada en vuelo y verifica que la 2ª no dispara otra request), y
  **reutilización/liberación de la idempotency key** (captura las keys de dos llamadas y compara).
- **i18n:** test que carga todos los archivos de idioma y valida que el set de claves del feature
  existe, no está vacío, conserva placeholders y es idéntico entre locales. (No pumpees el modal solo
  para esto: es frágil.)
- **No bajar la barra:** si tocas un flujo con tests, córrelos; deja la suite en verde.

---

## Resumen de una línea

Al tocar (o revisar) código Flutter: **i18n en todos los locales, nada de `!` sobre async, una sola
fuente por card, puebla offline, catch genérico + limpia estado en repos, idempotency estable,
estados terminales, serverTime, guard doble-tap + feedback local, Flexible en filas, sin PII en logs,
y tests (DTO/repo/cubit/i18n) dejando la suite verde.**
