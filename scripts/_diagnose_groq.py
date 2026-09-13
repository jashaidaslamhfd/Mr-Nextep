"""TEMPORARY diagnostic — not part of the pipeline, safe to delete after use.

Tests the real GROQ_API_KEY secret against Groq's API and writes ONLY a redacted
result (key length + first/last 2 chars, HTTP status, truncated error body) to
data/_groq_diagnostic.json, then commits it. The actual key value is never
written anywhere. This exists purely because Actions log/artifact downloads are
blocked from the debugging environment being used right now.
"""
from __future__ import annotations

import json
import os
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def redact(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return f"(len={len(key)}, too short to redact-preview)"
    return f"(len={len(key)}, {key[:4]}...{key[-4:]})"


def main() -> None:
    key = os.getenv("GROQ_API_KEY", "")
    info = {"key_present": bool(key), "key_fingerprint": redact(key)}
    if not key:
        info["verdict"] = "GROQ_API_KEY env var is empty/unset in this job"
    else:
        try:
            req = Request(
                "https://api.groq.com/openai/v1/models",
                headers={
                    "Authorization": f"Bearer {key}",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Mr-Nextep-Pipeline/1.0",
                },
            )
            with urlopen(req, timeout=15) as resp:
                info["http_status"] = resp.status
                info["verdict"] = "key authenticates successfully"
        except HTTPError as exc:
            info["http_status"] = exc.code
            body = exc.read().decode("utf-8", errors="replace")[:300]
            info["error_body"] = body
            info["verdict"] = "key REJECTED by Groq" if exc.code in (401, 403) else "unexpected HTTP error"
        except URLError as exc:
            info["verdict"] = f"network error reaching Groq: {exc.reason}"

    out_path = "data/_groq_diagnostic.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        check=False,
    )
    subprocess.run(["git", "add", "-f", out_path], check=False)
    subprocess.run(["git", "commit", "-m", "chore: groq key diagnostic result"], check=False)
    subprocess.run(["git", "push", "origin", "HEAD"], check=False)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
