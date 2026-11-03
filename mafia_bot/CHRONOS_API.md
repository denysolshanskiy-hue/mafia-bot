# CHRONOS Mini App API

The API is mounted on the existing bot `aiohttp` server. It uses the same `BOT_TOKEN` and `DATABASE_URL` as the Telegram bot.

## Authentication

Send Telegram's raw `Telegram.WebApp.initData` value on every request:

```http
Authorization: tma <raw-initData>
```

Do not send `initDataUnsafe` and do not trust a Telegram user ID supplied in the request body. The backend verifies Telegram's HMAC signature and the `auth_date` timestamp. The default maximum age is 24 hours; it can be changed with `TELEGRAM_INIT_DATA_MAX_AGE` (seconds).

Example browser request:

```js
const initData = window.Telegram.WebApp.initData;

const response = await fetch("/api/chronos/events", {
  headers: { Authorization: `tma ${initData}` },
});
const data = await response.json();
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/chronos/me` | Checks whether the Telegram user has a bot profile and game nickname |
| GET | `/api/chronos/events` | Returns the current draft/active/paused CHRONOS season, active bot-created CHRONOS events, and unlinked planned slots |
| GET | `/api/chronos/events/{event_id}` | Returns an event and its active roster |
| POST | `/api/chronos/events/{event_id}/register` | Registers the authenticated Telegram user in the existing `public.registrations` table |

Registration body is optional:

```json
{ "comment": "Optional note, up to 500 characters" }
```

The backend requires the user to have completed `/start` in the bot and have a game nickname. A registration is allowed only while the CHRONOS season is active and the original bot event has `event_type = 'chronos'` and `status = 'active'`.

## Data ownership and safety

- The Telegram bot remains the only creator of live events and owns the event broadcast.
- The Mini App reads live event details from `public.events` and the roster from `public.registrations`.
- Mini App registration writes to the same `public.registrations` table. It does not create an event or send a duplicate group/bot broadcast.
- Planned slots are stored in `chronos.event_slots`; when the bot creates the real event, an admin-side mapping can link the slot to its `event_id`.
- Event rosters are not capped at ten people. `players_per_game = 10` is the number of seats in one Mafia game, not the maximum size of an evening roster.
- Active duplicate registrations are prevented by the partial unique index created in migration `002_active_registration_unique.sql`. Cancelled historical rows are preserved.

## Database rollout

Run migrations manually in Neon SQL Editor in this order:

1. `001_chronos_foundation.sql` — creates the schema, a draft `CHRONOS` season, and 13 planned slots.
2. `002_active_registration_unique.sql` — prevents duplicate active registrations.

Migration 002 deliberately stops if duplicate active `(event_id, user_id)` registrations exist. Do not run `database.init_db()` against production; that function contains an outdated schema definition.

The season is deliberately seeded as `draft`. When the schedule and app are ready to accept registrations, activate it manually:

```sql
UPDATE chronos.seasons
SET status = 'active', updated_at = NOW()
WHERE season_code = 'CHRONOS';
```

Pause registrations without deleting data by changing the status to `paused`. Planned slots remain in the calendar; only events created by the bot and marked `event_type = 'chronos'` are treated as live events.

## Current scope

This PR adds the backend API only. The Mini App's visual frontend, launch button/menu entry, and admin-side event-slot mapping are separate next steps.


## Mini App launch

The visual Mini App is served from `/miniapp` on the same aiohttp server as the bot. Set the Koyeb environment variable:

```text
CHRONOS_WEBAPP_URL=https://YOUR-PUBLIC-HOST/miniapp
```

Use the real public HTTPS domain assigned to the Koyeb service. The CHRONOS launch button appears in the admin/player Telegram reply keyboard only when this value is a valid HTTPS URL. Without it, existing menus remain unchanged.
