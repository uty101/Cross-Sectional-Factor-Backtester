"""The one harness every agent runs through (BUILD_PLAN step 11.1).

    run_agent(name, system_prompt, user_prompt, toolbox, ...) -> dict

A manual tool loop on the Messages API: the model is called, every
``tool_use`` block is executed through the ``Toolbox`` (which enforces
the allowlists), the results go back, and the loop ends on ``end_turn``
or after ``max_turns``. Every run is written to
``decisions/<agent>/<timestamp>.json`` with the model, the sha256 of the
system prompt, the user prompt, every tool call with its input and
output, and the final text. A tool that raises returns its error to the
model as ``is_error`` and is logged the same way; it never stops the run.

The client is injectable so the test suite runs on a scripted fake and
never touches the network. The model comes from ``FB_AGENT_MODEL`` and
defaults to ``claude-opus-5``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from backtester.agents.tools import Toolbox, stamp

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


def run_agent(
    name: str,
    system_prompt: str,
    user_prompt: str,
    toolbox: Toolbox,
    *,
    tool_names: list[str] | None = None,
    web_search: bool = False,
    max_turns: int = 20,
    client: Any = None,
    model: str | None = None,
) -> dict:
    """Run one agent to completion and log it. Returns the log record."""
    model = model or os.environ.get("FB_AGENT_MODEL", DEFAULT_MODEL)
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    tools = {t.name: t for t in toolbox.tools(tool_names)}
    specs: list[dict] = [t.spec() for t in tools.values()]
    if web_search:
        specs.append(WEB_SEARCH)

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    calls: list[dict] = []
    final_text = ""
    stop_reason = "max_turns"
    for _ in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=specs,
            messages=messages,
        )
        text = [b.text for b in response.content if b.type == "text"]
        uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        if not uses:
            final_text = "\n".join(text)
            stop_reason = response.stop_reason
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for u in uses:
            out, err = _execute(tools, u.name, u.input)
            calls.append(
                {"tool": u.name, "input": u.input, "output": out, "is_error": err}
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": u.id,
                    "content": out,
                    "is_error": err,
                }
            )
        messages.append({"role": "user", "content": results})

    record = {
        "agent": name,
        "timestamp": stamp(),
        "model": model,
        "system_prompt_sha": hashlib.sha256(system_prompt.encode()).hexdigest(),
        "user_prompt": user_prompt,
        "tool_calls": calls,
        "final_output": final_text,
        "stop_reason": stop_reason,
    }
    _log(toolbox.root, name, record)
    return record


def _execute(tools: dict, name: str, inputs: dict) -> tuple[str, bool]:
    """Run one tool; an exception becomes an error result for the model."""
    tool = tools.get(name)
    if tool is None:
        return f"unknown tool {name}", True
    try:
        return str(tool.fn(**inputs)), False
    except Exception as e:  # noqa: BLE001 - the model gets the text, the log the flag
        return f"{type(e).__name__}: {e}", True


def _log(root: Path, name: str, record: dict) -> Path:
    d = root / "decisions" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['timestamp']}.json"
    p.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    return p
