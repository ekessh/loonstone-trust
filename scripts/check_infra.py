"""Check the self-hosted stack against the system register's security claims.

    python scripts/check_infra.py

1. Every published port binds to 127.0.0.1, so nothing is reachable off the laptop.
2. Every secret with a weak upstream default (the CHANGEME values in the Langfuse
   compose file) is set in infra/.env to something else.
3. Every secret the compose files require (${VAR:?...}) is set in infra/.env.
4. Every image is pinned by digest.
6. Langfuse usage telemetry (TELEMETRY_ENABLED) resolves to false, so nothing
   leaves the laptop.
7. A default that embeds credentials in a URL (DATABASE_URL) counts as a secret.

Compose files are parsed as YAML, so a comment mentioning a setting does not
satisfy a check.
5. LiveKit in --dev mode gets its keys from LIVEKIT_KEYS, so its fixed dev key
   ("devkey"/"secret") is never active.

Prints variable names only, never values. Exits 1 if any check fails.
"""

from __future__ import annotations

import re
import sys

import yaml
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1] / "infra"
SECRET_NAME = re.compile(r"PASSWORD|SECRET|SALT|ENCRYPTION_KEY|REDIS_AUTH")  # S3 *_ACCESS_KEY_ID values are user names


def env_values() -> dict[str, str]:
    path = INFRA / ".env"
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_REF = re.compile(r"\$\{(\w+)(?::?([-?]))?([^}]*)\}")
_URL_CREDENTIALS = re.compile(r"://[^/:@\s]+:[^@\s]+@")


def resolve(value: str, env: dict[str, str]) -> str:
    """Resolve ${VAR}, ${VAR:-default} and ${VAR:?msg} the way docker compose does."""
    def sub(m):
        var, op, rest = m.group(1), m.group(2), m.group(3)
        if env.get(var):
            return env[var]
        return rest if op == "-" else ""
    return _REF.sub(sub, str(value))


def environment(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return {str(k): "" if v is None else str(v) for k, v in env.items()}


def main() -> int:
    env = env_values()
    failures, notes = [], []
    for compose in sorted(INFRA.glob("compose.*.yml")):
        name = compose.name
        text = compose.read_text(encoding="utf-8")
        doc = yaml.safe_load(text) or {}
        services = doc.get("services") or {}
        if not services:
            failures.append(f"{name}: no services parsed (malformed compose file?)")

        for svc, spec in services.items():
            for port in spec.get("ports") or []:
                mapping = port if isinstance(port, str) else str(port.get("host_ip", "")) + ":" + str(port.get("published", ""))
                if not str(mapping).startswith("127.0.0.1:"):
                    failures.append(f"{name}: {svc} port {mapping} is not bound to 127.0.0.1")

            image = str(spec.get("image", ""))
            if image and "@sha256:" not in image:
                failures.append(f"{name}: {svc} image {image} is not pinned by digest")

            for var, raw in environment(spec).items():
                for ref, op, default in _REF.findall(raw):
                    if op == "?" and not env.get(ref):
                        failures.append(f"{name}: {svc} requires {ref}, missing from infra/.env")
                    is_secret = bool(SECRET_NAME.search(ref)) or bool(_URL_CREDENTIALS.search(default))
                    if op == "-" and default and is_secret:
                        if ref not in env:
                            failures.append(f"{name}: {svc} {ref} not set in infra/.env, so the upstream default is used")
                        elif env[ref] == default:
                            failures.append(f"{name}: {svc} {ref} in infra/.env still equals the upstream default")
                if var == "TELEMETRY_ENABLED" and resolve(raw, env).strip().lower() not in ("false", "0", "no"):
                    failures.append(f"{name}: {svc} TELEMETRY_ENABLED resolves to {resolve(raw, env)!r}; "
                                    "usage telemetry would leave the laptop")

            command = spec.get("command") or ""
            command = " ".join(command) if isinstance(command, list) else str(command)
            if "--dev" in command:
                keys = environment(spec).get("LIVEKIT_KEYS", "")
                if "LIVEKIT_API_KEY" not in keys:
                    failures.append(f"{name}: {svc} runs --dev without LIVEKIT_KEYS referencing LIVEKIT_API_KEY, "
                                    "so it falls back to the fixed dev key")
                elif env.get("LIVEKIT_API_KEY") in (None, "", "devkey") or env.get("LIVEKIT_API_SECRET") in (None, "", "secret"):
                    failures.append(f"{name}: LIVEKIT_API_KEY/SECRET missing from infra/.env or still the dev values")

    for note in notes:
        print("NOTE  " + note)
    for failure in failures:
        print("FAIL  " + failure)
    if not failures:
        print("PASS  ports on localhost, no upstream-default secrets (incl. credentials in URLs), required secrets "
              "set, images pinned by digest, Langfuse telemetry off, LiveKit on generated keys")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
