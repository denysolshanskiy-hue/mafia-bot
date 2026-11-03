"""Event type detection based on the event title.

Keep this function side-effect free: creating a CHRONOS event must not
change the existing event creation, registration, or broadcast workflow.
"""

import re


CHRONOS_MARKERS = (
    # Season / brand names
    "chronos",
    "хронос",
    "хранителі часу",
    "хранителів часу",
    "хранители времени",
    "хранителей времени",
    "time guardians",
    "guardians of time",
    # INITIALIZATION stage
    "initialization",
    "ініціалізація",
    "инициализация",
    "кубок ініціалізації",
    "кубок инициализации",
    # STABILITY stage
    "stability",
    "стабільність",
    "стабильность",
    "кубок стабільності",
    "кубок стабильности",
    # OVERDRIVE stage
    "overdrive",
    "овердрайв",
    "кубок овердрайву",
    "кубок овердрайва",
    # Main final
    "chronos final",
    "main final",
    "головний фінал",
    "главный финал",
    "фінал хроносу",
    "финал хроноса",
    "фінал хранителів часу",
    "финал хранителей времени",
)


def detect_event_type(title: str) -> str:
    """Return chronos, underground, school, or classic for an event title.

    CHRONOS markers have precedence so titles such as
    "CHRONOS — MAFIA UNDERGROUND" remain CHRONOS events.
    Existing UNDERGROUND and SCHOOL matching is preserved.
    """
    normalized = re.sub(r"[^\\w]+", " ", (title or "").casefold(), flags=re.UNICODE)
    normalized = " ".join(normalized.split())

    if any(marker in normalized for marker in CHRONOS_MARKERS):
        return "chronos"

    if "underground" in normalized:
        return "underground"

    if "школ" in normalized:
        return "school"

    return "classic"
