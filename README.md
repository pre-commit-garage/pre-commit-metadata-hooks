# pre-commit-metadata-hooks

Metadata-focused hooks for `pre-commit` that keep commit history clean before it ever leaves your laptop. The package currently ships checks for signatures, commit email domains, message patterns, and common commit trailers, and the CLI is structured so more metadata rules can be layered on without forking.

## Available hooks

| Hook id | Stage | What it enforces |
| ------- | ----- | ---------------- |
| `require-signed-commits` | `pre-push` | Blocks pushes that contain any commit missing a `gpgsig` header. |
| `validate-commit-emails` | `pre-commit` | Fails before a commit is created when the current Git author or committer email is outside your allowed domain. |
| `validate-recent-commit-emails-on-push` | `pre-push` | Checks a bounded window of recent commits from each pushed tip so older local history with the wrong email domain is still caught without scanning the whole repository. |
| `forbid-commit-message-patterns` | `commit-msg` | Fails the commit if the subject (or whole message) matches one of the supplied regexes. |
| `forbid-commit-message-patterns-on-push` | `pre-push` | Re-scans every commit about to be pushed for forbidden regex patterns. Useful when merges or rebases introduce bad subjects after the client-side commit-msg hook ran. |
| `forbid-trailers-on-push` | `pre-push` | Rejects pushes that contain supported trailers you explicitly pick. This keeps the check tied to a known list so typos such as `Co-auhtored-by` fail early. |

Each hook exposes CLI flags so you can tailor the behavior: email hooks accept `--domain`, and the push-time email hook also accepts `--max-count`; regex hooks accept `--pattern`, `--ignore-case`, and `--subject-only`; the trailer hook accepts one or more `--trailer` arguments and an optional `--case-sensitive` flag.

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
      - id: validate-commit-emails
        args:
          - --domain
          - company.com
      - id: validate-recent-commit-emails-on-push
        args:
          - --domain
          - company.com
          - --max-count
          - '50'
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
          - Signed-off-by
          - --trailer
          - Co-authored-by
```

Feel free to drop stages you do not need; each hook already declares sensible defaults.

`validate-recent-commit-emails-on-push` exists because a normal `pre-commit` hook only checks the commit you are creating right now. It cannot protect you from older commits near the branch tip, such as a repository bootstrap commit or an early local commit created with the wrong Git identity. The push-time hook closes that gap while staying bounded: it inspects only a configurable number of recent commits from each pushed tip instead of walking full history.

### Supported commit trailers

Only the following trailers are recognized by `forbid-trailers-on-push` (match is case-insensitive unless you supply `--case-sensitive`):

- Acked-by
- Bug
- Co-authored-by
- Fixes
- Reported-by
- Reviewed-by
- Reviewed-on
- Signed-off-by
- Suggested-by
- Tested-by

## CLI usage

The package installs `pre-commit-metadata-hooks`, which dispatches to individual subcommands:

```
pre-commit-metadata-hooks [command] [options]

Commands:
  require-signed-commits (default)
  validate-commit-emails
  validate-recent-commit-emails-on-push
  forbid-commit-message-patterns
  forbid-commit-message-patterns-on-push
  forbid-trailers-on-push
```

Invoke the command you need explicitly, e.g. to inspect a custom range with the signature check:

```sh
pre-commit-metadata-hooks require-signed-commits --range origin/main..HEAD
```

All pre-push commands accept `--repo`, `--range`, and `--commit`, read ranges from Git's `pre-push` stdin when available, and fall back to `HEAD` when no range is supplied.
