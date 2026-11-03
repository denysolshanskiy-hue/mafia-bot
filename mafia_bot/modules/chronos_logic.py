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

    def safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def median_or(values: list[float], fallback: float) -> float:
        if not values:
            return fallback
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    games = [max(0, safe_int(player.get("games_played", 0))) for player in players]
    known_indexes = [index for index, count in enumerate(games) if count > 0]

    ppg = [
        safe_float(player.get("points", 0)) / max(1, games[index])
        for index, player in enumerate(players)
    ]
    bonus = [safe_float(player.get("bonus_points", 0)) for player in players]
    win_rate = [
        max(0, safe_int(player.get("wins", 0))) / max(1, games[index])
        for index, player in enumerate(players)
    ]

    # A newcomer must not be treated as a zero-skill player. Use the median
    # of candidates with history as a neutral prior for every missing feature.
    ppg_prior = median_or([ppg[index] for index in known_indexes], 0.0)
    bonus_prior = median_or([bonus[index] for index in known_indexes], 0.0)
    win_rate_prior = median_or([win_rate[index] for index in known_indexes], 0.0)

    rank_values: list[float | None] = []
    for index, player in enumerate(players):
        rank = safe_int(player.get("rank_position"), 0)
        rank_values.append(1 / rank if rank > 0 and games[index] > 0 else None)
    rank_prior = median_or([value for value in rank_values if value is not None], 0.5)

    for index, count in enumerate(games):
        if count == 0:
            ppg[index] = ppg_prior
            bonus[index] = bonus_prior
            win_rate[index] = win_rate_prior
            rank_values[index] = rank_prior
        elif rank_values[index] is None:
            rank_values[index] = rank_prior

    rank_signal = [float(value) for value in rank_values]

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
