# pre-commit-metadata-hooks

Collection of pre-commit-style hooks that guard the metadata of every commit you push. The first hook in this package ensures every pushed commit carries a valid GPG signature, and the repository is structured so additional metadata checks can be added without splintering into multiple packages.

## Hooks

### `require-signed-commits`
- **Purpose:** reject unsigned commits before they reach a remote.
- **Entry point:** `pre-commit-metadata-hooks`
- **Behavior:** reads the ref updates from Git's `pre-push` stdin (or the range passed via `--range/--commit`) and inspects every commit in that range. Any commit lacking a `gpgsig` header causes the hook to fail with a list of offending SHAs.

## Installation

```sh
pip install .
```

## Usage with pre-commit

```yaml
- repo: https://github.com/your-org/pre-commit-metadata-hooks
  rev: vX.Y.Z
  hooks:
    - id: require-signed-commits
      entry: pre-commit-metadata-hooks
      language: python
      stages: [pre-push]
      pass_filenames: false
      always_run: true
```

You can still run the hook manually against a custom range:

```sh
pre-commit-metadata-hooks --range origin/main..HEAD
```

## CLI reference

```
pre-commit-metadata-hooks [--repo PATH] [--range RANGE] [--commit SHA]
```

- `--repo`: path to the repository (defaults to current directory).
- `--range`: inspect the commits in the provided rev-range (repeatable).
- `--commit`: validate a specific commit SHA (repeatable).

When no range/commit is provided, the hook falls back to the commits Git reports through `pre-push` stdin, and when stdin is empty it defaults to `HEAD`.
