import unittest

try:
    from modules.chronos_economy import (
        ACTIVITY_BONUS_POOL_UAH,
        CR_CATALOG,
        EX_CATALOG,
        INTERMEDIATE_FINAL_PRIZES,
        MAIN_FINAL_PRIZES,
        allocate_activity_bonus,
        calculate_activity_score,
        minigame_xp_reward,
        player_currency_income,
        prediction_reward_ex,
        qualification_games_required,
        season_prize_budget,
        simulate_economy,
    )
except ModuleNotFoundError:
    from mafia_bot.modules.chronos_economy import (
        ACTIVITY_BONUS_POOL_UAH,
        CR_CATALOG,
        EX_CATALOG,
        INTERMEDIATE_FINAL_PRIZES,
        MAIN_FINAL_PRIZES,
        allocate_activity_bonus,
        calculate_activity_score,
        minigame_xp_reward,
        player_currency_income,
        prediction_reward_ex,
        qualification_games_required,
        season_prize_budget,
        simulate_economy,
    )



class ChronosEconomyTests(unittest.TestCase):
    def test_currency_sources_for_player_archetypes(self):
        minimum = player_currency_income(21, 5, 3, 6)
        regular = player_currency_income(40, 7, 5, 18)
        active = player_currency_income(69, 13, 5, 39)
        active_with_main_final = player_currency_income(79, 13, 5, 39)
        self.assertEqual(minimum, {"CR": 155, "EX_expected": 30, "XP": 280})
        self.assertEqual(regular, {"CR": 270, "EX_expected": 90, "XP": 490})
        self.assertEqual(active, {"CR": 475, "EX_expected": 195, "XP": 810})
        self.assertEqual(active_with_main_final, {"CR": 525, "EX_expected": 195, "XP": 910})

    def test_minigame_xp_is_capped(self):
        self.assertEqual(minigame_xp_reward(0), 0)
        self.assertEqual(minigame_xp_reward(1), 20)
        self.assertEqual(minigame_xp_reward(2), 40)
        self.assertEqual(minigame_xp_reward(3), 45)
        self.assertEqual(minigame_xp_reward(12), 90)
        self.assertEqual(minigame_xp_reward(50), 90)

    def test_prediction_reward_has_constant_expected_value_in_normal_range(self):
        for probability in (0.05, 0.10, 0.125, 0.20):
            reward = prediction_reward_ex(probability)
            self.assertAlmostEqual(probability * reward, 5, delta=0.06)
        self.assertEqual(prediction_reward_ex(0.05), 100)
        self.assertEqual(prediction_reward_ex(0.10), 50)
        self.assertEqual(prediction_reward_ex(0.20), 25)

    def test_prediction_reward_rejects_invalid_probability(self):
        for probability in (0, -0.1, 1.01):
            with self.subTest(probability=probability):
                with self.assertRaises(ValueError):
                    prediction_reward_ex(probability)

    def test_ex_faucet_is_capped_in_the_season_model(self):
        income = player_currency_income(69, 13, 12, 1000)
        self.assertEqual(income["EX_expected"], 500)

    def test_activity_score_weights_and_cumulative_coefficient(self):
        full = calculate_activity_score(
            attended_slots=13, eligible_slots=13,
            verified_app_actions=15, completed_minigames=5,
        )
        skipped = calculate_activity_score(
            attended_slots=12, eligible_slots=13,
            verified_app_actions=15, completed_minigames=5,
        )
        non_top10 = calculate_activity_score(
            attended_slots=7, eligible_slots=9,
            verified_app_actions=10, completed_minigames=5,
        )
        self.assertEqual(full["activity_score"], 100)
        self.assertEqual(full["activity_coefficient"], 1)
        self.assertAlmostEqual(skipped["activity_score"], 93.8462, places=3)
        self.assertLess(skipped["activity_coefficient"], full["activity_coefficient"])
        self.assertAlmostEqual(non_top10["activity_score"], 78.7607, places=3)

    def test_activity_score_requires_weights_to_sum_to_100(self):
        with self.assertRaises(ValueError):
            calculate_activity_score(
                attended_slots=1, eligible_slots=1,
                verified_app_actions=1, completed_minigames=1,
                weights={"attendance": 80, "app": 10, "minigame": 5},
            )

    def test_exact_30_percent_qualification_threshold(self):
        self.assertEqual(qualification_games_required(69), 21)
        self.assertEqual(qualification_games_required(10), 3)
        self.assertEqual(qualification_games_required(0), 0)
        self.assertEqual(qualification_games_required(69, 0.5), 35)

    def test_activity_bonus_uses_largest_remainder_and_reconciles(self):
        players = [
            {"user_id": user_id, "rank_position": user_id, "activity_score": score}
            for user_id, score in enumerate((100, 98, 96, 94, 92, 90, 88, 86, 84, 82), start=1)
        ]
        allocations = allocate_activity_bonus(players)
        self.assertEqual(sum(allocations.values()), 500)
        self.assertEqual(len(allocations), 10)
        self.assertGreaterEqual(allocations[1], allocations[10])

    def test_bonus_pool_fails_if_every_score_is_zero(self):
        with self.assertRaises(ValueError):
            allocate_activity_bonus([{"user_id": 1, "activity_score": 0}])

    def test_fixed_prize_budget_reconciles(self):
        budget = season_prize_budget()
        self.assertEqual(sum(INTERMEDIATE_FINAL_PRIZES), 2000)
        self.assertEqual(sum(MAIN_FINAL_PRIZES), 6000)
        self.assertEqual(budget["intermediate_finals"], 6000)
        self.assertEqual(budget["main_final"], 6000)
        self.assertEqual(budget["activity_bonus"], ACTIVITY_BONUS_POOL_UAH)
        self.assertEqual(budget["total_commitment"], 12500)

    def test_catalog_prices_are_affordable_at_expected_income(self):
        self.assertEqual(min(CR_CATALOG.values()), 80)
        self.assertEqual(max(CR_CATALOG.values()), 320)
        self.assertEqual(min(EX_CATALOG.values()), 25)
        self.assertEqual(max(EX_CATALOG.values()), 250)
        report = simulate_economy()["cohorts"]
        self.assertGreaterEqual(report["minimum_qualifier"]["CR"], min(CR_CATALOG.values()))
        self.assertGreaterEqual(report["minimum_qualifier"]["EX_expected"], min(EX_CATALOG.values()))
        self.assertGreater(report["regular_player"]["CR"], min(CR_CATALOG.values()))
        self.assertGreater(report["active_top10"]["CR"], report["regular_player"]["CR"])

    def test_deterministic_simulator_reconciles_sources_and_sinks(self):
        report = simulate_economy()
        self.assertEqual(report["core_season_player_max"]["CR"], 475)
        self.assertEqual(report["core_season_player_max"]["EX_expected"], 195)
        self.assertEqual(report["top10_with_main_final_max"]["CR"], 525)
        self.assertEqual(report["top10_with_main_final_max"]["XP"], 945)
        self.assertEqual(report["prize_budget"]["total_commitment"], 12500)
        self.assertEqual(report["cr_catalog_total_sink_capacity"], sum(CR_CATALOG.values()))
        self.assertEqual(report["ex_catalog_total_sink_capacity"], sum(EX_CATALOG.values()))


if __name__ == "__main__":
    unittest.main()
