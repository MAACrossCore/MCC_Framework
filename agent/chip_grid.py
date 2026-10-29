"""Locate warehouse card borders without OCR or chip-content recognition."""
from pathlib import Path
import numpy as np

COLUMNS = (169, 421, 673, 925, 1177, 1429)
TEMPLATE = np.load(Path(__file__).with_name('chip_grid_corner.npy'))


def locate_rows(image):
    height, width = image.shape[:2]
    ys = np.minimum((np.arange(1080) * height / 1080).astype(int), height - 1)
    xs = np.minimum((np.arange(1920) * width / 1920).astype(int), width - 1)
    gray = image[ys[:, None], xs[None, :], :3].mean(axis=2).astype(np.float32)
    template = TEMPLATE.astype(np.float32)
    points = []
    for center in COLUMNS:
        left = center - 91
        errors = np.zeros((827, 25), dtype=np.float32)
        for ty in range(0, 27, 4):
            for tx in range(0, 27, 4):
                errors += np.abs(gray[145 + ty:972 + ty, left - 12 + tx:left + 13 + tx] - template[ty, tx])
        errors /= 49
        while errors.min() < 15:
            y, x = np.unravel_index(errors.argmin(), errors.shape)
            cy = int(y + 145 - 64)
            if 240 <= cy <= 900:
                points.append((int(left - 12 + x + 91), cy))
            errors[max(0, y - 70):y + 71] = np.inf
    groups = []
    for point in sorted(points, key=lambda p: p[1]):
        if not groups or abs(point[1] - np.median([p[1] for p in groups[-1]])) > 12:
            groups.append([])
        groups[-1].append(point)
    return [sorted(group) for group in groups]


def row_slots(rows, start_index, count, row=0):
    if row >= len(rows) or len(rows[row]) < count:
        raise ValueError('Cannot locate all requested warehouse chip cards')
    return [{'index': start_index + i, 'point': tuple(point)}
            for i, point in enumerate(rows[row][:count])]
