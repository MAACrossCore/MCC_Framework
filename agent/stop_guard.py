# -*- coding: utf-8 -*-
"""Shared cancellation checks for custom actions running through MFA."""


class ActionStopped(RuntimeError):
    pass


def _state_value(tasker, name, default):
    try:
        value = getattr(tasker, name, default)
        return bool(value() if callable(value) else value)
    except Exception:
        return default


def cancelled(context):
    tasker = context.tasker
    return _state_value(tasker, "stopping", False) or not _state_value(tasker, "running", True)


def ensure_running(context):
    if cancelled(context):
        raise ActionStopped("MFA task has been stopped")
