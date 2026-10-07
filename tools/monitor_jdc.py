"""Passive MCC task/log observer. Captures emulator PNGs without game input."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

from capture_screen import capture, png_size, resolve_adb, resolve_serial

ROOT = Path(__file__).resolve().parent.parent
TASK_NAMES = {"角斗场", "决斗场"}
EVENT_RE = re.compile(r"\[msg=([^\]]+)\] \[details=(.*)\]\s*$")
AGENT_EVENT_RE = re.compile(r"\[message=([^\]]+)\] \[details_json=(.*)\] \[trans_arg=")


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def parse_event(line):
    match = EVENT_RE.search(line) or AGENT_EVENT_RE.search(line)
    if not match:
        return None
    try:
        return match.group(1), json.loads(match.group(2))
    except json.JSONDecodeError:
        return None


class LogTail:
    def __init__(self, path, from_end=True):
        self.path = path
        self.offset = path.stat().st_size if from_end and path.exists() else 0
        self.partial = b""

    def read(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size < self.offset:
            self.offset = 0
            self.partial = b""
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read(1024 * 1024)
            self.offset = stream.tell()
        parts = (self.partial + chunk).split(b"\n")
        self.partial = parts.pop()
        return [part.decode("utf-8", "replace").rstrip("\r") for part in parts]


class Recorder:
    def __init__(self, out, limit_mb):
        self.out = out
        self.limit = int(limit_mb * 1024 * 1024)
        self.used = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.active = threading.Event()
        self.urgent = threading.Event()
        self.frames = 0
        self.last_hash = None
        self.last_file = None
        (out / "screens").mkdir(parents=True)
        self.stream = (out / "timeline.jsonl").open("w", encoding="utf-8", buffering=1)

    def record(self, kind, **fields):
        line = json.dumps({"observed_at": timestamp(), "kind": kind, **fields}, ensure_ascii=False) + "\n"
        with self.lock:
            if self.used + len(line.encode("utf-8")) > self.limit:
                self.stop.set()
                return
            self.stream.write(line)
            self.used += len(line.encode("utf-8"))

    def frame(self, data, started, reason):
        digest = hashlib.sha256(data).hexdigest()
        with self.lock:
            if digest != self.last_hash:
                if self.used + len(data) > self.limit:
                    self.stop.set()
                    return
                self.frames += 1
                self.last_file = "screens/%06d.png" % self.frames
                (self.out / self.last_file).write_bytes(data)
                self.used += len(data)
                self.last_hash = digest
            file = self.last_file
        self.record("screenshot", file=file, capture_started_at=started,
                    size=png_size(data), reason=reason)


def capture_loop(recorder, adb, serial, interval):
    last = 0.0
    while not recorder.stop.is_set():
        recorder.urgent.wait(0.1)
        urgent = recorder.urgent.is_set()
        elapsed = time.monotonic() - last
        if not recorder.active.is_set() and not urgent:
            continue
        if elapsed < (0.4 if urgent else interval):
            continue
        recorder.urgent.clear()
        started = timestamp()
        try:
            data = capture(adb, serial, timeout=8)
            if png_size(data) is None:
                raise ValueError("Invalid screenshot PNG")
            recorder.frame(data, started, "action" if urgent else "periodic")
        except (Exception, SystemExit) as exc:
            recorder.record("capture_error", message=str(exc))
        last = time.monotonic()


def existing_task(runtime):
    path = runtime / "debug" / "maafw.log"
    if not path.exists():
        return False
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 4 * 1024 * 1024))
        lines = stream.read().decode("utf-8", "replace").splitlines()
    active = False
    for line in lines:
        event = parse_event(line)
        if event:
            msg, details = event
            if msg == "Tasker.Task.Starting" and details.get("entry") in TASK_NAMES:
                active = True
            elif msg in {"Tasker.Task.Succeeded", "Tasker.Task.Failed", "Tasker.Task.Stopped"}:
                active = False
    return active


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=ROOT / "install")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--adb")
    parser.add_argument("--serial")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-mb", type=int, default=500)
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--capture-now", action="store_true", help="Capture immediately if task-start logging was missed")
    parser.add_argument("--keep-listening", action="store_true", help="Opt in to monitoring more than one task run")
    args = parser.parse_args(argv)
    out = (args.out or ROOT / "debug" / "jdc-monitor" / datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    if out.drive.upper() != "E:" or args.interval < 0.4 or args.max_mb < 1 or args.hours <= 0:
        parser.error("Output must be on E:, interval >= 0.4, and limits positive")
    adb = resolve_adb(args.adb)
    serial = resolve_serial(adb, args.serial)
    recorder = Recorder(out, args.max_mb)
    manifest = {"pid": os.getpid(), "started_at": timestamp(), "runtime": str(args.runtime),
                "adb": str(adb), "serial": serial, "interval": args.interval,
                "max_mb": args.max_mb, "input_operations": False}
    (out / "session.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "角斗场代码快照.py").write_bytes((ROOT / "agent" / "jdc_build_team.py").read_bytes())
    (out / "角斗场流程快照.json").write_bytes((ROOT / "assets/resource/pipeline/base/角斗场.json").read_bytes())
    if args.capture_now or existing_task(args.runtime):
        recorder.active.set()
    worker = threading.Thread(target=capture_loop, args=(recorder, adb, serial, args.interval))
    worker.start()
    tails = {}
    seen = set()
    started_task = recorder.active.is_set()
    finish_at = None
    deadline = time.monotonic() + args.hours * 3600
    recorder.record("monitor_started", **manifest)
    try:
        while not recorder.stop.is_set() and time.monotonic() < deadline:
            if finish_at is not None and time.monotonic() >= finish_at:
                break
            if (out / "STOP").exists():
                break
            paths = list((args.runtime / "logs").glob("*.log")) + [args.runtime / "debug/maafw.log"]
            for path in paths:
                if path not in tails:
                    tails[path] = LogTail(path, from_end=True)
                for line in tails[path].read():
                    event = parse_event(line)
                    if event:
                        msg, details = event
                        key = (msg, details.get("uuid"), details.get("task_id"), details.get("ctrl_id"), details.get("node_id"))
                        if msg.startswith("Tasker.Task.") and details.get("entry") in TASK_NAMES:
                            if key not in seen:
                                seen.add(key)
                                recorder.record("task_event", event=msg, details=details, source=str(path))
                            if msg == "Tasker.Task.Starting":
                                recorder.active.set()
                                started_task = True
                            else:
                                recorder.active.clear()
                                if started_task and not args.keep_listening:
                                    finish_at = time.monotonic() + 2.0
                            recorder.urgent.set()
                        elif recorder.active.is_set() and msg.startswith("Controller.Action."):
                            if details.get("action") in {"swipe", "click", "touch_down", "touch_move", "touch_up"} and key not in seen:
                                seen.add(key)
                                recorder.record("input_event", event=msg, details=details, source=str(path))
                                recorder.urgent.set()
                    if recorder.active.is_set() and ("角斗场" in line or "jdc_" in line or "PipelineNode." in line or "[ERR]" in line or "[WRN]" in line):
                        recorder.record("log", source=str(path), text=line)
                    if started_task and not args.keep_listening and "[op=StopTask]" in line:
                        recorder.active.clear()
                        recorder.urgent.set()
                        finish_at = time.monotonic() + 2.0
            if len(seen) > 20000:
                seen.clear()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.record("monitor_finished", frames=recorder.frames, bytes=recorder.used)
        recorder.stop.set()
        worker.join(timeout=12)
        recorder.stream.close()
        manifest.update(finished_at=timestamp(), frames=recorder.frames, bytes=recorder.used)
        (out / "session.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
