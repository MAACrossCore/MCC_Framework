import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from chip_filter_flow import ChipFilterFlow, DETAIL_CLOSE_BLANK


class CutoffTests(unittest.TestCase):
    def test_four_star_stops_before_reading_or_toggling(self):
        engine = ChipFilterFlow()
        engine._click = Mock()
        engine._sleep = Mock()
        engine._shot = Mock(return_value=None)
        engine._is_detail_open = Mock(return_value=True)
        engine._page_text = Mock(return_value='R4钝化控制芯片')
        engine._read_detail = Mock(side_effect=AssertionError('Must not read four-star skills'))
        engine._read_lock_state = Mock(side_effect=AssertionError('Must not toggle four-star lock'))
        summary = {'attempted': 0}
        result = engine._process_slot(None, {'point': (169, 271), 'index': 1}, {}, [], summary,
                                      stop_at_four_star=True)
        self.assertEqual(result, 'rarity_cutoff')
        self.assertEqual(summary['rarity_cutoff'], 4)
        self.assertEqual(engine._click.call_count, 2)
        self.assertEqual(engine._click.call_args.args[1], DETAIL_CLOSE_BLANK)


if __name__ == '__main__':
    unittest.main()
