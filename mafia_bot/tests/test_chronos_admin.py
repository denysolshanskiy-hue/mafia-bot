import unittest
from datetime import date, datetime, timedelta, timezone

from modules.chronos_admin import _invitation_deadline


class InvitationDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def test_deadline_is_at_most_seven_days_when_final_is_far_away(self):
        deadline = _invitation_deadline(date(2026, 11, 20), self.now)
        self.assertEqual(deadline, self.now + timedelta(days=7))

    def test_deadline_is_48_hours_when_final_is_less_than_seven_days_away(self):
        deadline = _invitation_deadline(date(2026, 11, 10), self.now)
        self.assertEqual(deadline, self.now + timedelta(hours=48))

    def test_exactly_seven_calendar_days_uses_seven_day_limit(self):
        deadline = _invitation_deadline(date(2026, 11, 11), self.now)
        self.assertEqual(deadline, self.now + timedelta(days=7))


if __name__ == "__main__":
    unittest.main()
