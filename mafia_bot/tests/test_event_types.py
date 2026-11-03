import unittest

try:
    from modules.event_types import detect_event_type
except ModuleNotFoundError:
    from mafia_bot.modules.event_types import detect_event_type


class DetectEventTypeTests(unittest.TestCase):
    def test_chronos_brand_variants(self):
        titles = [
            "CHRONOS — Вечір #1",
            "ХРОНОС: Вечір #2",
            "ХРАНИТЕЛІ ЧАСУ — Вечір #3",
            "Хранителів часу: сезон",
            "CHRONOS Season",
            "Time Guardians — Evening",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(detect_event_type(title), "chronos")

    def test_chronos_stage_variants(self):
        titles = [
            "INITIALIZATION CUP",
            "Кубок ініціалізації",
            "Ініціалізація — CHRONOS",
            "STABILITY CUP",
            "Кубок стабільності",
            "Стабильность",
            "OVERDRIVE CUP",
            "Кубок овердрайву",
            "Овердрайв",
            "CHRONOS FINAL",
            "MAIN FINAL",
            "Головний фінал",
            "Фінал Хроносу",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(detect_event_type(title), "chronos")

    def test_existing_event_types_are_preserved(self):
        self.assertEqual(detect_event_type("MAFIA UNDERGROUND"), "underground")
        self.assertEqual(detect_event_type("☣️ Underground — classic"), "underground")
        self.assertEqual(detect_event_type("Школа мафії"), "school")
        self.assertEqual(detect_event_type("Класична мафія"), "classic")

    def test_chronos_marker_has_precedence(self):
        self.assertEqual(
            detect_event_type("CHRONOS — MAFIA UNDERGROUND"),
            "chronos",
        )


if __name__ == "__main__":
    unittest.main()
