# Meal Manager — Coupon Expansion + Delivery-to-Calendar

## Context

The Meal Manager feature shipped end-to-end (backend, 5 scheduler jobs, UI with 25 seed services, LLM-based promo extraction) but two real gaps became visible once live data flowed:

1. **Promo coverage is thin.** The full hunt produced only 17 promos across 8 of 25 services. CouponFollow doesn't have pages for smaller brands (Mosaic, Territory, MealPro, etc.), Wethrift returns sparse content, and merchant homepages hide welcome offers behind JavaScript or in banner images. Target: 3× coverage (~50+ promos, ≥18 services).

2. **Shipment tracking found 0 matches.** The sender patterns (`@cookunity.com`) use plain substring matching, but real shipment emails come from subdomains like `noreply@notifications.factor75.com` that don't contain the seed substring. The user also wants Zero to **auto-create Google Calendar events for delivery dates with reminders**, which is new work that reuses the existing calendar write infrastructure.

Calendar write support, Gmail sync, and the LLM extraction framework all already exist — this plan wires them together rather than building greenfield.

---

## Confirmed decisions (from the clarifying questions)

- **Promo sources to add:** Reddit + Capital One Shopping + Knoji + Slickdeals (default set) + **Rakuten Advertising API** + **email-signup intercept** + **Vision-LLM on homepages** (all three advanced sources opted in).
- **Referral codes:** separate "Referral codes" row on each service card, distinct from promos.
- **Auto-add-to-calendar toggle:** default ON for every service.
- **Calendar event style:** all-day events with a single popup reminder 24 hours before delivery.

---

## Part A — Fix the Gmail→shipment match (quick win, highest impact)

