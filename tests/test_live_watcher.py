"""Tests for prism.widgets.live_watcher — incremental tail-read wiring."""

from __future__ import annotations

import json
import os
from pathlib import Path

from textual.app import App, ComposeResult

from prism.analyzer import estimate_record_tokens
from prism.parser import AssistantRecord, SystemRecord, parse_session_file
from prism.widgets.live_watcher import LiveWatcher


def _user(uuid: str, text: str = "hello") -> str:
    return json.dumps({
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "sessionId": "sess-live",
        "timestamp": "2026-06-03T10:00:00.000Z",
        "version": "2.1.98",
        "cwd": "/home/user/proj",
        "gitBranch": "main",
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    })


def _assistant(uuid: str) -> str:
    return json.dumps({
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "sessionId": "sess-live",
        "timestamp": "2026-06-03T10:00:01.000Z",
        "version": "2.1.98",
        "cwd": "/home/user/proj",
        "gitBranch": "main",
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "On it."},
                {"type": "tool_use", "id": f"t-{uuid}", "name": "Bash",
                 "input": {"command": "ls"}},
            ],
            "usage": {"output_tokens": 42},
        },
    })


def _append(path: Path, data: str) -> None:
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(data)


def _expected_state(path: Path) -> tuple[int, int]:
    records = parse_session_file(path).records
    tokens = sum(estimate_record_tokens(r) for r in records)
    tools = sum(
        1 for r in records
        if isinstance(r, AssistantRecord)
        for b in r.content if b.type == "tool_use"
    )
    return tokens, tools


class WatchApp(App):
    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self._base_dir = base_dir

    def compose(self) -> ComposeResult:
        yield LiveWatcher(base_dir=self._base_dir)


class TestLiveWatcherIncremental:
    async def test_appended_file_yields_same_state_as_full_reparse(self, tmp_path):
        proj = tmp_path / "-home-user-proj"
        proj.mkdir()
        f = proj / "live.jsonl"
        f.write_text(_user("u1") + "\n", encoding="utf-8")

        app = WatchApp(tmp_path)
        async with app.run_test() as pilot:
            watcher = app.query_one(LiveWatcher)
            seen: list[LiveWatcher.SessionUpdated] = []
            orig_post = watcher.post_message

            def capture(message):
                if isinstance(message, LiveWatcher.SessionUpdated):
                    seen.append(message)
                return orig_post(message)

            watcher.post_message = capture

            watcher._poll_and_update()
            await pilot.pause()
            offset_after_first = watcher._tail._offset
            assert offset_after_first == f.stat().st_size

            _append(f, _assistant("a1") + "\n" + _user("u2") + "\n")
            watcher._poll_and_update()
            await pilot.pause()

            # Incremental: offset advanced, not reset.
            assert watcher._tail._offset == f.stat().st_size
            assert watcher._tail._offset > offset_after_first

            # Same state a full re-parse of the final file would produce.
            expected_tokens, expected_tools = _expected_state(f)
            assert watcher._tail.records == parse_session_file(f).records
            assert seen[-1].token_count == expected_tokens
            assert seen[-1].tool_calls == expected_tools

    async def test_rotation_to_new_session_file_resets_tail(self, tmp_path):
        proj = tmp_path / "-home-user-proj"
        proj.mkdir()
        old = proj / "old.jsonl"
        old.write_text(_user("u1") + "\n" + _user("u2") + "\n", encoding="utf-8")
        os.utime(old, (1_000_000_000, 1_000_000_000))

        app = WatchApp(tmp_path)
        async with app.run_test() as pilot:
            watcher = app.query_one(LiveWatcher)
            watcher._poll_and_update()
            await pilot.pause()
            assert watcher._tail.path == old
            assert len(watcher._tail.records) == 2

            # A new session file appears with a newer mtime.
            new = proj / "new.jsonl"
            new.write_text(_user("n1") + "\n", encoding="utf-8")
            watcher._poll_and_update()
            await pilot.pause()

            assert watcher._tail.path == new
            assert watcher._tail.records == parse_session_file(new).records
            assert len(watcher._tail.records) == 1

    async def test_shrunk_file_rereads_from_start(self, tmp_path):
        proj = tmp_path / "-home-user-proj"
        proj.mkdir()
        f = proj / "live.jsonl"
        f.write_text(
            _user("u1") + "\n" + _user("u2") + "\n" + _user("u3") + "\n",
            encoding="utf-8",
        )

        app = WatchApp(tmp_path)
        async with app.run_test() as pilot:
            watcher = app.query_one(LiveWatcher)
            watcher._poll_and_update()
            await pilot.pause()
            assert len(watcher._tail.records) == 3

            f.write_text(_user("x1") + "\n", encoding="utf-8")
            watcher._poll_and_update()
            await pilot.pause()

            assert watcher._tail.records == parse_session_file(f).records
            assert len(watcher._tail.records) == 1
