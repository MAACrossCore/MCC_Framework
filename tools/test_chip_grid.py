import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from chip_grid import TEMPLATE, locate_rows, row_slots


class GridTests(unittest.TestCase):
    def image(self, centers):
        im = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for y, count in centers:
            for x in (169, 421, 673, 925, 1177, 1429)[:count]:
                im[y + 64:y + 91, x - 91:x - 64] = TEMPLATE[:, :, None].astype(np.uint8)
        return im

    def test_shifted_rows(self):
        rows = locate_rows(self.image([(241, 6), (488, 6), (735, 6)]))
        self.assertEqual([r[0][1] for r in rows], [241, 488, 735])
        self.assertEqual(len(rows[0]), 6)

    def test_short_last_row(self):
        rows = locate_rows(self.image([(271, 6), (518, 2)]))
        self.assertEqual(len(row_slots(rows, 7, 2, 1)), 2)
        with self.assertRaises(ValueError):
            row_slots(rows, 7, 3, 1)

    def test_blank_does_not_click(self):
        self.assertEqual(locate_rows(np.zeros((1080, 1920, 3), dtype=np.uint8)), [])


if __name__ == '__main__':
    unittest.main()
