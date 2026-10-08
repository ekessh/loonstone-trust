# Loonstone Trust

> **Fictional bank, demo only.** Loonstone Trust, its people and its customers do not exist.

A YouTube series that takes one AI request through the full AI governance lifecycle, built to comply with the EU AI Act, following ISO/IEC 42001 and the NIST AI Risk Management Framework.

## Episodes

| # | Episode | What it covers |
|---|---|---|
| 0 | Teaser | A hypothetical pressure call, rewound to day zero. The head of mortgage sales asks for an AI agent that calls every renewing customer, pitches a personalised rate and gets them to lock in on the call. The bank's AI register is empty. The gates the request will pass through, from intake to retirement. |
| 1 | Intake | The request goes through intake and gate G0. Intake finds shadow AI: sales ops had already uploaded 50 real customer records to a free online voice-demo site. The first register entry (UC-1, issued by VerifyWise), a preliminary risk screen with five red flags, and two G0 records: first Unclear with a named escalation, then Proceed with a narrowed scope. |

Next: risk assessment.

## Run it locally

Everything runs on your machine. Every published port binds to `127.0.0.1`.

### What you need

- Docker with Compose v2
- Python 3.12
- API keys: Anthropic (agent dialogue), Deepgram (speech-to-text and text-to-speech), OpenRouter (borrower simulator)

### 1. Python environment

```sh
python -m venv .venv
.venv/Scripts/python -m pip install "livekit-agents[anthropic,deepgram,openai,silero]==1.8.3" livekit-api python-dotenv pyyaml opentelemetry-sdk opentelemetry-exporter-otlp-proto-http pytest
```

On macOS or Linux, use `.venv/bin/python` in place of `.venv/Scripts/python` throughout.

Check it with the unit tests (no network, no keys needed):

```sh
.venv/Scripts/python -m pytest agent/tests
```

### 2. Secrets

Two env files, both git-ignored:

| File | For | Start from |
|---|---|---|
| `infra/.env` | The Docker services: Langfuse, VerifyWise, LiveKit | `infra/.env.example` |
| `.env` | The agent and the simulator | `.env.example` |

Generate every secret yourself. Never keep an upstream default such as `CHANGEME` or `mysecret`. `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` must match in both files. The Langfuse project keys you set in `infra/.env` (`LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY`) go into `.env` as `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.

Then check the stack config before starting anything:

```sh
.venv/Scripts/python scripts/check_infra.py
```

It checks that ports bind to localhost, secrets are set and not upstream defaults, images are pinned by digest, and Langfuse telemetry is off. It prints variable names only, never values.

### 3. Start the services

```sh
docker compose --env-file infra/.env -f infra/compose.verifywise.yml up -d
docker compose --env-file infra/.env -f infra/compose.langfuse.yml up -d
docker compose --env-file infra/.env -f infra/compose.livekit.yml up -d
```

| Service | What it is in the series | URL |
|---|---|---|
| VerifyWise | The AI system register: use cases, risks, gate records | http://localhost:8084 |
| VerifyWise mail | Catches invite emails (read the invite link here) | http://localhost:8027 |
| Langfuse | Call traces, with personal data redacted | http://localhost:3000 |
| LiveKit | Real-time audio for simulated calls | ws://localhost:7880 |

Log in to VerifyWise with `VW_ADMIN_EMAIL` and `VW_ADMIN_PASSWORD` from `infra/.env`, and to Langfuse with `LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD`.

### 4. Run a simulated call

Start the two workers, each in its own terminal:

```sh
.venv/Scripts/python -m agent.renewal_agent dev
.venv/Scripts/python -m agent.borrower_sim dev
```

Then start a call. It opens a browser listener with the live transcript:

```sh
.venv/Scripts/python -m agent.start_call                                    # v1.0, baseline customer
.venv/Scripts/python -m agent.start_call --version v0.9 --scenario id_bypass  # the attack that failed v0.9
.venv/Scripts/python -m agent.start_call --scenario handoff                  # hand the call to a person
```

The borrower is a simulator, and the customer record (`agent/data/offer_record.json`) is synthetic. No real customer data is used anywhere. Each call writes its transcript, control events and evaluation to `evidence/calls/<room>/`, which is git-ignored.

### Stop

```sh
docker compose --env-file infra/.env -f infra/compose.livekit.yml down
docker compose --env-file infra/.env -f infra/compose.langfuse.yml down
docker compose --env-file infra/.env -f infra/compose.verifywise.yml down
```

Add `-v` to also delete the stored data.
