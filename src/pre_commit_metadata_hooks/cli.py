"""Main CLI implementation for metadata hooks."""

from __future__ import annotations

import argparse
import re
import select
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, TextIO

from git import Commit, GitCommandError, Repo

ZERO_COMMIT = "0" * 40


@dataclass(frozen=True)
class RevRange:
    start: Optional[str]
    end: str

    def to_rev(self) -> str:
        if self.start:
            return f"{self.start}..{self.end}"
        return self.end


def parse_pre_push_lines(lines: Iterable[str]) -> List[RevRange]:
    ranges: List[RevRange] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        _, local_sha, _, remote_sha = parts
        if local_sha == ZERO_COMMIT:
            continue
        start = None if remote_sha == ZERO_COMMIT else remote_sha
        ranges.append(RevRange(start=start, end=local_sha))
    return ranges


def parse_range_arg(value: str) -> RevRange:
    value = value.strip()
    if ".." in value:
        start, end = value.split("..", 1)
        end = end.strip()
        if not end or end == ZERO_COMMIT:
            raise ValueError(f"invalid range {value!r}: end commit required")
        start = start.strip()
        normalized_start = None
        if start and start != ZERO_COMMIT:
            normalized_start = start
        return RevRange(start=normalized_start, end=end)

    if not value or value == ZERO_COMMIT:
        raise ValueError(f"invalid range {value!r}: commit required")
    return RevRange(start=None, end=value)


def combine_ranges(
    *,
    ranges: Iterable[str],
    commits: Iterable[str],
    stdin_ranges: Iterable[RevRange],
) -> List[RevRange]:
    result: List[RevRange] = []
    for value in ranges:
        result.append(parse_range_arg(value))
    for sha in commits:
        sha = sha.strip()
        if not sha or sha == ZERO_COMMIT:
            continue
        result.append(RevRange(start=None, end=sha))
    result.extend(stdin_ranges)
    if not result:
        result.append(RevRange(start=None, end="HEAD"))
    return result


def stdin_has_data(stdin: TextIO) -> bool:
    if getattr(stdin, "closed", False):
        return False
    if getattr(stdin, "isatty", lambda: True)():
        return False
    try:
        readable, _, _ = select.select([stdin], [], [], 0)
    except (ValueError, OSError):
        return False
    return bool(readable)


def read_pre_push_ranges(stdin: TextIO) -> List[RevRange]:
    if not stdin_has_data(stdin):
        return []
    data = stdin.read().splitlines()
    return parse_pre_push_lines(data)


def iter_commits_for_ranges(repo: Repo, ranges: Iterable[RevRange]) -> Iterator[Commit]:
    seen: set[str] = set()
    for rev_range in ranges:
        rev = rev_range.to_rev()
        try:
            for commit in repo.iter_commits(rev):
                if commit.hexsha in seen:
                    continue
                seen.add(commit.hexsha)
                yield commit
        except GitCommandError as error:
            raise SystemExit(f"git error while iterating {rev}: {error}")


def find_unsigned_commits(repo: Repo, ranges: Iterable[RevRange]) -> List[Commit]:
    unsigned: List[Commit] = []
    for commit in iter_commits_for_ranges(repo, ranges):
        if not commit.gpgsig:
            unsigned.append(commit)
    return unsigned


def format_unsigned_message(unsigned: List[Commit]) -> str:
    pieces = ["Unsigned commits detected:"]
    for commit in unsigned:
        pieces.append(f"- {commit.hexsha} {commit.summary or ''}".rstrip())
    return "\n".join(pieces)


def require_signed_commits(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Block unsigned commits by validating GPG signatures before pushing."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to the git repository (defaults to current directory).",
    )
    parser.add_argument(
        "--range",
        dest="ranges",
        action="append",
        default=[],
        help="Commit range to inspect, e.g. HEAD~5..HEAD. Can be repeated.",
    )
    parser.add_argument(
        "--commit",
        dest="commits",
        action="append",
        default=[],
        help="Specific commit SHA to validate. Can be repeated.",
    )

    args = parser.parse_args(argv)
    stdin_ranges = read_pre_push_ranges(sys.stdin)
    resolved_ranges = combine_ranges(
        ranges=args.ranges, commits=args.commits, stdin_ranges=stdin_ranges
    )

    repo = Repo(args.repo)
    unsigned = find_unsigned_commits(repo, resolved_ranges)
    if unsigned:
        print(format_unsigned_message(unsigned), file=sys.stderr)
        return 1
    return 0


def forbid_commit_message_patterns(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Block commit messages that match forbidden regular expressions."
    )
    parser.add_argument(
        "--pattern",
        action="append",
        dest="patterns",
        required=True,
        help="Regular expression describing disallowed content. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="Match patterns case-insensitively.",
    )
    parser.add_argument(
        "--subject-only",
        action="store_true",
        help="Only inspect the subject (first line) of the commit message.",
    )
    parser.add_argument(
        "commit_msg_file",
        help="Path to the commit message file provided by Git.",
    )

    args = parser.parse_args(argv)

    try:
        message = Path(args.commit_msg_file).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - exercised in runtime environments
        raise SystemExit(f"failed to read commit message file: {exc}") from exc

    if args.subject_only:
        message = message.splitlines()[0] if message else ""

    flags = re.MULTILINE
    if args.ignore_case:
        flags |= re.IGNORECASE

    violations: List[str] = []
    for pattern in args.patterns:
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise SystemExit(f"invalid pattern {pattern!r}: {exc}") from exc
        if compiled.search(message):
            violations.append(pattern)

    if not violations:
        return 0

    lines = ["Commit message contains forbidden patterns:"]
    lines.extend(f"- {pattern}" for pattern in violations)
    print("\n".join(lines), file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    commands: Dict[str, Callable[[Optional[List[str]]], int]] = {
        "require-signed-commits": require_signed_commits,
        "forbid-commit-message-patterns": forbid_commit_message_patterns,
    }

    if args and args[0] in commands:
        command = args[0]
        command_args: Optional[List[str]] = args[1:]
    else:
        command = "require-signed-commits"
        command_args = args

    return commands[command](command_args)
