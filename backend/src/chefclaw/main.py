"""Uvicorn entrypoint.

Exactly ONE uvicorn worker process — a hard constraint of the no-broker
design, not a tuning knob (CLAUDE.md, Key Design Decisions): the in-process
asyncio job worker claims jobs via FOR UPDATE SKIP LOCKED and executes them
strictly serially; the double-spend race is only closed at concurrency 1.
"""

import os

import uvicorn

from chefclaw.app import create_app

app = create_app()


def run() -> None:
    host = os.environ.get("CHEFCLAW_HOST", "127.0.0.1")
    port = int(os.environ.get("CHEFCLAW_PORT", "8000"))
    uvicorn.run("chefclaw.main:app", host=host, port=port, workers=1)


if __name__ == "__main__":
    run()