**Root cause:** [meal_shipment_tracker_service.py:136](backend/app/services/meal_shipment_tracker_service.py#L136) uses `if pat and pat in sender`. Pattern `@factor75.com` does not match `noreply@notifications.factor75.com` because the substring `@factor75.com` never appears — the email's domain is `notifications.factor75.com`.

**Fix:**
- Extract the sender's email domain via `sender_email.split("@")[-1]`
- Match using `endswith` against each pattern stripped of leading `@`:
  ```python
  domain = sender_email.split("@")[-1].lower()
  def _matches(pat: str) -> bool:
      p = pat.lstrip("@").lower().strip()
      return domain == p or domain.endswith("." + p)
  ```
- Preserve the existing "pattern is a free-text brand phrase" fallback (patterns without `@` like `"cook unity"` match either sender_email or sender_name).

**File:** [backend/app/services/meal_shipment_tracker_service.py](backend/app/services/meal_shipment_tracker_service.py) — update the pattern-to-service resolution in `scan_recent`.

**Verification:** after rebuild, query `email_cache` for rows whose `from_address->>'email'` domain-ends with any seed pattern domain; confirm count > 0 before re-running the scan.

---

## Part B — Delivery-to-calendar + reminders

**Target flow:** when the shipment scanner upserts a new `meal_shipments` row with an `expected_delivery` date, create an **all-day** Google Calendar event for that day with a **24h-before popup reminder**. On subsequent status updates (delayed / delivered), update the event in place.

**Reuse:**
- [calendar_service.py:586-680](backend/app/services/calendar_service.py#L586) — `create_event(EventCreate)`, `update_event`, `delete_event` all exist and mirror into `calendar_event_cache`.
- [email_rule_service.py `_execute_create_calendar_event`](backend/app/services/email_rule_service.py) — reference pattern.
- `EventCreate`, `EventDateTime`, `EventReminder` models in [backend/app/models/calendar.py](backend/app/models/calendar.py).

**New work:**

1. **Robust delivery-date extraction.** Keep `ETA_RE` regex as the fast path. Add an **LLM fallback** when regex returns nothing, using the existing `unified_llm_client.structured_chat()` pattern (already used in [url_import_service.py:120-130](backend/app/services/url_import_service.py#L120)). Output schema:
   ```python
   {"expected_delivery_date": "ISO 8601 date YYYY-MM-DD",
    "confidence": "high|medium|low",
    "delivery_window_text": "optional human phrasing"}
   ```
   Drop low-confidence picks (skip the event rather than book a wrong date).

2. **New `calendar_event_id` column** on `MealShipmentModel` — declarative `Mapped[Optional[str]]`; `create_tables()` adds on next boot (project already uses this pattern, no Alembic migration).

3. **New service methods on `MealShipmentTrackerService`**:
   - `_extract_delivery_date_llm(body) -> Optional[date]`
   - `_create_delivery_calendar_event(shipment) -> Optional[str]` — builds `EventCreate`, calls `get_calendar_service().create_event`, returns event_id
   - `_update_delivery_calendar_event(shipment, event_id)` — for status changes

4. **Wire into `_upsert_shipment`** so that whenever status is `processing`/`shipped`/`out_for_delivery` AND `expected_delivery` is set AND the service's `auto_calendar` is ON AND `calendar_event_id` is null → create event, store event_id. On `delivered`, update summary to `"✅ <service> delivered"` and clear future reminders. On status change, update ETA.

5. **Per-service opt-in toggle** stored on `MealServiceModel.metadata_` (existing JSONB). Default `auto_calendar: true` for all seeded services.

6. **Event content** (all-day, 24h reminder as user chose):
   - `summary`: `"🍱 <service_name> delivery"`
   - `description`:
     ```
     Order #{order_number}
     Tracking: {tracking_url or tracking_number}
     Meals: {meal_count}
     Charged: ${total_charged}
     Service: <link to /meals>
     ```
   - `start`: `EventDateTime(date=<YYYY-MM-DD>)` (no `date_time` = all-day)
   - `end`: same date (all-day)
   - `reminders`: `[EventReminder(method="popup", minutes=1440)]`
   - Private metadata on the event (via `extendedProperties.private`): `{source: "meal_manager", shipment_id: ..., service_slug: ...}` for future idempotency/dedup

**File changes:**
- [backend/app/db/models.py](backend/app/db/models.py) — add `calendar_event_id: Mapped[Optional[str]]` to `MealShipmentModel`
- [backend/app/services/meal_shipment_tracker_service.py](backend/app/services/meal_shipment_tracker_service.py) — LLM date-extraction + calendar event create/update

---

## Part C — Expand coupon coverage from 17 to ~50+

### Tier 1 — ship first (all four)

**1. Reddit JSON API** — `reddit.com/r/{MealKits|frugal|referralcodes}/search.json?q=<brand>+code&restrict_sr=1&sort=new`. 25/25 coverage, real-time, free. Take top 10-20 results per brand, run each snippet through existing `_extract_codes_llm`.
- New method: `_hunt_reddit(svc)` in [meal_promo_hunter_service.py](backend/app/services/meal_promo_hunter_service.py)
- `PromoSource.REDDIT` enum value already exists.

**2. Capital One Shopping extension endpoint** — undocumented JSON at `capitaloneshopping.com/api/v4/merchant/<slug>/offers`. ~20/25 coverage, no auth. Parse JSON directly (skip LLM extraction; it's structured already).
- New enum value: `PromoSource.CAPITAL_ONE_SHOPPING`
- New method: `_hunt_capital_one_shopping(svc)`

**3. Knoji scrape** — `knoji.com/coupons/<slug>`. Clean HTML, 18/25 coverage. Add URL to `_aggregator_urls`; existing LLM extractor handles it.
- New enum value: `PromoSource.KNOJI`

**4. Slickdeals coupon pages** — `slickdeals.net/coupons/<slug>`. Hourly freshness, 12/25. Same pattern as Knoji.
- `PromoSource.SLICKDEALS` enum value already exists.

### Tier 2 — the three advanced sources the user opted into

**5. Rakuten Advertising Coupon Web Service** (10/25 coverage, highest-quality codes)
- Requires publisher-account approval (3-10 business days, free).
- Add `.env` keys `RAKUTEN_ADVERTISING_USERNAME`, `RAKUTEN_ADVERTISING_PASSWORD`, `RAKUTEN_ADVERTISING_TOKEN`.
- New method: `_hunt_rakuten_advertising(svc)` calls `api.linksynergy.com/coupon/1.0` with `merchantid` lookup. Gated behind env-var presence so v1 ships without blocking on approval.
- New enum value: `PromoSource.RAKUTEN_ADVERTISING`.

**6. Email-signup intercept** (22/25 coverage, best first-order codes)
- New scheduler job `meal_signup_sweep` (weekly, Saturday 3 AM).
- Uses Playwright to visit each merchant's `/signup` or footer newsletter form, submits an alias `meals+<slug>@<user_catchall>` (configurable env var `MEAL_SIGNUP_ALIAS_TEMPLATE`), closes the tab.
- The existing Gmail scanner + shipment tracker already see those welcome emails — so add a new module `meal_signup_parser` that looks for welcome emails by subject/body patterns and extracts the welcome code via `_extract_codes_llm`, persisting to `meal_promo_codes` with `source=PromoSource.EMAIL`, `new_customer_only=true`.
- Idempotent: only signs up per merchant once every 90 days, tracked in `MealServiceModel.metadata_.last_signup_at`.
- **Cost:** adds ~25 marketing emails per sweep cycle to your inbox (user confirmed acceptable).
- New enum value: `PromoSource.SIGNUP_INTERCEPT` (or reuse `EMAIL`).

**7. Vision-LLM on merchant homepages** (closes all 17 dark brands, ~$15/mo)
- Playwright screenshot full-page for each tracked merchant (stealth plugin to avoid bot walls), save to local tmpdir.
- Call Gemini 2.5 Flash Vision via `unified_llm_client` with task_type `meal_vision_extract`, schema: `[{code, discount_type, value, description, location_on_page}]`.
- Runs weekly (Sunday 4 AM) — not every promo hunt — since homepage banners change slowly.
- New file: `meal_vision_extractor_service.py`. Uses existing `get_unified_llm_client()` with Gemini routing.
- New enum value: `PromoSource.VISION`.
- Rate-limit: cap to 25 merchants × 1 screenshot/week = 100 LLM-vision calls/month.

### Referral codes (user confirmed: separate row on cards)

- Sources: `reddit.com/r/referralcodes/search.json?q=<brand>`, `refer.me`, `invitation.codes`, `referralcodes.com`.
- **Data model decision:** add `is_referral: Mapped[bool] = default False` to `MealPromoCodeModel`. Keeps one table (simpler), distinguished by flag. In the UI, split into two sections per card.
- New enum value: `PromoSource.REFERRAL` for the source attribution.

### Hunter architecture cleanup

- Keep the parallelized `asyncio.gather` batching already in place.
- JSON sources (Capital One, Rakuten, Reddit JSON) skip the LLM step.
- HTML sources (Knoji, Slickdeals, CouponFollow, merchant site) go through LLM.
- Preserve 60%-of-subtotal discount sanity cap and known-competitor filter.
- Promote the expanded `_aggregator_urls` function to accept a per-service config so we can disable slow sources selectively.

---

## Part D — UI additions

**Service cards:**
- **"Upcoming deliveries" section** — list next 1-2 deliveries for that service with carrier + ETA + tracking link (or "No shipments" placeholder).
- **"Referral codes" section** — new row distinct from "Top promos", shown only when referral codes exist. Subtle badge: "New customers only · ~$30 off".
- **"Auto-calendar" toggle** — small switch in card header. Writes `metadata_.auto_calendar` via `PATCH /api/meals/services/{id}`. Default ON.

**Overview tab:**
- New **"Upcoming deliveries" widget** above "Hottest promos" — 3 soonest deliveries across all services, with tracking buttons. Uses existing `useShipments()` hook.

**Promos tab:**
- Expose the `description` column (currently hidden).
- Show referral-code rows with a "First-order only" pill.

**No backend endpoint changes needed** — all data is already returned by existing endpoints.

**Files:**
- [frontend/src/pages/MealsPage.tsx](frontend/src/pages/MealsPage.tsx) — add widgets + sections
- [frontend/src/hooks/useMealsApi.ts](frontend/src/hooks/useMealsApi.ts) — type update: `is_referral?: boolean` on `PromoCode`

---

## Scheduler additions

Two new jobs in [scheduler_service.py DAILY_SCHEDULE](backend/app/services/scheduler_service.py):

- `meal_signup_sweep` — `"0 3 * * 6"` (Saturday 3 AM) — Playwright signup intercept
- `meal_vision_sweep` — `"0 4 * * 0"` (Sunday 4 AM) — Gemini Vision homepage extraction

Existing `meal_promo_hunt` (every 4h) stays; just gets new sources layered in.

---

## Critical files to modify

| Area | File | Change |
|---|---|---|
| Match bug | [meal_shipment_tracker_service.py](backend/app/services/meal_shipment_tracker_service.py) | Domain-suffix matching in `scan_recent` |
| Calendar | [meal_shipment_tracker_service.py](backend/app/services/meal_shipment_tracker_service.py) | LLM date extract + `_create_delivery_calendar_event` + update on status change |
| Calendar | [backend/app/db/models.py](backend/app/db/models.py) | Add `calendar_event_id` to `MealShipmentModel`; add `is_referral` to `MealPromoCodeModel` |
| Coupons core | [meal_promo_hunter_service.py](backend/app/services/meal_promo_hunter_service.py) | Reddit + Capital One + Knoji + Slickdeals hunters |
| Coupons Tier 2 | [meal_promo_hunter_service.py](backend/app/services/meal_promo_hunter_service.py) | Rakuten API call (env-gated) |
| Coupons Tier 2 | New: [meal_signup_sweeper_service.py](backend/app/services/meal_signup_sweeper_service.py) | Playwright signup + follow-up welcome-email parser |
| Coupons Tier 2 | New: [meal_vision_extractor_service.py](backend/app/services/meal_vision_extractor_service.py) | Playwright screenshot + Gemini Vision extract |
| Enums | [backend/app/models/meal.py](backend/app/models/meal.py) | Add `CAPITAL_ONE_SHOPPING`, `KNOJI`, `RAKUTEN_ADVERTISING`, `VISION`, `REFERRAL`, `SIGNUP_INTERCEPT` (or reuse EMAIL) to `PromoSource`; add `is_referral` to `PromoCode` + `PromoCodeCreate` |
| Scheduler | [scheduler_service.py](backend/app/services/scheduler_service.py) | Add `meal_signup_sweep` + `meal_vision_sweep` jobs |
| UI | [MealsPage.tsx](frontend/src/pages/MealsPage.tsx) | Upcoming-deliveries widget + per-card deliveries row + referral-codes row + auto-calendar toggle |
| UI | [useMealsApi.ts](frontend/src/hooks/useMealsApi.ts) | `is_referral` field on `PromoCode` type |
| Env | [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py) | `rakuten_advertising_token`, `rakuten_advertising_username`, `rakuten_advertising_password`, `meal_signup_alias_template` settings |

No Alembic migrations — project uses `create_tables()` for declarative column adds.

---

## Verification

1. **Sender-match fix**
   - `docker exec zero-api python -c "..."` to list distinct `from_address` domains in `email_cache`
   - Confirm meal-service domains present
   - `POST /api/meals/shipments/scan?lookback_days=90` — expect `shipments > 0`

2. **Calendar event creation (end-to-end)**
   - Pick any new shipment row; confirm `calendar_event_id IS NOT NULL`
   - Hit `GET /api/calendar/events?days_ahead=30` — confirm the event appears with `summary` prefixed by 🍱 and `reminders=[{method: popup, minutes: 1440}]`
   - Confirm event is visible in Google Calendar UI
   - Simulate a `delivered` status → confirm `update_event` called and summary changes to ✅

3. **Promo coverage target**
   - Baseline: 17 promos / 8 services
   - After Tier 1 (Reddit + Capital One + Knoji + Slickdeals): target **≥40 promos across ≥16 services**
   - After Tier 2 ships (Rakuten approval ~1 week, signup sweep 1st Saturday, vision sweep 1st Sunday): target **≥60 promos across ≥22 services**
   - Verify each source's `PromoCode.source` enum populates correctly

4. **UI smoke test via Playwright**
   - Navigate `/meals`
   - Overview: "Upcoming deliveries" widget renders (or says "No deliveries scheduled")
   - Services tab: every card has 4 links + "Top promos" + "Referral codes" (if any) + "Upcoming deliveries" (if any) + auto-calendar toggle
   - Promos tab shows both regular + referral rows, referral rows have pill
   - Console error count = 0

5. **End-to-end calendar workflow**
   - Manually forward a past CookUnity shipment email to your Gmail
   - Wait for `gmail_check` (≤5 min) + `meal_shipment_scan` (≤30 min) cycles
   - New calendar event for the delivery date, 24h reminder attached
   - Toggle the service's "Auto-calendar" OFF → new shipment upserts do NOT create events

6. **Environment-gated sources** (Rakuten, signup, vision)
   - Without env vars configured: startup logs `rakuten_disabled`, signup job logs `signup_skipped`, vision job logs `vision_disabled`
   - With env vars set: first scheduled run logs the source-specific metrics

---

## Execution order

1. Part A — sender-match fix (30 min; must land first so other work sees real shipment data)
2. Part B — delivery-to-calendar (~2 hr: new column, LLM date extractor, create/update logic, tests)
3. Part C Tier 1 — Reddit + Capital One + Knoji + Slickdeals (~2-3 hr: 4 new hunters, new enum values, parallel integration)
4. Part C referral codes — schema + new sources (~1 hr)
5. Part D UI — upcoming-deliveries widget + referral row + auto-calendar toggle (~1.5 hr)
6. Part C Tier 2 — Vision-LLM sweeper (~2 hr: Playwright screenshot pipeline + Gemini routing)
7. Part C Tier 2 — Email-signup sweeper (~3 hr: Playwright signup automation per merchant + welcome-email parser)
8. Part C Tier 2 — Rakuten Advertising API (gated; code ships disabled until publisher approval lands)
9. Scheduler wiring + rebuild + verification

Ship 1-5 as the first merge; ship 6-8 as a follow-up merge after first verification.
