# Тесты распределителя бюджета meta_ads: python -m unittest discover tests
import unittest

from meta_ads.budget import CampaignStats, ad_verdict, allocate

RULES = {"min_impressions": 2000, "min_ctr": 0.004, "kill_cpa_multiplier": 2.5,
         "fatigue_frequency": 3.5, "max_active_ads": 5}


def camp(key, budget, cpa_target, spend, results, days=7, learning=False):
    return CampaignStats(key, budget, cpa_target, [(spend, results)] * days, learning)


class AllocateTest(unittest.TestCase):
    def test_money_moves_to_cheaper_results(self):
        plan = allocate([camp("good", 10, 0.2, 10, 100), camp("bad", 10, 0.2, 10, 20)],
                        total=20, min_b=4, max_b=20)
        self.assertGreater(plan["good"][0], 10)
        self.assertLess(plan["bad"][0], 10)

    def test_daily_step_is_limited(self):
        plan = allocate([camp("good", 10, 0.2, 10, 1000), camp("bad", 10, 0.2, 10, 1)],
                        total=40, min_b=4, max_b=30, max_change=0.2)
        self.assertLessEqual(plan["good"][0], 12.0)
        self.assertGreaterEqual(plan["bad"][0], 8.0)

    def test_total_never_exceeded(self):
        cs = [camp(f"c{i}", 10, 0.2, 10, 200) for i in range(4)]
        plan = allocate(cs, total=30, min_b=4, max_b=20)
        self.assertLessEqual(sum(v[0] for v in plan.values()), 30.0001)

    def test_learning_campaign_frozen(self):
        plan = allocate([camp("new", 10, 0.2, 10, 0, learning=True), camp("old", 10, 0.2, 10, 100)],
                        total=20, min_b=4, max_b=20)
        self.assertEqual(plan["new"][0], 10)

    def test_little_data_stays_near_current(self):
        # 1 результат за неделю — шум, а не сигнал: бюджет почти не двигается.
        plan = allocate([camp("a", 10, 0.2, 0.05, 0, days=1), camp("b", 10, 0.2, 0.05, 0, days=1)],
                        total=20, min_b=4, max_b=20)
        self.assertAlmostEqual(plan["a"][0], 10, delta=0.5)

    def test_underspending_campaign_not_raised(self):
        plan = allocate([camp("slow", 10, 0.2, 2, 100), camp("x", 10, 0.2, 10, 10)],
                        total=20, min_b=4, max_b=20)
        self.assertLessEqual(plan["slow"][0], 10)


class AdVerdictTest(unittest.TestCase):
    def test_low_ctr_paused(self):
        v, _ = ad_verdict({"impressions": 5000, "inline_link_clicks": 5, "spend": 3}, RULES, 0.2, 5)
        self.assertEqual(v, "pause")

    def test_expensive_results_paused(self):
        v, _ = ad_verdict({"impressions": 1000, "inline_link_clicks": 50, "spend": 2}, RULES, 0.2, 1)
        self.assertEqual(v, "pause")

    def test_fatigue_refresh(self):
        v, _ = ad_verdict({"impressions": 3000, "inline_link_clicks": 60, "spend": 1, "frequency": 4.2},
                          RULES, 0.2, 10)
        self.assertEqual(v, "refresh")

    def test_healthy_ad_kept(self):
        v, _ = ad_verdict({"impressions": 3000, "inline_link_clicks": 60, "spend": 1, "frequency": 1.5},
                          RULES, 0.2, 10)
        self.assertIsNone(v)


if __name__ == "__main__":
    unittest.main()
