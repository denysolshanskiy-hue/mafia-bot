"""CHRONOS closed-economy rules and deterministic balance simulator.

CR is a soft cosmetic currency, EX is a prediction reward currency, and XP
only tracks progression. None of them can be purchased, transferred or cashed
out. All reward grants are recorded in the append-only ledger.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Iterable

ECONOMY_VERSION = "1.0"

DEFAULT_ECONOMY = {
    "status": "draft",
    "cr_per_confirmed_game": 5,
    "xp_per_confirmed_game": 10,
    "cr_per_attended_evening": 10,
    "xp_per_attended_evening": 5,
    "minigame_first_clear_xp": 20,
    "minigame_repeat_xp": 5,
    "minigame_repeat_cap": 10,
    "prediction_expected_reward_ex": 5,
    "prediction_min_reward_ex": 5,
    "prediction_max_reward_ex": 100,
    "prediction_max_forecasts_per_event": 3,
    "prediction_ex_season_cap": 500,
    "prediction_store_unlock_after": 6,
    "activity_score": {
        "status": "draft",
        "weights": {"attendance": 80, "app": 15, "minigame": 5},
        "app_actions_cap": 13,
        "minigame_completions_cap": 5,
    },
    "season_activity_bonus_uah": 500,
}

CR_CATALOG = {
    "CR_NEON_FRAME": 80,
    "CR_CYAN_AURA": 120,
    "CR_SIGNAL_GLASSES": 100,
    "CR_CHRONO_CHAIN": 140,
    "CR_OPERATOR_GLOVE": 160,
    "CR_HOLO_FRAME": 180,
    "CR_PULSE_AURA": 220,
    "CR_CHROME_VISOR": 260,
    "CR_TIMEKEEPER_FRAME": 320,
}

EX_CATALOG = {
    "GOLDEN_CHIP": 25,
    "LUCKY_DICE": 40,
    "HIGH_ROLLER": 55,
    "MONEY_VISION": 80,
    "ALL_IN": 90,
    "BIG_STAKE": 120,
    "CASH_BLASTER": 160,
    "HOUSE_OWNER": 180,
    "JACKPOT_AURA": 220,
    "MONEY_RAIN": 250,
    "THE_WHALE": 250,
}

INTERMEDIATE_FINAL_PRIZES = (1000, 700, 300)
MAIN_FINAL_PRIZES = (3000, 2000, 1000)
INTERMEDIATE_FINALS = 3
ACTIVITY_BONUS_POOL_UAH = 500


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def minigame_xp_reward(
    completed_sessions: int,
    first_clear_types: int | None = None,
    first_clear_xp: int = 20,
    repeat_xp: int = 5,
    repeat_cap: int = 10,
) -> int:
    """First clear is paid once for each of the two distinct mini-game types.

    If first_clear_types is omitted, the simulator assumes the player has
    completed both types whenever there are at least two sessions. Callers with
    actual data should pass the number of distinct first clears (0, 1 or 2).
    """
    count = max(0, int(completed_sessions))
    if first_clear_types is None:
        first_clears = min(2, count)
    else:
        first_clears = min(2, count, max(0, int(first_clear_types)))
    repeats = min(max(0, count - first_clears), max(0, int(repeat_cap)))
    return first_clears * int(first_clear_xp) + repeats * int(repeat_xp)


def player_currency_income(
    confirmed_games: int,
    attended_evenings: int,
    completed_minigames: int,
    predictions_submitted: int = 0,
    prediction_expected_reward: int = 5,
    prediction_season_cap: int = 500,
    minigame_first_clear_types: int | None = None,
    economy_settings: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Calculate season income; forecast EX is an expected value, not a guarantee.

    Rates come from the same versioned economy settings used by the ledger
    reconciler. Explicit prediction arguments remain available for scenario tests.
    """
    settings = dict(DEFAULT_ECONOMY)
    if economy_settings:
        settings.update(economy_settings)

    games = max(0, int(confirmed_games))
    evenings = max(0, int(attended_evenings))
    predictions = max(0, int(predictions_submitted))
    cr = (
        games * max(0, int(settings["cr_per_confirmed_game"]))
        + evenings * max(0, int(settings["cr_per_attended_evening"]))
    )
    xp = (
        games * max(0, int(settings["xp_per_confirmed_game"]))
        + evenings * max(0, int(settings["xp_per_attended_evening"]))
        + minigame_xp_reward(
            completed_minigames,
            first_clear_types=minigame_first_clear_types,
            first_clear_xp=int(settings["minigame_first_clear_xp"]),
            repeat_xp=int(settings["minigame_repeat_xp"]),
            repeat_cap=int(settings["minigame_repeat_cap"]),
        )
    )
    ex_expected = min(
        max(0, int(prediction_season_cap)),
        predictions * max(0, int(prediction_expected_reward)),
    )
    return {"CR": cr, "EX_expected": ex_expected, "XP": xp}


