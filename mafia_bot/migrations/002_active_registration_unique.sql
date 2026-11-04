-- Enforce one active registration per Telegram user and event.
-- Historical cancelled registrations remain intact and may be reactivated by a new row.
-- This migration is for the isolated CHRONOS staging database only.
-- The guard checks that staging has no active duplicates before creating its idempotency index.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.registrations
        WHERE status = 'active'
        GROUP BY event_id, user_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot create registrations active-unique index: duplicate active (event_id, user_id) pairs exist.';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS registrations_one_active_per_user_event_idx
    ON public.registrations (event_id, user_id)
    WHERE status = 'active';

COMMENT ON INDEX public.registrations_one_active_per_user_event_idx IS
    'Prevents duplicate active registrations across Telegram bot and CHRONOS Mini App; cancelled history is preserved.';
