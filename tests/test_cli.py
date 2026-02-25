"""Unit tests for the pre-commit-metadata-hooks CLI helpers."""

from __future__ import annotations

import pytest
from git import GitCommandError

from pre_commit_metadata_hooks import cli
from pre_commit_metadata_hooks.cli import (
    RevRange,
    combine_ranges,
    find_unsigned_commits,
    iter_commits_for_ranges,
    parse_pre_push_lines,
    parse_range_arg,
)


class DummyCommit:
    def __init__(
        self,
        hexsha: str,
        summary: str = "",
        message: str = "",
        gpgsig: str | None = None,
    ) -> None:
        self.hexsha = hexsha
        self.summary = summary
        self.message = message
        self.gpgsig = gpgsig


def test_parse_pre_push_lines_filters_zero_commits() -> None:
    base = "f" * 40
    local = "1" * 40
    remote = "2" * 40
    inputs = [
        f"refs/heads/main {local} refs/remotes/origin/main {remote}",
        f"refs/heads/main {local} refs/remotes/origin/main {cli.ZERO_COMMIT}",
        "invalid line",
        "",
    ]

    ranges = parse_pre_push_lines(inputs)

    assert ranges == [
        RevRange(start=remote, end=local),
        RevRange(start=None, end=local),
    ]


def test_parse_range_arg_handles_empty_start() -> None:
    parsed = parse_range_arg("abc123..def456")
    assert parsed.start == "abc123"
    assert parsed.end == "def456"


def test_parse_range_arg_raises_for_zero_end() -> None:
    with pytest.raises(ValueError):
        parse_range_arg("abc.." + "0" * 40)


def test_combine_ranges_defaults_to_head() -> None:
    result = combine_ranges(ranges=(), commits=(), stdin_ranges=())
    assert result == [RevRange(start=None, end="HEAD")]


def test_iter_commits_for_ranges_deduplicates() -> None:
    commit = DummyCommit("a" * 40)

    class StubRepo:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def iter_commits(self, rev: str):
            self.calls.append(rev)
            yield commit
            yield commit

    repo = StubRepo()
    ranges = [RevRange(start="abc", end="def"), RevRange(start=None, end="ghi")]

    result = list(iter_commits_for_ranges(repo, ranges))

    assert result == [commit]
    assert repo.calls == ["abc..def", "ghi"]


def test_iter_commits_for_ranges_reports_git_errors() -> None:
    class ErrorRepo:
        def iter_commits(self, _: str):
            raise GitCommandError("rev-parse", "boom")

    with pytest.raises(SystemExit) as excinfo:
        list(iter_commits_for_ranges(ErrorRepo(), [RevRange(start=None, end="HEAD")]))

    assert "git error" in str(excinfo.value)


def test_find_unsigned_commits_filters_signed() -> None:
    signed = DummyCommit("a" * 40, gpgsig="sig")
    unsigned = DummyCommit("b" * 40)

    class RepoWithCommits:
        def iter_commits(self, _: str):
            yield signed
            yield unsigned

    commits = find_unsigned_commits(
        RepoWithCommits(), [RevRange(start=None, end="HEAD")]
    )

    assert commits == [unsigned]


def test_format_unsigned_message_includes_hexsha() -> None:
    unsigned = DummyCommit("deadbeef" * 5, summary="missing signature")
    formatted = cli.format_unsigned_message([unsigned])

    assert "Unsigned commits detected:" in formatted
    assert unsigned.hexsha in formatted


def test_main_returns_zero_for_signed(monkeypatch) -> None:
    commit = DummyCommit("a" * 40, gpgsig="sig")

    class Repo:
        def iter_commits(self, _: str):
            yield commit

    monkeypatch.setattr(
        cli, "read_pre_push_ranges", lambda stdin: [RevRange(start=None, end="HEAD")]
    )
    monkeypatch.setattr(
        cli, "combine_ranges", lambda **kwargs: [RevRange(start=None, end="HEAD")]
    )
    monkeypatch.setattr(cli, "Repo", lambda repo_path: Repo())

    assert cli.main([]) == 0


def test_main_reports_unsigned_commits(monkeypatch, capsys) -> None:
    unsigned = DummyCommit("b" * 40)

    class Repo:
        def iter_commits(self, _: str):
            yield unsigned

    monkeypatch.setattr(
        cli, "read_pre_push_ranges", lambda stdin: [RevRange(start=None, end="HEAD")]
    )
    monkeypatch.setattr(
        cli, "combine_ranges", lambda **kwargs: [RevRange(start=None, end="HEAD")]
    )
    monkeypatch.setattr(cli, "Repo", lambda repo_path: Repo())

    result = cli.main([])

    assert result == 1
    assert unsigned.hexsha in capsys.readouterr().err


