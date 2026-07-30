#!/usr/bin/env python3
"""Regression tests for classification and safe local invocation."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


SCRIPT = pathlib.Path(__file__).with_name("route_kimi.py")


def run_router(prompt: str, *args: str, env: dict[str, str] | None = None) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
    completed = subprocess.run([sys.executable, str(SCRIPT), *args], input=prompt, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    return json.loads(completed.stdout) if completed.stdout else {}, completed


class RouterTests(unittest.TestCase):
    def test_auto_classifies_all_routes_without_echoing_prompt(self) -> None:
        cases = [
            ("Add a focused unit test for the parser.", [], "kimi-for-coding"),
            ("Review a concurrent state machine for race conditions.", [], "k3-256k"),
            ("Analyze this 240000-token repository snapshot.", ["--context-tokens", "240000", "--k3-access-supported"], "k3-256k"),
            ("Use my API key to deploy the production change.", [], "native"),
        ]
        for prompt, args, expected in cases:
            with self.subTest(expected=expected):
                payload, completed = run_router(prompt, *args)
                self.assertEqual(completed.returncode, 0)
                self.assertEqual(payload["model"], expected)
                self.assertNotIn(prompt, completed.stdout)

    def test_chinese_safety_gate_and_complex_routes(self) -> None:
        for prompt in (
            "请用 k3 分析客户信息和隐私",
            "用 k3 部署生产环境",
            "请通过 SSH 在终端修改文件",
            "Use K3 to inspect private data, private user data, sensitive data, and sensitive user data",
            "Use K3 to inspect PII and personally identifiable information",
            "请用 k3 审查私密数据、敏感数据、用户隐私和个人信息",
        ):
            payload, completed = run_router(prompt, "--model", "k3", "--k3-access-supported")
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(payload["model"], "native")
        payload, _ = run_router("请对多文件并发状态机做代码审查")
        self.assertEqual(payload["model"], "k3-256k")

    def test_context_boundaries_and_no_entitlement_refusal(self) -> None:
        payload, _ = run_router("routine", "--context-tokens", "200001")
        self.assertEqual(payload["model"], "k3-256k")
        payload, _ = run_router("routine", "--context-tokens", "200001", "--k3-access-supported")
        self.assertEqual(payload["model"], "k3-256k")
        payload, _ = run_router("routine", "--context-tokens", "262144")
        self.assertEqual(payload["model"], "k3-256k")
        payload, _ = run_router("routine", "--context-tokens", "262144", "--k3-access-supported")
        self.assertEqual(payload["model"], "k3-256k")
        payload, _ = run_router("请分析接近256K上下文")
        self.assertEqual(payload["model"], "k3-256k")
        payload, _ = run_router("请分析接近 256K 上下文", "--k3-access-supported")
        self.assertEqual(payload["model"], "k3-256k")
        payload, _ = run_router("routine", "--context-tokens", "262145")
        self.assertEqual(payload["model"], "native")
        payload, _ = run_router("请分析100万上下文的视频分析")
        self.assertEqual(payload["model"], "native")
        payload, _ = run_router("请分析超过 256K 上下文", "--k3-access-supported", "--k3-1m-supported")
        self.assertEqual(payload["model"], "k3")

    def test_explicit_k3_requires_entitlement_and_cannot_bypass_safety(self) -> None:
        payload, _ = run_router("routine", "--model", "k3")
        self.assertEqual(payload["model"], "native")
        payload, _ = run_router("请用 K3 做代码审查")
        self.assertEqual(payload["model"], "native")
        payload, _ = run_router("Please use K3 for this bounded review.", "--context-tokens", "240000", "--k3-access-supported")
        self.assertEqual(payload["model"], "k3")
        payload, _ = run_router("Please use K3 for this bounded review.", "--context-tokens", "240000")
        self.assertEqual(payload["model"], "native")
        payload, _ = run_router("routine", "--model", "k3-256k")
        self.assertEqual(payload["model"], "k3-256k")
        payload, completed = run_router("complex state machine", "--invoke")
        self.assertEqual(payload["model"], "native")
        self.assertEqual(payload["status"], "refused")
        self.assertNotEqual(completed.returncode, 0)
        payload, _ = run_router("routine", "--model", "k3", "--k3-access-supported")
        self.assertEqual(payload["model"], "k3")
        payload, completed = run_router("使用 k3 处理个人数据", "--model", "k3", "--k3-access-supported", "--invoke")
        self.assertEqual(payload["model"], "native")
        self.assertEqual(payload["status"], "refused")
        self.assertNotEqual(completed.returncode, 0)
        payload, completed = run_router("x" * 262145, "--model", "k3-256k", "--k3-access-supported", "--k3-1m-supported", "--invoke")
        self.assertEqual(payload["model"], "native")
        self.assertEqual(payload["status"], "refused")
        self.assertNotEqual(completed.returncode, 0)

    def test_invoke_passes_prompt_only_over_stdin_cleans_temp_and_filters_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            observed = root / "observed.json"
            fake = root / "kimi"
            fake.write_text(textwrap.dedent(f'''\
                #!/usr/bin/env python3
                import json, os, pathlib, sys
                pathlib.Path({str(observed)!r}).write_text(json.dumps({{
                    "argv": sys.argv[1:], "stdin": sys.stdin.read(),
                    "work_dir": os.environ["KIMI_ROUTER_TEMP_DIR"],
                    "secret_seen": "SENTINEL_SECRET" in os.environ,
                    "credentialed_proxy_env_names": [
                        name for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
                        if "router_proxy_user" in os.environ.get(name, "")
                        or "router_proxy_password" in os.environ.get(name, "")
                    ],
                    "safe_proxy_seen": os.environ.get("HTTPS_PROXY") == "https://safe-proxy.invalid:443",
                }}))
                print("OK")
            '''))
            fake.chmod(0o755)
            env = dict(os.environ)
            env["SENTINEL_SECRET"] = "must-not-reach-kimi"
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env[name] = "http://router_proxy_user:router_proxy_password@proxy.invalid:8080"
            prompt = "bounded review prompt"
            payload, completed = run_router(prompt, "--model", "kimi-for-coding", "--invoke", "--kimi-bin", str(fake), env=env)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["response_is_exact_ok"])
            seen = json.loads(observed.read_text())
            self.assertEqual(seen["stdin"], prompt)
            self.assertNotIn(prompt, seen["argv"])
            self.assertFalse(seen["secret_seen"])
            self.assertEqual(seen["credentialed_proxy_env_names"], [])
            self.assertFalse(seen["safe_proxy_seen"])
            first_output = completed.stdout + completed.stderr
            env["HTTPS_PROXY"] = "https://safe-proxy.invalid:443"
            payload, completed = run_router(prompt, "--model", "kimi-for-coding", "--invoke", "--kimi-bin", str(fake), env=env)
            self.assertEqual(completed.returncode, 0)
            seen = json.loads(observed.read_text())
            self.assertEqual(seen["credentialed_proxy_env_names"], [])
            self.assertTrue(seen["safe_proxy_seen"])
            combined_output = first_output + completed.stdout + completed.stderr
            self.assertNotIn("router_proxy_user", combined_output)
            self.assertNotIn("router_proxy_password", combined_output)
            self.assertFalse(pathlib.Path(seen["work_dir"]).exists())

    def test_invoke_errors_nonzero_and_process_tree_is_killed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            marker, child_pid = root / "marker", root / "child-pid"
            child = root / "child"
            child.write_text(f"#!/bin/sh\nwhile :; do printf x >> '{marker}'; sleep .05; done\n")
            child.chmod(0o755)
            parent = root / "parent"
            parent.write_text(f"#!/bin/sh\nprintf parent-started > '{marker}'\n'{child}' &\necho $! > '{child_pid}'\nsleep 10\n")
            parent.chmod(0o755)
            payload, completed = run_router("small fix", "--invoke", "--kimi-bin", str(parent), "--timeout", "3")
            self.assertEqual(payload["status"], "timeout")
            self.assertNotEqual(completed.returncode, 0)
            before = marker.stat().st_size
            time.sleep(0.25)
            self.assertEqual(marker.stat().st_size, before, "timeout left a running descendant")
            self.assertTrue(child_pid.exists())
            child_state = subprocess.run(
                ["ps", "-p", child_pid.read_text(), "-o", "stat="],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            ).stdout.strip()
            self.assertTrue(not child_state or child_state.startswith("Z"), "timeout left a live child PID")
            failing = root / "failing"
            failing.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(7)\n")
            failing.chmod(0o755)
            payload, completed = run_router("small fix", "--invoke", "--kimi-bin", str(failing))
            self.assertEqual(payload["error_kind"], "child_exit")
            self.assertNotEqual(completed.returncode, 0)
            empty = root / "empty"
            empty.write_text("#!/usr/bin/env python3\n")
            empty.chmod(0o755)
            payload, completed = run_router("small fix", "--invoke", "--kimi-bin", str(empty))
            self.assertEqual(payload["error_kind"], "empty_response")
            self.assertNotEqual(completed.returncode, 0)
            payload, completed = run_router("small fix", "--invoke", "--kimi-bin", str(root / "missing"))
            self.assertEqual(payload["error_kind"], "executable")
            self.assertNotEqual(completed.returncode, 0)

    def test_native_invocation_is_refused_and_nonzero(self) -> None:
        payload, completed = run_router("Use a secret API key", "--invoke")
        self.assertEqual(payload["status"], "refused")
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