def prediction_reward_ex(
    probability: float,
    expected_reward: int = 5,
    minimum: int = 5,
    maximum: int = 100,
) -> int:
    """Probability-weighted, no-stake forecast reward.

    Within the un-clamped range: probability * reward ~= expected_reward.
    """
    p = _decimal(probability)
    if p <= 0 or p > 1:
        raise ValueError("probability must be in (0, 1]")
    if minimum < 0 or maximum < minimum:
        raise ValueError("invalid reward bounds")
    raw = (_decimal(expected_reward) / p).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(int(minimum), min(int(maximum), int(raw)))


def calculate_activity_score(
    *,
    attended_slots: int,
    eligible_slots: int,
    verified_app_actions: int,
    completed_minigames: int,
    weights: dict[str, int] | None = None,
    app_actions_cap: int = 13,
    minigame_completions_cap: int = 5,
) -> dict[str, float]:
    """Cumulative 80/15/5 score; only invited finals enter the attendance denominator."""
    weights = weights or {"attendance": 80, "app": 15, "minigame": 5}
    keys = ("attendance", "app", "minigame")
    normalized = {key: int(weights.get(key, 0)) for key in keys}
    if any(value < 0 for value in normalized.values()) or sum(normalized.values()) != 100:
        raise ValueError("activity score weights must be non-negative and sum to 100")

    eligible = max(0, int(eligible_slots))
    attended = max(0, min(int(attended_slots), eligible))
    app_cap = max(1, int(app_actions_cap))
    game_cap = max(1, int(minigame_completions_cap))
    app_count = max(0, int(verified_app_actions))
    game_count = max(0, int(completed_minigames))

    attendance_ratio = attended / eligible if eligible else 0.0
    attendance_points = normalized["attendance"] * attendance_ratio
    app_points = normalized["app"] * min(1.0, app_count / app_cap)
    minigame_points = normalized["minigame"] * min(1.0, game_count / game_cap)
    score = min(100.0, attendance_points + app_points + minigame_points)
    return {
        "attendance_points": round(attendance_points, 4),
        "app_points": round(app_points, 4),
        "minigame_points": round(minigame_points, 4),
        "activity_score": round(score, 4),
        "activity_coefficient": round(score / 100.0, 6),
    }


def allocate_activity_bonus(
    participants: Iterable[dict[str, Any]],
    pool_uah: int = ACTIVITY_BONUS_POOL_UAH,
) -> dict[int, int]:
    """Largest-remainder allocation: integer UAH shares add up exactly to the pool."""
    eligible = [
        {
            "user_id": int(row["user_id"]),
            "score": max(Decimal("0"), _decimal(row["activity_score"])),
            "rank": int(row.get("rank_position", 999999)),
        }
        for row in participants
    ]
    pool = max(0, int(pool_uah))
    if not eligible or pool == 0:
        return {}
    total_weight = sum((row["score"] for row in eligible), Decimal("0"))
    if total_weight <= 0:
        raise ValueError("cannot allocate a bonus when all activity scores are zero")

    allocations: dict[int, int] = {}
    remainders: list[tuple[Decimal, int, int]] = []
    for row in eligible:
        exact = _decimal(pool) * row["score"] / total_weight
        floor_value = int(exact.to_integral_value(rounding=ROUND_FLOOR))
        allocations[row["user_id"]] = floor_value
        remainders.append((exact - floor_value, row["rank"], row["user_id"]))

    leftover = pool - sum(allocations.values())
    remainders.sort(key=lambda item: (-item[0], item[1], item[2]))
    for _, _, user_id in remainders[:leftover]:
        allocations[user_id] += 1
    if sum(allocations.values()) != pool:
        raise ArithmeticError("bonus allocation does not reconcile to the pool")
    return allocations


def qualification_games_required(conducted_games: int, participation_ratio: float = 0.30) -> int:
    """Minimum distinct core games a player must appear in to qualify."""
    import math

    games = max(0, int(conducted_games))
    ratio = _decimal(participation_ratio)
    if ratio < 0 or ratio > 1:
        raise ValueError("participation_ratio must be between 0 and 1")
    return int(math.ceil(Decimal(games) * ratio))


