"""Offline tests; no emulator connection or game actions."""
from pathlib import Path
import tempfile

from monitor_jdc import LogTail, parse_event, Recorder


def main():
    event = parse_event('[msg=Tasker.Task.Starting] [details={"entry":"角斗场","task_id":12}] ')
    assert event == ("Tasker.Task.Starting", {"entry": "角斗场", "task_id": 12})
    event = parse_event('[message=Controller.Action.Starting] [details_json={"action":"swipe","ctrl_id":12}] [trans_arg=true] ')
    assert event == ("Controller.Action.Starting", {"action": "swipe", "ctrl_id": 12})
    assert parse_event("unrelated log") is None
    assert parse_event("[msg=x] [details=invalid]") is None
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent / ".tmp") as temp:
        path = Path(temp) / "test.log"
        path.write_bytes(b"old\n")
        tail = LogTail(path)
        assert tail.read() == []
        with path.open("ab") as stream:
            stream.write("角斗".encode())
        assert tail.read() == []
        with path.open("ab") as stream:
            stream.write("场\n".encode())
        assert tail.read() == ["角斗场"]
        path.write_bytes(b"new\n")
        assert tail.read() == ["new"]
        recorder = Recorder(Path(temp) / "session", 1)
        recorder.frame(b"fake PNG", "start", "test")
        recorder.frame(b"fake PNG", "later", "test")
        assert recorder.frames == 1
        recorder.stream.close()
        recorder = Recorder(Path(temp) / "limit", 1)
        recorder.frame(b"x" * (1024 * 1024 + 1), "start", "test")
        assert recorder.stop.is_set()
        recorder.stream.close()
    print("MONITOR_OFFLINE_OK: event parsing, partial UTF8, truncation, frame deduplication, capacity limit")


if __name__ == "__main__":
    main()
