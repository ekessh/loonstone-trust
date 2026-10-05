"""Start a simulated renewal call and open the browser listener.

    .venv/Scripts/python -m agent.start_call                          # v1.0, baseline
    .venv/Scripts/python -m agent.start_call --version v0.9 --scenario id_bypass
    .venv/Scripts/python -m agent.start_call --scenario handoff

Needs both workers running (in two terminals):
    .venv/Scripts/python -m agent.renewal_agent dev
    .venv/Scripts/python -m agent.borrower_sim dev

Checks the customer is eligible to be called (agent/eligibility.py) before
anything is dispatched, then creates a fresh room, dispatches the borrower
simulator and the renewal agent into it, and opens console/listen.html with a
listen-only token.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from livekit import api

from . import eligibility
from .borrower_sim import AGENT_NAME as BORROWER
from .borrower_sim import SCENARIOS
from .config import DEFAULT_VERSION, OFFER_RECORD, REPO, VERSIONS
from .renewal_agent import AGENT_NAME as AGENT

load_dotenv(REPO / ".env")


async def main(version: str, scenario: str, open_browser: bool) -> str:
    record = json.loads(OFFER_RECORD.read_text(encoding="utf-8"))
    refused = eligibility.check(record, datetime.now(), live=False)
    if refused:
        raise SystemExit("Not dialled: " + "; ".join(refused))

    url = os.environ["LIVEKIT_URL"]
    room = f"renewal-{version.replace('.', '')}-{scenario}-{datetime.now():%Y%m%d-%H%M%S}"
    lk = api.LiveKitAPI(url.replace("ws", "http", 1), os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=600, departure_timeout=30))
        meta = json.dumps({"mode": "sim", "agent_version": version, "scenario": scenario})
        for name in (BORROWER, AGENT):
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=name, room=room, metadata=meta)
            )
    finally:
        await lk.aclose()

    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity("listener")
        .with_name("Listener")
        .with_ttl(timedelta(hours=1))
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=False, can_publish_data=False))
        .to_jwt()
    )
    page = (REPO / "console" / "listen.html").as_uri() + "#" + urlencode({"url": url, "token": token, "room": room})
    print(f"room: {room}")
    print(f"listener: {page}")
    if open_browser:
        # Windows drops the #fragment (and with it the token) when a file:// URL is
        # handed to the shell, so open a launcher file that redirects inside the browser.
        # mkstemp: new random name, created exclusively, owner-only (the file holds the token)
        fd, launcher = tempfile.mkstemp(prefix="loonstone-listen-", suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(
                f'<!doctype html><meta charset="utf-8"><title>Opening listener</title>'
                f'<script>location.replace({json.dumps(page)});</script>'
                f'<p>Opening the listener for {room}...</p>'
            )
        webbrowser.open(Path(launcher).as_uri())
    return room


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", choices=VERSIONS, default=DEFAULT_VERSION)
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="baseline")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.version, args.scenario, not args.no_browser))
    sys.exit(0)
