# The-E-comm-Hacka

Offline-first conversational shopping agent for the TechJam Conversational E-Commerce Search Challenge.

## Local development setup

Download the official participant kit, verify its SHA256 checksum, and unpack its `data/` and `evaluator/` directories at the repository root. These official development artifacts are intentionally ignored by Git.

The verified participant-kit SHA256 used for the E0 baseline is:

```text
b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae
```

Run the official local evaluator with:

```bash
python3 -m evaluator.local_evaluator
```

The verified unmodified official starter baseline is E0, with `TechnicalScore = 0.106710`. See [docs/experiment_log.md](docs/experiment_log.md) for its environment checks and metrics.

## Repository layout

- `starter/agent.py` is the official entrypoint. It is the unmodified E0 baseline in the first experiment snapshot; the later D scaffold will make it re-export `src.agent.Agent`.
- `src/` will hold the team production package after the D scaffold.
- `docs/` contains the implementation plan, organizer Q&A, experiment log, and official reference documents.

The production Agent must remain offline-capable. Do not commit official data, evaluator outputs, model weights, embedding indexes, API keys, or secrets.
