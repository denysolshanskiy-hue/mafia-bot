"""Pure CHRONOS calculations shared by the API and unit tests."""

from __future__ import annotations

import math
import random
from typing import Any


AVATAR_BASES = (
    "european_male", "european_female",
    "dark_male", "dark_female",
    "asian_male", "asian_female",
    "android_male", "android_female",
)


def level_for_xp(xp: int) -> tuple[int, int, int]:
    """Return level, XP in current level, XP required for next level.

    Thresholds are intentionally simple and deterministic: 100 XP per level.
    """
    safe_xp = max(0, int(xp))
    level = safe_xp // 100 + 1
    return level, safe_xp % 100, 100


def plackett_luce_probabilities(
    players: list[dict[str, Any]],
    simulations: int = 8000,
    seed: int = 1,
    house_margin: float = 0.05,
) -> dict[int, dict[str, float]]:
    """Estimate exact placement probabilities from a ranking snapshot.

    The score blends points/game, bonus points, win rate and current rank.
    The result is a model estimate, not a guarantee. Odds are frozen by the
    caller when the market is opened.
    """
    if len(players) < 2:
        raise ValueError("At least two ranked candidates are required")
    if simulations < 100:
        raise ValueError("At least 100 simulations are required")
    if not 0 <= house_margin < 0.5:
        raise ValueError("Invalid market margin")

    def normalize(values: list[float]) -> list[float]:
        low, high = min(values), max(values)
        if math.isclose(low, high):
            return [0.5 for _ in values]
        return [(value - low) / (high - low) for value in values]

    ppg = [float(p.get("points", 0)) / max(1, int(p.get("games_played", 0))) for p in players]
    bonus = [float(p.get("bonus_points", 0)) for p in players]
    win_rate = [
        int(p.get("wins", 0)) / max(1, int(p.get("games_played", 0)))
        for p in players
    ]
    rank_signal = [1 / max(1, int(p.get("rank_position", 9999))) for p in players]

    components = list(zip(normalize(ppg), normalize(bonus), normalize(win_rate), normalize(rank_signal)))
    weights = [
        math.exp(2.4 * (0.40 * a + 0.20 * b + 0.20 * c + 0.20 * d))
        for a, b, c, d in components
    ]

    rng = random.Random(seed)
    counts = [{int(player["user_id"]): 0 for player in players} for _ in range(min(3, len(players)))]

    for _ in range(simulations):
        remaining = list(range(len(players)))
        for place in range(min(3, len(players))):
            total = sum(weights[index] for index in remaining)
            pick = rng.random() * total
            chosen = remaining[-1]
            for index in remaining:
                pick -= weights[index]
                if pick <= 0:
                    chosen = index
                    break
            counts[place][int(players[chosen]["user_id"])] += 1
            remaining.remove(chosen)

    result: dict[int, dict[str, float]] = {}
    for place, place_counts in enumerate(counts, start=1):
        result[place] = {}
        for player in players:
            user_id = int(player["user_id"])
            probability = place_counts[user_id] / simulations
            if probability <= 0:
                probability = 1 / (simulations * 10)
            odds = 1 / (probability * (1 + house_margin))
            result[place][str(user_id)] = {
                "probability": probability,
                "odds": round(max(1.05, min(20.0, odds)), 3),
            }

    return result
