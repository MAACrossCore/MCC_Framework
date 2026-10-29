"""Regression tests for the 30-run, default-maximum sweep selector."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

import activity_pipeline as activity
import mainstory_pipeline as mainstory
from daily_chip_rewards import parse_sweep_count, parse_sweep_selector_count
from daily_stamina import plan_consume_all
from test_daily_stamina_dialog import _run, BASE


class SweepUpdateTests(unittest.TestCase):
    def tearDown(self):
        activity._SESSION.clear()
        mainstory._SESSION.clear()

    def test_consume_all_mainstory_999_is_30_then_11(self):
        steps, summary = plan_consume_all(0, 24, 999)
        self.assertEqual([s["count"] for s in steps], [30, 11])
        self.assertEqual(summary["stamina_left"], 15)
        self.assertEqual(mainstory.plan_batch(mainstory.MODE_CONSUME_ALL, 0, 999), 30)
        self.assertEqual(mainstory.plan_batch(mainstory.MODE_CONSUME_ALL, 0, 279), 11)
        self.assertEqual(mainstory.plan_batch(mainstory.MODE_CONSUME_ALL, 0, 15), 0)

    def test_daily_default_maximum_needs_no_clicks(self):
        ok, recorder, session = _run("set_sweep_count_by_stamina",
            dict(BASE, cost=36, final_stamina=999), [999, 27])
        self.assertTrue(ok)
        self.assertEqual(session["sweep_runs"], 27)
        self.assertEqual(recorder.clicks, [])

    def test_daily_custom_three_reduces_default_thirty(self):
        ok, recorder, _ = _run("set_sweep_count", dict(BASE, cost=24,
            final_stamina=999, batches=[3], batch_index=0), [999, 279, 927])
        self.assertTrue(ok)
        import daily_stamina_pipeline as daily
        self.assertEqual(recorder.clicks, [daily.SWEEP_MINUS_POINT] * 27)

    def test_daily_second_batch_uses_remaining_stamina(self):
        session = dict(BASE, cost=24, final_stamina=999, batches=[30, 11], batch_index=0)
        ok, _, session = _run("advance_batch", session, [])
        self.assertTrue(ok)
        self.assertEqual(session["final_stamina"], 279)
        ok, recorder, session = _run("set_sweep_count_by_stamina", session, [279, 15])
        self.assertTrue(ok)
        self.assertEqual(session["sweep_runs"], 11)
        self.assertEqual(recorder.clicks, [])

    def test_activity_custom_remaining_is_not_reset_after_batch(self):
        activity._SESSION.update(exchange_mode="自定次数", custom_runs=35,
                                 remaining_runs=5, ticket_cost_per_run=2)
        request = SimpleNamespace(wait=lambda: SimpleNamespace(get=lambda: object()))
        context = SimpleNamespace(tasker=SimpleNamespace(controller=SimpleNamespace(
            post_screencap=lambda: request)))
        with patch.object(activity, "ensure_running"), patch.object(activity, "_ocr_digits", return_value=100):
            self.assertTrue(activity.ActivityPipelineAction().run(context,
                SimpleNamespace(custom_action_param=json.dumps({"operation": "read_tickets"}))))
        self.assertEqual(activity._SESSION["remaining_runs"], 5)

    def test_activity_default_thirty_reduces_to_custom_three(self):
        activity._SESSION.update(batch_runs=3, current_tickets=81, ticket_cost_per_run=2)
        request = SimpleNamespace(wait=lambda: SimpleNamespace(get=lambda: object()))
        context = SimpleNamespace(tasker=SimpleNamespace(controller=SimpleNamespace(
            post_screencap=lambda: request)))
        with patch.object(activity, "ensure_running"), patch.object(activity.time, "sleep"), \
             patch.object(activity, "_ocr_digits", side_effect=[21, 75]), \
             patch.object(activity, "_click") as click:
            self.assertTrue(activity.ActivityPipelineAction().run(context,
                SimpleNamespace(custom_action_param=json.dumps({"operation": "adjust_count"}))))
        self.assertEqual(click.call_count, 27)
        self.assertTrue(all(call.args[1:] == activity.SWEEP_MINUS_POINT for call in click.call_args_list))

    def test_chip_settlement_and_selector_accept_thirty(self):
        self.assertEqual(parse_sweep_count("扫荡次数 1/30 扫荡次数 2/30"), 30)
        self.assertEqual(parse_sweep_selector_count("27"), 27)
        self.assertEqual(parse_sweep_selector_count("30"), 30)
        self.assertIsNone(parse_sweep_selector_count("31"))

    def test_mainstory_default_maximum_keeps_next_batch(self):
        mainstory._SESSION.update(stamina=999, stamina_ok=True, remaining=None)
        request = SimpleNamespace(wait=lambda: SimpleNamespace(get=lambda: object()))
        context = SimpleNamespace(tasker=SimpleNamespace(controller=SimpleNamespace(
            post_screencap=lambda: request)))
        with patch.object(mainstory, "_load_settings", return_value={
            "mode": mainstory.MODE_CONSUME_ALL, "runs": 1}), \
             patch.object(mainstory, "_ocr_digits", side_effect=[999, 279]), \
             patch.object(mainstory, "_click") as click:
            self.assertTrue(mainstory.MainStoryAction()._set_count(context, {}))
        self.assertTrue(mainstory._SESSION["more"])
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
