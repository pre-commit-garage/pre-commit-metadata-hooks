# pre-commit-metadata-hooks

Metadata-focused hooks for `pre-commit` that keep commit history clean before it ever leaves your laptop. The package currently ships checks for signatures, message patterns, and common commit trailers, and the CLI is structured so more metadata rules can be layered on without forking.

## Available hooks

| Hook id | Stage | What it enforces |
| ------- | ----- | ---------------- |
| `require-signed-commits` | `pre-push` | Blocks pushes that contain any commit missing a `gpgsig` header. |
| `forbid-commit-message-patterns` | `commit-msg` | Fails the commit if the subject (or whole message) matches one of the supplied regexes. |
| `forbid-commit-message-patterns-on-push` | `pre-push` | Re-scans every commit about to be pushed for forbidden regex patterns. Useful when merges or rebases introduce bad subjects after the client-side commit-msg hook ran. |
| `forbid-trailers-on-push` | `pre-push` | Rejects pushes containing trailers such as `Signed-off-by`, `Co-authored-by`, `Reviewed-by`, `Acked-by`, `Tested-by`, `Reported-by`, `Suggested-by`, `Reviewed-on`, `Bug`, or `Fixes`. Extra trailers can be blocked or allow-listed per repo. |

Each hook exposes CLI flags so you can tailor the behavior: regex hooks accept `--pattern`, `--ignore-case`, and `--subject-only`; the trailer hook supports `--trailer`, `--allow-trailer`, and `--case-sensitive`.

## Installation

```sh
pip install .
```

## pre-commit configuration

```yaml
default_install_hook_types:
  - pre-commit
  - commit-msg
  - pre-push

repos:
  - repo: https://github.com/pre-commit-garage/pre-commit-metadata-hooks
    rev: v0.1.2
    hooks:
      - id: require-signed-commits
      - id: forbid-commit-message-patterns
        args:
          - --pattern
          - '^wip\b'
          - --ignore-case
          - --subject-only
      - id: forbid-commit-message-patterns-on-push
        args:
          - --pattern
          - '^wip\b'
          - --ignore-case
      - id: forbid-trailers-on-push
        args:
          - --trailer
          - Ticket
          - --allow-trailer
          - Signed-off-by
```

Feel free to drop stages you do not need; each hook already declares sensible defaults.

## CLI usage

The package installs `pre-commit-metadata-hooks`, which dispatches to individual subcommands:

```
pre-commit-metadata-hooks [command] [options]

Commands:
  require-signed-commits (default)
  forbid-commit-message-patterns
  forbid-commit-message-patterns-on-push
  forbid-trailers-on-push
```

Running without a command keeps the legacy behavior of `require-signed-commits`:

```sh
pre-commit-metadata-hooks --range origin/main..HEAD
```

All pre-push commands accept `--repo`, `--range`, and `--commit`, read ranges from Git's `pre-push` stdin when available, and fall back to `HEAD` when no range is supplied.
