from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from .config import load_settings
from .providers import _codex_call, _command, _post_chat, _run_command, discover_all, smoke_record
from .registry import ModelRecord, load_registry, save_registry
from .runner import ClientBundle, orchestrate


REGISTRY_PATH = Path(__file__).with_name("models.json")


def _record_dicts(records: list[ModelRecord]) -> list[dict]:
    return [record.to_dict() for record in records]


def _build_clients(records: list[dict], settings) -> ClientBundle:
    gemini_settings = replace(settings, timeout=max(settings.timeout, 90.0))

    def gemini(system: str, user: str) -> str:
        record = next(record for record in records if record.get("model") == "Gemini 3.8 Flash")
        return _post_chat(gemini_settings, record["exact_id"], [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

    specialists = {}
    for record in records:
        if not record.get("verified") or not record.get("exact_id") or record.get("model") == "Gemini 3.8 Flash":
            continue
        if record.get("provider") == "APInex":
            specialists[record["exact_id"]] = lambda item, record=record: _post_chat(
                settings,
                record["exact_id"],
                [{"role": "user", "content": item["instruction"]}],
            )
        elif record.get("provider") == "OpenCode Go":
            specialists[record["exact_id"]] = lambda item, record=record: _run_command(_command("opencode") + [
                "run", "--format", "json", "--model", record["exact_id"], item["instruction"],
            ], timeout=max(settings.timeout, 90.0))[1]
        elif record.get("provider") == "Codex / OpenAI":
            specialists[record["exact_id"]] = lambda item, record=record: _codex_call(
                "codex", record["exact_id"], item["instruction"], settings.timeout,
            )
    return ClientBundle(gemini=gemini, specialists=specialists)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal multi-model task orchestrator")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("discover", help="discover exact provider model IDs")
    subparsers.add_parser("smoke-test", help="smoke-test discovered callable providers")
    run_parser = subparsers.add_parser("run", help="route an arbitrary task through Gemini")
    run_parser.add_argument("task")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in {"discover", "smoke-test", "run", "-h", "--help"}:
        print(json.dumps({"status": "error", "error": "unknown command"}))
        return 2
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    settings = load_settings(Path.cwd())
    try:
        if args.command == "discover":
            records = discover_all(settings)
            save_registry(REGISTRY_PATH, records)
            print(json.dumps({"status": "ok", "records": _record_dicts(records)}, indent=2))
            return 0
        if args.command == "smoke-test":
            records = load_registry(REGISTRY_PATH)
            if not records:
                records = _record_dicts(discover_all(settings))
            updated = [
                smoke_record(ModelRecord(**record), settings)
                if record.get("exact_id") and record.get("transport") != "ui-only"
                else ModelRecord(**record)
                for record in records
            ]
            save_registry(REGISTRY_PATH, updated)
            print(json.dumps({"status": "ok", "records": _record_dicts(updated)}, indent=2))
            return 0
        if args.command == "run":
            result = orchestrate(args.task, REGISTRY_PATH, settings, _build_clients(load_registry(REGISTRY_PATH), settings))
            print(json.dumps(result, indent=2))
            return 0
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)[:500]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