def season_prize_budget(
    intermediate_count: int = INTERMEDIATE_FINALS,
    activity_bonus: int = ACTIVITY_BONUS_POOL_UAH,
) -> dict[str, int]:
    intermediate_total = max(0, int(intermediate_count)) * sum(INTERMEDIATE_FINAL_PRIZES)
    main_total = sum(MAIN_FINAL_PRIZES)
    bonus = max(0, int(activity_bonus))
    return {
        "intermediate_finals": intermediate_total,
        "main_final": main_total,
        "activity_bonus": bonus,
        "total_commitment": intermediate_total + main_total + bonus,
    }


def _catalog_affordability(balance: int, prices: dict[str, int]) -> dict[str, Any]:
    affordable = [price for price in prices.values() if price <= balance]
    # 0/1 knapsack: unique item codes can only be purchased once.
    dp: list[tuple[int, int, tuple[str, ...]]] = [(0, 0, ()) for _ in range(max(0, balance) + 1)]
    for code, price in prices.items():
        if price < 0:
            continue
        for available in range(max(0, balance), price - 1, -1):
            previous = dp[available - price]
            candidate = (previous[0] + 1, previous[1] + price, previous[2] + (code,))
            current = dp[available]
            if candidate[0] > current[0] or (candidate[0] == current[0] and candidate[1] > current[1]):
                dp[available] = candidate
    best = dp[max(0, balance)]
    return {
        "minimum_item_price": min(prices.values()),
        "maximum_individually_affordable_price": max(affordable) if affordable else 0,
        "items_individually_affordable": len(affordable),
        "max_unique_items_buyable": best[0],
        "max_unique_items_spend": best[1],
        "remaining_after_max_item_count": max(0, balance - best[1]),
        "max_item_count_bundle": list(best[2]),
    }


def simulate_economy() -> dict[str, Any]:
    """Deterministic cohort model using 69 core games and 13 possible event slots."""
    cohorts = {
        "minimum_qualifier": {
            "games": 21, "attended": 5, "eligible": 9,
            "app_actions": 6, "minigames": 3, "predictions": 6,
        },
        "regular_player": {
            "games": 35, "attended": 7, "eligible": 9,
            "app_actions": 10, "minigames": 5, "predictions": 18,
        },
        "active_top10": {
            "games": 69, "attended": 12, "eligible": 12,
            "app_actions": 12, "minigames": 5, "predictions": 36,
        },
        "active_top10_with_main_final": {
            "games": 79, "attended": 13, "eligible": 13,
            "app_actions": 13, "minigames": 5, "predictions": 39,
        },
        "top10_skips_one_final": {
            "games": 71, "attended": 12, "eligible": 13,
            "app_actions": 13, "minigames": 5, "predictions": 36,
        },
    }
    report: dict[str, Any] = {}
    for name, profile in cohorts.items():
        income = player_currency_income(
            profile["games"], profile["attended"], profile["minigames"],
            profile["predictions"],
        )
        score = calculate_activity_score(
            attended_slots=profile["attended"],
            eligible_slots=profile["eligible"],
            verified_app_actions=profile["app_actions"],
            completed_minigames=profile["minigames"],
        )
        report[name] = {
            **profile,
            **income,
            **score,
            "cr_catalog": _catalog_affordability(income["CR"], CR_CATALOG),
            "ex_catalog": _catalog_affordability(income["EX_expected"], EX_CATALOG),
        }

    # Before Main Final: 69 core games over 12 progression evenings.
    core_maximum_income = player_currency_income(69, 12, 12, 36)
    # Top-10 player may additionally play 10 Main Final games. They earn CR/XP,
    # but are deliberately excluded from the 690 core synchronization target.
    top10_with_main_final_income = player_currency_income(79, 13, 12, 39)
    prize_budget = season_prize_budget()
    return {
        "version": ECONOMY_VERSION,
        "cohorts": report,
        "core_season_player_max": core_maximum_income,
        "top10_with_main_final_max": top10_with_main_final_income,
        "cr_catalog_total_sink_capacity": sum(CR_CATALOG.values()),
        "ex_catalog_total_sink_capacity": sum(EX_CATALOG.values()),
        "cr_catalog_prices": CR_CATALOG,
        "ex_catalog_prices": EX_CATALOG,
        "prize_budget": prize_budget,
        "prediction_expectation": {
            "expected_ex_per_forecast": 5,
            "max_forecasts_per_event": 3,
            "max_forecasts_across_13_events": 39,
            "expected_ex_across_13_events_before_cap": 195,
            "hard_season_cap_ex": 500,
            "store_unlock_after_forecasts": 6,
        },
    }
