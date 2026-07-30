---
name: kimi-model-router
description: Safely route routine and non-trivial coding, debugging, architecture, security, concurrency, and code-review tasks between `kimi-for-coding`, `k3-256k`, `k3`, and native Codex/SOL. Use automatically before a Kimi coding/review call or when selecting a model, conserving Codex quota, comparing K3 with SOL, or seeking a bounded second opinion.
---

# Kimi Model Router

Classify first, then select a model. Native Codex/SOL retains orchestration, tool use, workspace writes, sensitive data, and high-impact work. Kimi is advisory by default; apply any edits through the native owner unless the user grants a narrowly scoped write action later.

## Safety gate

Run the safety gate before honoring an explicit model request. Keep the task native when it needs browser or terminal tools, workspace writes, production or other high-impact actions, secrets, personal data, customer data, or other sensitive material. The router returns a native route rather than invoking Kimi for these requests.

## Routing policy

- `kimi-for-coding`: routine, low-ambiguity code, tests, or boilerplate.
- `k3-256k`: bounded debugging, architecture, security, concurrency, state-machine, or code-review analysis at or below 256K context. A real invocation requires separately confirmed base K3 access.
- `k3`: only when the user explicitly requests K3 and base K3 access is confirmed, or when the task exceeds 256K context or needs video/1M analysis and both base K3 access and separate 1M support are confirmed. Never silently substitute it for another model.
- `native`: any safety-gated task, an unconfirmed requested model, or context outside the selected model's safe window.

The context estimate is conservative: it uses the larger of `--context-tokens` and the UTF-8 byte count of stdin. Do not send secrets or unnecessary content. Keep Kimi output to an answer or review; the native owner remains responsible for changes.

## Dry run first

From this skill directory, put only redacted, non-sensitive task text in a temporary file with your preferred editor, then pass it via stdin:

```sh
task_file="$(mktemp)"
chmod 600 "$task_file"
# Edit "$task_file" with redacted task text.
python3 scripts/route_kimi.py --dry-run < "$task_file"
rm -f -- "$task_file"
```

Dry run is advisory and does not call a model. The JSON output contains the selected route and a reason, not the input prompt.

## Bounded invocation

Only after the dry run and independent confirmation that the request is safe to share, invoke one model call. The prompt is passed over stdin, the child runs in an empty temporary directory, the environment is allowlisted, credentialed proxy URLs are rejected, and timeouts terminate the child process group.

```sh
python3 scripts/route_kimi.py \
  --model k3-256k \
  --k3-access-supported \
  --invoke \
  --timeout 30 \
  < "$task_file"
```

Use `--k3-1m-supported` only when separate support for that capability has been confirmed; this flag is not inferred from base K3 access. Invocation fails closed for a native route, unavailable executable, timeout, empty response, or nonzero child exit.

## Installation and validation

To install from a repository that contains this package, set a portable Codex home and copy the directory into it:

```sh
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills"
cp -R skills/kimi-model-router "$CODEX_HOME/skills/"
cd "$CODEX_HOME/skills/kimi-model-router"
```

Run the package checks from the skill directory:

```sh
python3 scripts/test_route_kimi.py
python3 -m py_compile scripts/route_kimi.py scripts/test_route_kimi.py
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" .
```

This router is a local selection boundary, not a benchmark, provider setup guide, entitlement claim, or automatic fallback mechanism.
