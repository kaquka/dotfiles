---
name: analytics-contract
description: Instrumentation contract for PostHog product analytics (naming, one fact = one event, provenance properties, closed lists, identity, frontend vs backend emitter, PII, safety, per-stack rules for Flutter/Next.js/React/Go/Node); use it whenever code adds, renames, or reviews an analytics event. Triggers - analytics, posthog, track event, logEvent, capture(, funnel, instrumentation, product analytics, evento de analítica, trackear, métricas de producto.
---

# Product analytics: instrumentation contract

You are helping an engineer instrument a product with PostHog. Apply the rules below
as hard gates. **MUST** = do not produce code that violates it. **SHOULD** = follow
unless the user gives a reason. **MAY** = the engineer's call.

When the user asks for an event, first ask (or infer) the **question** it answers.
No question → no event. Propose the funnel before proposing names.

This contract assumes the team keeps a human-readable analytics handbook (event
catalog, closed lists, funnels). This skill is the machine-readable distillation of
it; when they disagree, fix one of them in the same PR.

## 0. What PostHog is NOT for

PostHog receives **facts about the user**. It is typically billed per event, so
diagnostics sent there spend the quota on the wrong thing.

| Belongs to | Examples |
|---|---|
| PostHog | `payment_completed`, `invitation_accepted`, `subscription_started` |
| Crash reporting (Crashlytics, Sentry) | exceptions, stack traces, HTTP errors, full error messages |
| APM / metrics (Datadog, CloudWatch, Firebase Performance) | latency, p99, `HTTP 500`, startup time |
| The domain (your database, warehouse) | audit entries, ledgers, immutable domain records |

**MUST NOT** send to PostHog: HTTP error logs, retries, preference reads, lifecycle
noise, anything that describes the system instead of the person.

A domain record is not an analytics event even when the names look alike: an
`audit_entry` (domain, immutable, legal retention) is not `access_granted`
(PostHog). Who emits what is decided by §6, not by the layer.

## 1. Naming (MUST)

```
<object>_<past_tense_action>      english · snake_case · always past tense
```

```
checkout_started      payment_started     invitation_created    onboarding_started
order_created         payment_completed   invitation_opened     onboarding_completed
order_cancelled       payment_failed      invitation_accepted   onboarding_failed
subscription_started  item_added          access_granted        report_exported
subscription_ended    item_removed        access_denied
```

- No screen, component, or function names (`checkout_screen`, `open_payment_modal`).
- No UI verbs as the base of a name (`button_clicked`, `icon_clicked`, `modal_opened`).
- No abbreviations (`inv_crtd`). No dynamic names (`payment_completed_${provider}`).
- **The product is not in the name**; it is the `product` property.
  `sale_completed` + `product=pos_app`, never `pos_app_sale_completed`.
- Short form by default. Add a domain prefix only when the object is ambiguous
  across domains (`team_invitation_created` only if another invitation type exists).
- **Names come from constants**, never string literals at call sites. Each codebase
  has one event registry (e.g. `AnalyticsEvents`); a name not declared there is not
  emitted. Create the registry before the first event.
- Legacy names already in production that break the rule are not renamed (history)
  and not imitated.

## 2. One fact, one event (MUST)

- Variants are **properties**, never new events:
  `payment_completed{payment_method}`, not `payment_completed_credit_card`.
- Outcomes are properties: `payment_failed{error_category}`, `access_denied{deny_reason}`.
- **Twin test:** two events are one when the **same system** emits both at the **same
  instant** for the **same person**. Measure per-person co-occurrence, not totals. If
  one is the immediate outcome of the other, drop the one that adds no outcome
  (`access_requested` next to `access_granted`/`access_denied` from the same backend).
  A step and its outcome ARE two events when time or emitter separates them
  (`qr_generated` by the app, `qr_presented` by the person minutes later).
- Intent is captured by the client-side event that observes it (`qr_presented`);
  the decision by the backend (`access_granted` / `access_denied`).
- Categories per flow: Discovery, Intent, Completion, Failure. A well-instrumented flow
  has at least Intent + Completion + Failure. 4–5 events per flow, not 30.
- Retention/engagement event: **designate** an existing Completion event
  (`order_created`, `report_exported`). Never `app_opened`.

## 3. Standard properties

**Provenance (MUST on every event, registered once at startup as super-properties):**

| Property | Values | Notes |
|---|---|---|
| `product` | closed list (see "Define your closed lists") | who emits |
| `surface` | `mobile` · `web` · `kiosk` | form factor (attribute of the product; sent anyway) |
| `env` | `production` · `staging` · `development` | default filter of every analysis |
| `app_version` | e.g. `3.4.1` | your own name on web and mobile, even though mobile SDKs also auto-send `$app_version` |

**`reset()` clears super-properties.** After every logout the wrapper MUST register
them again, or every event until the next cold start ships without provenance.

**`vertical` (MUST on every Intent / Completion / Failure event)**, per event, not a
super-property, from your closed list. It is the business line; `product` is the
emitter. Both are needed. The wrapper SHOULD fill it from an event → vertical map;
call sites pass it only when the same event can belong to two lines (a purchase vs a
balance top-up).

**Backend provenance.** A service has no super-properties: the wrapper sets them on
each event from what the client sent in request headers (e.g.
`X-Analytics-Distinct-Id`, `X-Analytics-Product`, `X-Analytics-App-Version`).
`product` = the **originating client product**, never the service; `vertical` and
`env` always; `app_version` only when the client propagated it, never as an empty
string. `surface` is never sent from backend: it is derivable from `product` through
the catalog. When the definitive fact arrives later without a client request (a
payment processor webhook, an async decision), persist that provenance with the
transaction or entity when it is created and read it back when emitting.

**SHOULD, when they apply:** `project_id`, `location_id`, `region_id`, `actor_type`
(`user` · `operator` · `system` · `integration`, whoever caused it; a
webhook-confirmed payment is still `user`). The organization is a PostHog **group**,
not a property (§9).

**MUST NOT duplicate SDK properties:** `$os` (web) / `$os_name` (mobile), `$os_version`,
`$device_type`, `$lib`, `$app_build` arrive automatically. Do not add `platform` or
`operating_system`.

**Dedup key (MUST on every backend event that can repeat):** `transaction_id`,
`order_id`, `attempt_id`. Analyses count distinct facts, not rows.

**Failure vocabulary:** `error_category` is THE reason property on every Failure
event, from a closed set, for example: `validation` · `not_available` ·
`not_authorized` · `expired` · `duplicate` · `provider_declined` ·
`provider_timeout` · `network` · `cancelled_by_user` · `unknown`. A new value is
added to the list (handbook + this skill) before it is emitted. Domains with their
own established vocabulary MAY use a dedicated reason property **instead of**
`error_category` (e.g. `access_denied{deny_reason}`); document each exception.
`recoverable: bool`; durations as `duration_ms`.

**Dedup key on failures:** when the fact failed before an entity existed (no
`transaction_id` yet), use `request_id` = the request's idempotency key.

## 4. Define your closed lists (MUST)

`product` and `vertical` are **closed lists**. Each team fixes its own and keeps them
in one place (the handbook, mirrored in code as constants) as the **single source of
truth**. A value that is not in the list does not exist: add it to the list first,
then emit. Once a value has been emitted, it is never renamed.

Convention for `product`: english, snake_case, one product **per actor**, a suffix
that says the kind: `_app` mobile, `_console` operations/back-office tool, `_web`
end-user facing web. Fictitious example:

| `product` | kind | surface | what it is | status |
|---|---|---|---|---|
| `shop_app` | app | mobile | Customer app: browse, checkout, orders | active |
| `shop_web` | web | web | Customer storefront | active |
| `pos_app` | app | mobile, web | Point of sale used by partner stores | planned |
| `admin_console` | console | web | Internal operations: support, configuration | planned |

A `planned` product MAY emit; the engineer who ships its first event flips it to
`active` in the same PR.

`vertical` = which business line owns the fact. Fictitious example:

| `vertical` | covers |
|---|---|
| `checkout` | cart, checkout, payments for orders |
| `onboarding` | sign-up, verification, first-run setup |
| `subscriptions` | plans, renewals, cancellations |
| `wallet` | balance top-ups and payment methods (not a business line, but payment events need a vertical) |

Tie-break when a flow touches two lines: the vertical is the one whose domain owns
the entity being created or changed.

Other closed lists: `surface` (`mobile` · `web` · `kiosk`), `env` (`production` ·
`staging` · `development`; prefer one PostHog project separated by `env`),
`actor_type` (`user` · `operator` · `system` · `integration`), `error_category` (§3).

## 5. Property values (MUST)

- Primitives only: `String`, `num`, `bool`. **No `null`, no maps, no arrays.** If the
  wrapper fans out to other SDKs (marketing/attribution tools), some of them silently
  drop the whole event when any value is null, nested, or an array.
- No open cardinality: no `error_message`, full URLs, stack traces, free text, custom
  timestamps. IDs (`location_id`, `order_id`, `transaction_id`) MAY go as filters or
  dedup keys, never as the primary analysis dimension.
- Do not add properties "just in case". Each one is stored on every event.

## 6. Identity (MUST)

| Actor | `distinct_id` |
|---|---|
| End user (app, public fronts) | stable internal user id; anonymous until login |
| Console / back-office operator | operator user id; a different person, never aliased to an end user; not repeated as an event property |
| Person without an account (visitor, a customer's own customer, minors) | **not identified**: events with `$process_person_profile: false`, no identify, no alias, no person properties |
| Backend | the client's `distinct_id` that originated the fact (sent in the request), or one already joined by `alias` |

- `distinct_id` is a stable internal id. **Never email, never phone.** It is still
  personal data (pseudonymised) under applicable data-protection law.
- **Never call `identify` without a valid id.** `""`, `"0"`, `"null"`, ids `<= 0`
  collapse all those users into one person, irreversibly. No id → stay anonymous.
- `person_profiles: 'identified_only'` in every client. A `$set` inside `capture` to an
  anonymous user is discarded server-side, but `setPersonProperties`, `group` and
  `alias` DO create the anonymous profile: in clients, never call any of the three
  before `identify`. Before login, only `capture`.
- `reset()` on logout, before any `identify` of the next user, then re-register
  provenance (§3).
- Person properties: `$set` overwrites, `$set_once` never does. **If a value is
  missing, omit the key**, because sending `""` destroys the stored value.
- Identity migrations (e.g. a new identity service id): keep the existing canonical
  `distinct_id`. Join the new id with `alias(newId)` only when non-empty; store it as
  a person property for lookup. **Never call `identify(newId)`**: PostHog silently
  rejects an alias whose id was ever used in identify, splitting the person forever;
  the SDK gets no error, the only trace is the ingestion warning
  `cannot_merge_already_identified` in Data management. Backend events that only know
  the new id use plain `capture` with it. SHOULD: emit `alias` from backend.

## 7. Who emits (MUST)

**The system that knows the truth emits the definitive event.**

| Frontend | Backend |
|---|---|
| `payment_started` | `payment_completed` (processor confirmed) |
| `qr_presented` | `access_granted` / `access_denied` (access system decided) |
| `checkout_started` | `order_created` |

Criterion: **the client emits intent, discovery, and navigation; the backend emits
server state changes** (creations, confirmations, decisions, expiries) even when the
client sees the result in the response. Backend events carry the client's
`distinct_id` (from the request), full provenance (§3), and a dedup key. Async send
(`Enqueue`/`capture` in memory is fine for analytics; an outbox is for domain facts).
Frontend timing by category: Intent events fire on the user's action (submit, tap);
Completion and Failure events fire in the result callback, never in the tap handler.

## 8. Privacy (MUST)

- Everything in PostHog is pseudonymised personal data: analytics and any
  cross-border transfer must be in each product's privacy notice; account deletion
  must delete the person and events in PostHog; read access is granted by role.
- **Event properties: no personal data in the clear.** Person properties MAY carry
  `name`, `email`, `phone` for the **account holder only**, if declared in the privacy
  notice and deletion is implemented. Never for third parties.
- **Never, anywhere:** passwords, access/refresh tokens, PAN, CVV, card data, QR or
  OTP secrets, biometrics or anything derived from them, images, photos, **lat/lng or
  street address** (use `location_id` / `region_id`).
- **Never data of third parties who are not the user:** a visitor someone else
  enrolled, a minor, a customer's own customer, another person's license plate.
  Their events go without a profile (§6).
- Pseudonymous ids of OTHER account holders involved in the fact (the host of an
  invitation, the recipient of a transfer) MAY ride as properties (`host_user_id`)
  for filtering. Identifiers of people without an account never do.
- Track identifiers and categories, not the sensitive value:
  `vehicle_id` not `license_plate`; `has_photo: true` not `photo_url`;
  `error_category: "provider_declined"` not the bank's message.
- Session replay: **MUST be off by default** (project and client: `sessionReplay:
  false` in Flutter, `disable_session_recording: true` in posthog-js). **MUST NOT** on
  identity verification, enforcement, or any surface with a camera or minors. MAY be
  enabled per product in writing, then masking is mandatory: web
  `maskAllInputs: true` + `maskTextSelector: '*'`; Flutter `maskAllTexts` +
  `maskAllImages`.
- Autocapture: **MUST NOT** on any surface showing third-party or minors' data
  (admin/back-office consoles). MAY be on, with a review date, in a low-traffic new
  end-user front. Critical events are always explicit.
- Web URLs: `$current_url` / `$referrer` carry query strings (ids, phones, tokens).
  **MUST** strip query and fragment with `sanitize_properties`.

## 9. Safety (MUST)

Analytics never blocks or breaks the product: async send, silent failure, own
`try/catch` per SDK, never in the critical path (opening a door, completing a
payment).

## 10. Stack rules

- **Flutter**: always through the app's analytics facade
  (`analytics.logEvent(AnalyticsEvents.x, ...)`), never the PostHog SDK directly.
  Provenance is registered at startup and after `reset()`. One `app_opened` per return
  to foreground, not one event per lifecycle transition. Queued offline events keep
  their capture timestamp. If the facade fans out to several SDKs and cannot pick
  destinations per event, remember a new event reaches all of them.

  ```dart
  analytics.logEvent(
    AnalyticsEvents.paymentStarted,
    parameters: {'vertical': 'checkout', 'payment_method': 'credit_card'},
  );
  // ❌ {'user': {'id': x}, 'tags': ['a'], 'note': null}
  // ✅ {'plan': 'premium', 'tag_primary': 'a', 'has_note': false}

  if (userId != null && userId > 0) {
    posthog.identify(userId.toString());
  }
  // on logout: posthog.reset(); then re-register provenance
  ```

- **Web (Next.js / React)**: init with autocapture off, SPA pageviews, identified-only
  profiles, no replay, sanitized URLs. No manual `$pageview` on top of
  `history_change` (double counting). A reload is not an event.

  ```ts
  const stripQueryStrings = (props: Record<string, unknown>) => {
    for (const key of ['$current_url', '$referrer', '$pathname']) {
      const v = props[key]
      if (typeof v === 'string') props[key] = v.split(/[?#]/)[0]
    }
    return props
  }

  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    autocapture: false,
    capture_pageview: 'history_change',
    person_profiles: 'identified_only',
    disable_session_recording: true,
    sanitize_properties: stripQueryStrings,
  })
  posthog.register({ product: PRODUCT.adminConsole, surface: 'web', env, app_version, project_id })
  posthog.identify(session.operatorUserId)       // never aliased to an end user
  posthog.group('organization', session.organizationId, { name: org.name })
  posthog.capture(AnalyticsEvents.invitationCreated, { vertical: VERTICAL.onboarding })
  // on logout: posthog.reset(); posthog.register({ /* provenance again */ })
  ```

- **Backend (Go `posthog-go`, Node `posthog-node`)**: `Enqueue`/`capture` async,
  `distinct_id` from the request, provenance per §3, `vertical`, `actor_type`, dedup
  key. If no shared wrapper exists yet, the first emitting service creates one per
  §11 in its own internal package, owns it, and moves it to the shared library so the
  next service reuses it.

  ```go
  props := posthog.NewProperties().
      Set("transaction_id", txnID).           // dedup key
      Set("payment_method", "credit_card").
      Set("product", txn.Analytics.Product).  // originating client, never the service
      Set("vertical", "checkout").
      Set("env", cfg.Env).
      Set("actor_type", "user")
  if txn.Analytics.AppVersion != "" {         // never send empty strings
      props.Set("app_version", txn.Analytics.AppVersion)
  }
  client.Enqueue(posthog.Capture{
      DistinctId: txn.Analytics.DistinctID,
      Event:      events.PaymentCompleted,
      Properties: props,
  })
  // Visitors without account: Set("$process_person_profile", false).
  ```

  ```ts
  client.capture({
    distinctId: userId,
    event: AnalyticsEvents.accessGranted,
    properties: { attempt_id: attemptId, product: 'admin_console', vertical: 'onboarding', env, actor_type: 'operator' },
  })
  ```

- **Feature flags**: when the PostHog SDK evaluates a flag it attaches
  `$feature/<flag_key>` to events and emits `$feature_flag_called`, which is how
  Experiments counts exposures. When the flag arrives another way (backend bootstrap,
  server-side evaluation) reproduce both by hand:
  `register({'$feature/<key>': variant})` and `capture('$feature_flag_called',
  {$feature_flag: key, $feature_flag_response: variant})`. Without that event the
  experiment shows zero exposures. The event name never changes per variant.
- **Groups**: one group type, `organization`, keyed by the organization the app
  already knows. `project_id` / `location_id` stay properties. Never turn a tenant
  into a person; never repeat the organization as an event property.

## 11. The wrapper

Thin, one per platform. It MUST: inject provenance (and re-inject after `reset`),
expose names as constants, coerce properties to primitives, fail silently. It MUST NOT
validate business rules or grow logic of its own.

## 12. Before finishing: checklist to run on the diff

```
[ ] Every event answers a named question and sits in a funnel; the PR links the analytics spec
[ ] Names: english, snake_case, past tense, from constants, no product in the name
[ ] No twin of an existing event (§2); variants are properties
[ ] product / surface / env / app_version registered once (and after reset); vertical on the event
[ ] product and vertical values exist in the closed lists (§4)
[ ] Properties are primitives, no null, no personal data in the clear, no open cardinality
[ ] Definitive event emitted by the system that knows the truth; backend events carry a dedup key
[ ] identify only with a valid internal user id; never identify(newId) in a migration; reset on logout
[ ] Third parties (visitors, minors, customers' customers) get no person profile
[ ] Autocapture / replay posture matches the product's data sensitivity; web URLs sanitized
[ ] Event has a description in PostHog → Data management
```

## 13. Anti-patterns to reject on sight

`button_clicked` · `payment_completed_${provider}` · `payment_completed` from the UI ·
email as `distinct_id` · `identify(newId)` during an identity migration · new event
because a property was missing · changing the meaning of an existing event · one event
reused for two concepts · full API response as a property · an event nobody asked for.

Never change the semantics of an existing event. Add a property, or create a new
event and deprecate the old one (mark `deprecated` in PostHog with a cut-off date,
warn insight owners, stop emitting; keep history).
