"""Scale coordinates recorded at 1920x1080 to the controller viewport."""

REFERENCE_SIZE = (1920, 1080)


def image_size(image):
    try:
        height, width = image.shape[:2]
        return int(width), int(height)
    except Exception:
        return REFERENCE_SIZE


def scale_point(size, point):
    width, height = size
    x = round(point[0] * width / REFERENCE_SIZE[0])
    y = round(point[1] * height / REFERENCE_SIZE[1])
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))


def scale_roi(image, roi):
    width, height = image_size(image)
    x, y, roi_width, roi_height = roi
    if roi_width == 0 or roi_height == 0:
        return [0, 0, 0, 0]
    left = max(0, min(width - 1, round(x * width / REFERENCE_SIZE[0])))
    top = max(0, min(height - 1, round(y * height / REFERENCE_SIZE[1])))
    right = max(left + 1, min(width, round((x + roi_width) * width / REFERENCE_SIZE[0])))
    bottom = max(top + 1, min(height, round((y + roi_height) * height / REFERENCE_SIZE[1])))
    return [left, top, right - left, bottom - top]


def scale_swipe(size, swipe):
    start = scale_point(size, swipe[:2])
    end = scale_point(size, swipe[2:4])
    return (*start, *end, swipe[4])
