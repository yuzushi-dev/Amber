import os
import subprocess
from pathlib import Path


def test_smoke_defaults_to_nginx_frontend(tmp_path):
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "${CURL_LOG}"
if [[ " $* " == *" -w "* ]]; then
    if [[ " $* " == *"/v1/admin/tenants"* ]]; then
        printf '401'
    else
        printf '200'
    fi
else
    printf '{"status":"ok"}'
fi
"""
    )
    fake_curl.chmod(0o755)

    repo_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    curl_log = tmp_path / "curl.log"
    environment["CURL_LOG"] = str(curl_log)

    result = subprocess.run(
        ["bash", "scripts/smoke_production_readonly.sh"],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Frontend: http://127.0.0.1\n" in result.stdout
    assert any(
        "http://127.0.0.1/" in invocation
        for invocation in curl_log.read_text().splitlines()
    )
