#!/usr/bin/env python3
"""Classify stdin-only coding requests and safely run one bounded Kimi canary."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from urllib.parse import urlsplit


KIMI_MODELS = {"kimi-for-coding", "k3-256k", "k3"}
MODELS = {"auto", "native", *KIMI_MODELS}
MAX_256K_CONTEXT = 262_144
SENSITIVE_ENV_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
SAFE_ENV_NAMES = {
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TMP", "TEMP",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
}
PROXY_ENV_NAMES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}


@dataclass(frozen=True)
class Decision:
    model: str
    reason: str


def estimated_context_tokens(prompt: str, declared_tokens: int) -> int:
    """Use UTF-8 byte count as a conservative, content-free stdin estimate."""
    return max(declared_tokens, len(prompt.encode("utf-8")))


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def native_safety_gate(prompt: str) -> Decision | None:
    text = prompt.lower()
    native_terms = (
        "api key", "access token", "password", "secret", "credential", "private personal",
        "personal data", "private data", "private user data", "sensitive data", "sensitive user data",
        "pii", "personally identifiable information", "customer information", "production", "deploy", "ssh", "browser",
        "terminal", "orchestrat", "use tool", "write files", "modify files", "write file",
        "密钥", "令牌", "密码", "凭据", "隐私", "个人数据", "私密数据", "敏感数据", "用户隐私", "个人信息", "客户信息", "生产环境",
        "部署", "上线", "ssh", "浏览器", "终端", "工具", "写文件", "修改文件",
    )
    if has_any(text, native_terms):
        return Decision("native", "Requires native Codex tools, workspace ownership, or sensitive/high-impact handling.")
    return None


def classify(prompt: str, context_tokens: int, k3_access_supported: bool, k3_1m_supported: bool) -> Decision:
    safety = native_safety_gate(prompt)
    if safety:
        return safety
    text = prompt.lower()
    estimated = estimated_context_tokens(prompt, context_tokens)
    asks_over_256k = has_any(text, ("超过256k", "大于256k", "超过 256k", "大于 256k"))
    asks_near_256k = has_any(text, ("接近256k", "接近 256k"))
    asks_1m_or_video = has_any(text, ("1m context", "one million context", "video analysis", "100万上下文", "100 万上下文", "1m 上下文", "视频分析"))
    if estimated > MAX_256K_CONTEXT or asks_over_256k or asks_1m_or_video:
        if k3_access_supported and k3_1m_supported:
            return Decision("k3", "Needs context beyond 256K or a K3-only 1M/video capability with separately confirmed 1M entitlement.")
        return Decision("native", "K3 1M entitlement is unconfirmed for context beyond 256K or video/1M analysis; keep it native rather than silently downgrading.")
    asks_k3 = has_any(text, ("use k3", "use kimi k3", "model k3", " k3 ", "使用k3", "用k3", "使用 k3", "用 k3"))
    if asks_k3:
        if k3_access_supported:
            return Decision("k3", "User explicitly requested K3 and base K3 model access was confirmed.")
        return Decision("native", "K3 was requested but base K3 model access is unconfirmed; do not silently substitute k3-256k.")
    if estimated > 200_000 or asks_near_256k:
        return Decision("k3-256k", "Needs about 200K–256K context; automatic routing stays on bounded K3-256K even when base K3 access is confirmed.")
    complex_terms = (
        "debug", "architecture", "security", "concurren", "race condition", "state machine",
        "multi-file", "second opinion", "code review", "调试", "架构", "安全", "并发",
        "竞态", "状态机", "多文件", "代码审查", "第二意见",
    )
    if has_any(text, complex_terms):
        return Decision("k3-256k", "Needs a bounded K3 analysis/review under 256K context; invocation requires confirmed base K3 access.")
    return Decision("kimi-for-coding", "Low-ambiguity routine coding/test/boilerplate work is suitable for throughput relief.")


def choose(args: argparse.Namespace, prompt: str) -> Decision:
    safety = native_safety_gate(prompt)
    if safety:
        return safety
    estimated = estimated_context_tokens(prompt, args.context_tokens)
    text = prompt.lower()
    needs_over_256k = estimated > MAX_256K_CONTEXT or has_any(text, (
        "超过256k", "大于256k", "超过 256k", "大于 256k",
        "1m context", "one million context", "video analysis", "100万上下文", "100 万上下文", "1m 上下文", "视频分析",
    ))
    if needs_over_256k:
        if args.model in {"kimi-for-coding", "k3-256k"}:
            return Decision("native", "The requested Kimi model cannot safely receive context beyond 256K; keep it native rather than sending an over-window request.")
        if args.model == "native":
            return Decision("native", "Explicit native selection.")
        if args.k3_access_supported and args.k3_1m_supported:
            return Decision("k3", "Context beyond 256K requires separately confirmed base K3 access and 1M entitlement.")
        return Decision("native", "K3 1M entitlement is unconfirmed for context beyond 256K or video/1M analysis; keep it native rather than silently downgrading.")
    if args.model != "auto":
        if args.model == "k3" and not args.k3_access_supported:
            return Decision("native", "The requested K3 model requires base K3 access, which is unconfirmed; keep it native rather than silently substituting another K3 route.")
        decision = Decision(args.model, "Explicit model selection after the native safety gate.")
    else:
        decision = classify(prompt, args.context_tokens, args.k3_access_supported, args.k3_1m_supported)
    if args.invoke and decision.model in {"k3", "k3-256k"} and not args.k3_access_supported:
        return Decision("native", "K3 invocation requires confirmed base K3 access; dry-run advice is not authorization to call the model.")
    return decision


def safe_proxy_url(value: str) -> bool:
    """Accept only well-formed HTTP(S)/ALL proxy URLs with no authority userinfo."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(parsed.scheme and parsed.hostname and "@" not in parsed.netloc and parsed.username is None and parsed.password is None)


