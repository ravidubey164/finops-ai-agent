#!/usr/bin/env python3
"""PreToolUse hook: deny Azure CLI commands that are not on the read-only allow-list."""

from __future__ import annotations

import json
import re
import shlex
import sys

SHELL_OPERATORS = {"|", "||", "&&", ";", ">", ">>", "&"}

# Everything else must go through scripts/azure_read.py. The wrapper spawns `az` itself
# rather than through a terminal tool, so this hook never sees the wrapper's own calls.
ALLOWED_AZ_PATHS = (
    ("login",),
    ("logout",),
    ("version",),
    ("account", "show"),
    ("account", "list"),
)


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    print(reason, file=sys.stderr)
    raise SystemExit(2)


def tokenize(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=True)
    except ValueError:
        return re.split(r"\s+", command.strip())


def az_argument_lists(tokens: list[str]) -> list[list[str]]:
    return [
        tokens[index + 1 :]
        for index, token in enumerate(tokens)
        if token == "az" or token.endswith("/az") or token.lower().endswith("\\az.cmd")
    ]


def command_path(arguments: list[str]) -> tuple[str, ...]:
    path = []
    for argument in arguments:
        if argument in SHELL_OPERATORS:
            break
        if not argument.startswith("-"):
            path.append(argument.lower())
    return tuple(path)


def check(command: str) -> None:
    for arguments in az_argument_lists(tokenize(command)):
        path = command_path(arguments)
        if not path:
            continue  # flag-only invocation such as `az --version`
        if any(path[: len(allowed)] == allowed for allowed in ALLOWED_AZ_PATHS):
            continue
        deny(
            f"Blocked `az {' '.join(path)}`. This repository is read-only: use "
            "scripts/azure_read.py and never create, modify, scale, restart, or delete "
            "an Azure resource."
        )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        raise SystemExit(0)

    if payload.get("hook_event_name") not in (None, "PreToolUse"):
        raise SystemExit(0)

    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = tool_input.get("command") or tool_input.get("commandLine")
    if isinstance(command, str) and command.strip():
        check(command)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
