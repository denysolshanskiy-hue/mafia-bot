# CHRONOS Mini App and platform

The Mini App is served by the existing bot aiohttp server. It uses the existing BOT_TOKEN and DATABASE_URL; it does not create a second bot, event system, or registration table.

## Current implementation

### Player experience
- Home, 10-floor Tower, planned/live event calendar, event detail and roster, registration and cancellation.
- Profile identity: eight selectable avatar bases, earned titles and up to two earned badges.
- Operations: personal confirmed game count, current qualification check, attendance summary and final invitations.
- iMafia ranking snapshots and global synchronization counter (690 game participations).
- CODE BREAKER and MEMORY server-authoritative mini-games. Session state and answer keys are stored on the server.
- CR / EX / XP ledger, achievements, collection, catalogue, equipment and player ledger history.
- No-stake Prediction Exchange: probability-weighted EX rewards, no penalty for an incorrect forecast, self-prediction protection, per-event limits and automatic voiding when the registered roster changes.
- In-app notification inbox and category preferences.

### Admin console
- Season state and draft activity/prediction settings.
- Planned slot dates/titles and mapping to real bot-created CHRONOS events.
- iMafia screenshot upload, server OCR draft, manual JSON correction, review, confirm or reject.
- Ranking snapshot import and confirmed game-results import. Each game must have exactly 10 unique mapped players and placements 1–10.
- Final TOP-10 invitation creation, accepted/declined responses, next-rank replacement and manual expiry processing.
- Attendance closure after the linked bot event is closed.
- Prediction market creation and settlement / void-refunds.
- Prize award drafts, approval and manual paid status.
- Catalog pricing/enablement, economy rule approval, idempotent ledger reconciliation, fixed prize validation, 500 UAH Activity Bonus calculation/approval, player list and audit log.

## Authentication and data ownership

