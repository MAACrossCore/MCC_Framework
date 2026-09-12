# -*- coding: utf-8 -*-
"""Task-independent CF3 chip-plan persistence and share-code service."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

from chip_domain import validate_filter_plan


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAN_FILE = PROJECT_ROOT / "config" / "chip_filter_plan.json"
DEFAULT_PLAN_FILES = (
    PROJECT_ROOT / "default" / "chip_filter_plan.json",
    PROJECT_ROOT / "assets" / "default" / "chip_filter_plan.json",
)
CODE_PREFIX = "LAA-CF3"
MAX_CODE_LENGTH = 65536
MAX_JSON_BYTES = 131072


class PlanCodeError(ValueError):
    pass


def plan_file_path(path=None):
    if path:
        return Path(path)
    configured = os.environ.get("LAA_CHIP_PLAN_FILE")
    return Path(configured) if configured else PLAN_FILE


def _canonical(plan):
    validate_filter_plan(plan)
    return json.dumps(
        plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def load_filter_plan(path=None):
    requested = plan_file_path(path)
    source = requested if requested.exists() else next(
        (candidate for candidate in DEFAULT_PLAN_FILES if candidate.exists()), requested
    )
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    validate_filter_plan(data)
    return data


def save_filter_plan(plan, path=None):
    raw = _canonical(plan)
    target = plan_file_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(raw + b"\n")
    temporary.replace(target)
    return target


def encode_plan_code(plan):
    packed = zlib.compress(_canonical(plan), level=9)
    checksum = hashlib.sha256(packed).hexdigest()[:12]
    payload = base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
    return f"{CODE_PREFIX}-{checksum}-{payload}"


def decode_plan_code(code):
    value = "".join(str(code or "").split())
    if len(value) > MAX_CODE_LENGTH:
        raise PlanCodeError("方案码过长")
    prefix = CODE_PREFIX + "-"
    if not value.startswith(prefix):
        raise PlanCodeError("仅支持CF3芯片筛选方案码")
    try:
        checksum, payload = value[len(prefix):].split("-", 1)
        packed = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    except Exception as exc:
        raise PlanCodeError("方案码内容损坏") from exc
    if hashlib.sha256(packed).hexdigest()[:12] != checksum:
        raise PlanCodeError("方案码校验失败")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(packed, MAX_JSON_BYTES + 1)
        raw += decompressor.flush()
        if len(raw) > MAX_JSON_BYTES or decompressor.unconsumed_tail:
            raise PlanCodeError("方案数据过大")
        plan = json.loads(raw.decode("utf-8"))
        validate_filter_plan(plan)
        return plan
    except PlanCodeError:
        raise
    except Exception as exc:
        raise PlanCodeError("方案码无法解析") from exc