def test_forbid_commit_message_patterns_blocks_subject(tmp_path, capsys) -> None:
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("WIP: test\n\nbody")

    result = cli.forbid_commit_message_patterns(
        [
            "--pattern",
            r"^wip\b",
            "--ignore-case",
            "--subject-only",
            str(message_path),
        ]
    )

    assert result == 1
    output = capsys.readouterr().err
    assert "forbidden" in output
    assert "^wip\\b" in output


def test_forbid_commit_message_patterns_allows_clean_message(tmp_path) -> None:
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("feat: add feature\n\nbody")

    result = cli.forbid_commit_message_patterns(
        [
            "--pattern",
            r"^wip\b",
            str(message_path),
        ]
    )

    assert result == 0


def test_forbid_commit_message_patterns_accepts_body(tmp_path) -> None:
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("feat: ok\n\nWIP details")

    result = cli.forbid_commit_message_patterns(
        [
            "--pattern",
            r"WIP",
            str(message_path),
        ]
    )

    assert result == 1


def test_forbid_commit_message_patterns_invalid_regex(tmp_path) -> None:
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("ok")

    with pytest.raises(SystemExit):
        cli.forbid_commit_message_patterns(
            [
                "--pattern",
                r"(*invalid",
                str(message_path),
            ]
        )


def test_main_dispatches_to_subcommand(monkeypatch) -> None:
    called: dict[str, list[str] | None] = {}

    def fake_forbid(argv):
        called["args"] = argv
        return 0

    monkeypatch.setattr(cli, "forbid_commit_message_patterns", fake_forbid)

    assert cli.main(["forbid-commit-message-patterns", "msg.txt"]) == 0
    assert called["args"] == ["msg.txt"]


def _patch_pre_push(monkeypatch, commit: DummyCommit) -> None:
    class RepoWithCommits:
        def iter_commits(self, _: str):
            yield commit

    monkeypatch.setattr(
        cli,
        "read_pre_push_ranges",
        lambda stdin: [RevRange(start=None, end="HEAD")],
    )
    monkeypatch.setattr(
        cli,
        "combine_ranges",
        lambda **kwargs: [RevRange(start=None, end="HEAD")],
    )
    monkeypatch.setattr(cli, "Repo", lambda repo_path: RepoWithCommits())


def test_forbid_commit_message_patterns_on_push(monkeypatch, capsys) -> None:
    commit = DummyCommit("a" * 40, message="WIP: fix later")
    _patch_pre_push(monkeypatch, commit)

    result = cli.forbid_commit_message_patterns_on_push(
        ["--pattern", r"^wip\b", "--ignore-case"]
    )

    assert result == 1
    output = capsys.readouterr().err
    assert commit.hexsha in output
    assert r"^wip\b" in output


def test_forbid_commit_message_patterns_on_push_subject_only(monkeypatch) -> None:
    commit = DummyCommit("b" * 40, message="feat: release\n\nWIP notes")
    _patch_pre_push(monkeypatch, commit)

    result = cli.forbid_commit_message_patterns_on_push(
        ["--pattern", r"WIP", "--subject-only"]
    )

    assert result == 0


def test_forbid_commit_message_patterns_on_push_allows_clean_commits(
    monkeypatch,
) -> None:
    commit = DummyCommit("c" * 40, message="feat: ok")
    _patch_pre_push(monkeypatch, commit)

    result = cli.forbid_commit_message_patterns_on_push(["--pattern", r"WIP"])

    assert result == 0


def test_forbid_trailers_on_push_blocks_default(monkeypatch, capsys) -> None:
    commit = DummyCommit(
        "d" * 40,
        message="feat: add\n\nbody\n\nSigned-off-by: Dev <dev@example.com>",
    )
    _patch_pre_push(monkeypatch, commit)

    result = cli.forbid_trailers_on_push([])

    assert result == 1
    output = capsys.readouterr().err
    assert commit.hexsha in output
    assert "Signed-off-by" in output


def test_forbid_trailers_on_push_respects_allow(monkeypatch) -> None:
    commit = DummyCommit(
        "e" * 40,
        message="feat: add\n\nSigned-off-by: Dev <dev@example.com>",
    )
    _patch_pre_push(monkeypatch, commit)

    result = cli.forbid_trailers_on_push(["--allow-trailer", "Signed-off-by"])

    assert result == 0


def test_forbid_trailers_on_push_supports_extra(monkeypatch, capsys) -> None:
    commit = DummyCommit(
        "f" * 40,
        message="feat: add\n\nTicket: 123",
    )
    _patch_pre_push(monkeypatch, commit)

    result = cli.forbid_trailers_on_push(["--trailer", "Ticket"])

    assert result == 1
    assert "Ticket" in capsys.readouterr().err