def safe_environment(work_dir: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in SAFE_ENV_NAMES
        and not any(part in key.upper() for part in SENSITIVE_ENV_PARTS)
        and (key.upper() not in PROXY_ENV_NAMES or safe_proxy_url(value))
    }
    env["KIMI_ROUTER_TEMP_DIR"] = work_dir
    return env


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.communicate(timeout=0.5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def invoke(args: argparse.Namespace, prompt: str, decision: Decision) -> dict[str, object]:
    if decision.model not in KIMI_MODELS:
        return {"invoked": False, "status": "refused", "error_kind": "native_route"}
    try:
        with tempfile.TemporaryDirectory(prefix="kimi-model-router-") as work_dir:
            command = [args.kimi_bin, "--print", "--model", decision.model, "--work-dir", work_dir, "--input-format", "text", "--max-steps-per-turn", "1"]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=work_dir, env=safe_environment(work_dir), start_new_session=True)
            try:
                stdout, _ = process.communicate(prompt, timeout=args.timeout)
            except subprocess.TimeoutExpired:
                terminate_process_group(process)
                return {"invoked": True, "status": "timeout", "error_kind": "timeout"}
            response_bytes = len(stdout.encode())
            if process.returncode != 0:
                return {"invoked": True, "status": "error", "error_kind": "child_exit", "exit_code": process.returncode, "response_bytes": response_bytes}
            if not stdout.strip():
                return {"invoked": True, "status": "error", "error_kind": "empty_response", "exit_code": 0, "response_bytes": 0}
            return {"invoked": True, "status": "ok", "exit_code": 0, "response_bytes": response_bytes, "response_is_exact_ok": stdout.strip() == "OK"}
    except OSError:
        return {"invoked": True, "status": "error", "error_kind": "executable"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify a stdin-only Kimi/Codex route.")
    parser.add_argument("--model", choices=sorted(MODELS), default="auto")
    parser.add_argument("--context-tokens", type=int, default=0)
    parser.add_argument("--k3-access-supported", action="store_true", help="Confirm base access to the k3/k3-256k model family; this is not 1M entitlement.")
    parser.add_argument("--k3-1m-supported", action="store_true", help="Confirm K3 1M entitlement separately from base model access.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit advisory mode (also the default).")
    parser.add_argument("--invoke", action="store_true", help="Make one bounded stdin-only Kimi call in an empty temp directory.")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--kimi-bin", default="kimi")
    args = parser.parse_args()
    if args.context_tokens < 0 or args.timeout <= 0:
        parser.error("--context-tokens must be non-negative and --timeout must be positive")
    if args.dry_run and args.invoke:
        parser.error("--dry-run and --invoke are mutually exclusive")
    prompt = sys.stdin.read()
    decision = choose(args, prompt)
    result: dict[str, object] = {"model": decision.model, "reason": decision.reason, "mode": "advisory"}
    if args.invoke:
        result["mode"] = "canary"
        outcome = invoke(args, prompt, decision)
        result.update(outcome)
    print(json.dumps(result, sort_keys=True))
    return 1 if args.invoke and result.get("status") != "ok" else 0


if __name__ == "__main__":
    raise SystemExit(main())
