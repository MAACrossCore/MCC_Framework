"""Loading an interrupted run must not erase its saved roster."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import numpy as np
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import jdc_reset_state as state


class ResumeStateTests(unittest.TestCase):
    def test_formation_view_uses_selected_tab_at_both_resolutions(self):
        for width, height in ((1280, 720), (1920, 1080)):
            for view, x in (("flat", 500), ("perspective", 610)):
                image = np.zeros((height, width, 3), dtype=np.uint8)
                image[round(650 * height / 720):round(658 * height / 720),
                      round(x * width / 1280):round((x + 85) * width / 1280)] = 220
                self.assertEqual(state.formation_view(image), view)
            self.assertIsNone(state.formation_view(np.zeros_like(image)))

    def test_saved_progress_is_loaded_not_reset(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        with patch.object(state.os.path, "exists", return_value=True), \
             patch.object(state.jdc, "load_jdc_state", return_value=True) as load, \
             patch.object(state.jdc, "reset_jdc_state") as reset:
            self.assertTrue(state.JdcLoadState().run(context, None))
            load.assert_called_once()
            reset.assert_not_called()

    def test_corrupt_progress_is_not_silently_deleted(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        with patch.object(state.os.path, "exists", return_value=True), \
             patch.object(state.jdc, "load_jdc_state", return_value=False), \
             patch.object(state.jdc, "reset_jdc_state") as reset:
            self.assertFalse(state.JdcLoadState().run(context, None))
            reset.assert_not_called()

    def test_missing_progress_starts_clean(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        with patch.object(state.os.path, "exists", return_value=False), \
             patch.object(state.jdc, "reset_jdc_state") as reset:
            self.assertTrue(state.JdcLoadState().run(context, None))
            reset.assert_called_once()

    def test_stopping_does_not_touch_progress(self):
        with patch.object(state.jdc, "load_jdc_state") as load:
            self.assertFalse(state.JdcLoadState().run(
                SimpleNamespace(tasker=SimpleNamespace(stopping=True)), None))
            load.assert_not_called()

    def test_only_completed_formation_skips_rebuild(self):
        for phase, count, expected in (("route", 5, True), ("battle", 5, True),
                                      ("build_team", 5, False), ("select_extra", 5, False),
                                      ("select", 0, False)):
            with patch.object(state.jdc, "jdc_phase", phase), \
                 patch.object(state.jdc, "jdc_final_team", [None] * count):
                self.assertEqual(bool(state.JdcTeamReady().analyze(None, None)), expected)


if __name__ == "__main__":
    unittest.main()