Every /api/chronos/* request must include Telegram's raw Telegram.WebApp.initData value in the Authorization header using the tma scheme.

Do not send initDataUnsafe and do not trust a Telegram user ID supplied in the body. The backend verifies Telegram's HMAC signature and auth_date. Default maximum age is 24 hours; configure TELEGRAM_INIT_DATA_MAX_AGE in seconds to change it.

- The Telegram bot remains the only creator of live events and the owner of bot/group event broadcasts.
- Live events and rosters use the existing public.events and public.registrations tables.
- Mini App registration/cancellation uses those same registrations. It does not send a second broadcast.
- Evening roster size is not capped at ten. Ten is the number of seats in one Mafia game.
- Ranking snapshots, played-game rows, and attendance are only changed by an admin-confirmed import; OCR output alone never changes a ranking.

## API routes

All paths below are authenticated with Telegram initData.

| Area | Method | Path |
|---|---|---|
| Events | GET | /api/chronos/events |
| Events | GET | /api/chronos/events/{event_id} |
| Events | POST | /api/chronos/events/{event_id}/register |
| Events | POST | /api/chronos/events/{event_id}/cancel |
| Profile | GET / POST | /api/chronos/identity, /identity/avatar, /identity/appearance |
| Store | GET / POST | /api/chronos/store, /store/{item_id}/buy, /store/{item_id}/equip |
| Player data | GET | /api/chronos/operations, /rankings, /achievements, /collection, /ledger |
| Notifications | GET / POST | /api/chronos/notifications, /notifications/{id}/read, /notifications/preferences |
| Mini-games | GET / POST | /api/chronos/games, /games/{game_code}, /games/sessions/{session_id}/action |
| Predictions | GET / POST | /api/chronos/predictions, /predictions/markets/open, /predictions/markets/{id}/bet, /predictions/markets/{id}/settle |
| Admin | GET / POST | /api/chronos/admin/* (overview, slots, imports, invitations, prizes, economy, catalog, players, audit and settings) |

## Database migrations

Run these manually in a staging Neon branch first, after confirming the existing public schema and making a backup:

1. 001_chronos_foundation.sql — schema, draft CHRONOS season and 13 planned slots.
2. 002_active_registration_unique.sql — partial unique index preventing duplicate active registrations. It intentionally stops when duplicate pairs exist.
3. 003_chronos_platform.sql — identity, inventory, currency ledger, ranking/game imports, attendance, mini-games, predictions, notifications, prizes and audit structures.
4. 004_chronos_economy.sql — versioned CR/EX/XP rules, no-stake prediction support, cosmetic prices and the separate 500 UAH Activity Bonus allocation table.

Do not execute database.init_db() as a production migration. It contains a legacy DDL definition and is not a schema migration tool.

**Schema compatibility check before applying:** the existing bot database must contain public.users, public.events, and public.registrations with the columns used by the API, including public.events.event_type. PR #2 adds event-type detection in the bot but does not include a SQL migration. Confirm that the deployed database already has event_type; if it does not, add and review a separate compatibility migration before deploying.

## Environment variables

Existing:
- BOT_TOKEN
- DATABASE_URL
- PAYMENT_CARD_NUMBER — required by PR #2 to preserve the current bot payment-message flow.

For Mini App:
- CHRONOS_WEBAPP_URL=https://YOUR-PUBLIC-HOST/miniapp — actual Koyeb public HTTPS URL.
- TELEGRAM_INIT_DATA_MAX_AGE=86400 — optional initData age limit in seconds.

The Docker image installs Tesseract with Ukrainian and English language packs for screenshot OCR. OCR is an assistive draft only; an admin must correct and confirm every import.

## CHRONOS economy v1.0

The detailed method and worked cohort simulation are documented in CHRONOS_ECONOMY.md. The current rule set is kept in DRAFT until approved in the admin console.

- CR: 5 per confirmed game plus 10 once per attended evening. Spent only on cosmetics.
- XP: 10 per confirmed game, 5 per attended evening, 20 for each distinct mini-game first clear, and 5 per repeat completion up to 10 repeats. XP is progression-only.
- EX: free predictions with no stake. A correct prediction earns clamp(5, 100, round(5 / probability)) EX; an incorrect forecast costs zero. Maximum three forecasts per event, six accepted forecasts to open EX Store, and a hard 500 EX seasonal cap.
- Activity Score: 80% attendance + 15% unique verified event-level app interactions (maximum one per event across 13 possible events) + 5% mini-game completions (maximum five). Only personally invited finals count in a player's attendance denominator.
- Qualification: ceil(30% × conducted confirmed core games); for the planned 69 core games this is 21 games.
- Fixed prizes: 6,000 UAH across the three intermediate finals and 6,000 UAH for the Main Final. Fixed place prizes are not reduced by Activity Score.
- Separate Activity Bonus: 500 UAH split proportionally by Activity Score among the initial Main Final Top-10 who meet qualification, using largest-remainder rounding. The allocation is saved as draft and requires approval.
- Seasonal cash commitment: 12,500 UAH total, including the separate 500 UAH bonus pool.
- CR and EX are cosmetic currencies only; XP is non-spendable. None can be purchased for UAH, transferred or withdrawn.

Cosmetic catalogue prices:
- CR: 80–320 CR across nine unique items.
- EX: 25–250 EX across eleven unique items.
- All catalogue items are disabled until separately enabled by an administrator.

Activity Score, economy and prediction rules must be approved in that order. Activity Score is fixed at 80/15/5 in this version; rate changes require a versioned economy update. The simulator assumes both mini-game types are cleared for its standard cohort examples; actual XP depends on which distinct first-clear types a player completes.

The sporting iMafia rank and 30% qualification are not affected by CR, EX, XP, purchases, mini-games or app engagement.


## Checks already run

GitHub Actions on the latest PR #4 head completed successfully:
- Python compile check.
- JavaScript syntax check for app.js and modules.js.
- Existing unit tests.
- Imports and aiohttp route registration for player/admin modules.
- Existence of all Mini App static assets.

This is not a live Neon integration test or a rendered Telegram WebView test. Those remain pre-launch acceptance checks.

## Safe rollout order

1. Review and merge PR #2 first (event type classifier; it remains a draft and requires PAYMENT_CARD_NUMBER in Koyeb).
2. Merge PR #4 only after PR #2 is on main.
3. Apply migrations 001, 002, 003 and 004 in staging, verify schema and sample data, then repeat on production only after backup and approval.
4. Configure CHRONOS_WEBAPP_URL, TELEGRAM_INIT_DATA_MAX_AGE, and verify the public HTTPS Mini App launch in Telegram.
5. Run admin/player acceptance tests and only then decide whether to activate the season.

No Neon migration, PR merge, Koyeb deployment, environment-variable change or season activation is performed by this implementation work.
