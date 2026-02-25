"""Main CLI implementation for metadata hooks (currently GPG signature validation)."""
from __future__ import annotations

import argparse
import select
import sys
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, TextIO

from git import Commit, Repo, GitCommandError

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
            raise ValueError(f"invalid range " f"{value!r}: end commit required")
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Block unsigned commits by validating GPG signatures before pushing."
    )
    parser.add_argument("--repo", default=".", help="Path to the git repository (defaults to current directory).")
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
