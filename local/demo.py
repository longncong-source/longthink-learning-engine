"""MVP end-to-end demo - exact scenario from FIRST_SECOND_BRAIN.md section 27.

Proves the full loop on one laptop:
    Local -> Cloud Memory (store) -> Local (retrieve) -> Reason -> Store decision
    -> Retrieve again and verify the new decision is found.

Runs with any local LLM; without one it degrades to deterministic extractive mode
while still exercising the complete memory path.
"""

from __future__ import annotations

import re

from local.agent import FirstBrainAgent, TaskInput, confirm_action
from local.llm import BaseChatLLM
from local.memory_client import SecondBrainClient

PROJECT_NAME = "LNG Project"

MEMORY_VENDOR_DELAY = "Vendor A delayed mechanical drawing approval by 21 days."
LESSON_REVIEW_FIRST = "Engineering document review must start before procurement."
DEFAULT_DECISION = "We decided to require vendor drawings 14 days before procurement."

QUESTION_1 = "What happened previously with mechanical drawing delays?"
QUESTION_2 = "What is our rule for vendor drawings?"


def _banner(text: str) -> None:
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def _print_result(result) -> None:  # type: ignore[no-untyped-def]
    for step in result.steps:
        preview = step.output if len(step.output) <= 160 else step.output[:157] + "..."
        print(f"  [{step.phase:<8}] {preview}")
    print(f"  memories used: {result.memories_used} | verified: {result.verified}")


def run_demo(
    *,
    client: SecondBrainClient,
    llm: BaseChatLLM | None = None,
    auto_yes: bool = True,
    offline_ok: bool = False,
    decision_text: str | None = None,
) -> int:
    """Execute spec section 27 steps 1-10. Returns process exit code."""
    agent = FirstBrainAgent(client, llm=llm)

    _banner("FIRST BRAIN + SECOND BRAIN - MVP DEMO (spec section 27)")
    health = client.health()
    online = health is not None
    llm_mode = getattr(agent.llm, "online", False) and "online LLM" or "offline extractive fallback"
    print(f"Second Brain API : {'ONLINE' if online else 'UNREACHABLE'}")
    print(f"LLM mode         : {llm_mode}")

    if not online:
        if not offline_ok:
            print("\nSecond Brain is not reachable. Start it first:")
            print("  .\\.venv\\Scripts\\python.exe -m uvicorn cloud.app.main:app --port 8100")
            print("(or run with --offline-ok to demonstrate queueing without the cloud)")
            return 2
        print("Offline mode enabled: writes will be queued locally and synced later.")

    project_id: str | None = None
    if online:
        project_id = client.ensure_project(PROJECT_NAME, description="MVP demo project")
        print(f"[STEP 1/10] project ready: {PROJECT_NAME} ({project_id})")
    else:
        print("[STEP 1/10] skipped (offline): project will resolve after sync")

    # STEP 2-3: store memory + lesson
    for label, step_no, text, mtype, importance in (
        ("memory", "2", MEMORY_VENDOR_DELAY, "episodic", 0.75),
        ("lesson", "3", LESSON_REVIEW_FIRST, "lesson", 0.70),
    ):
        outcome = client.write_memory(
            title=text[:120],
            content=text,
            type=mtype,
            importance=importance,
            confidence=0.9,
            source="demo-seed",
            project_id=project_id,
            allow_cloud=True,
        )
        print(f"[STEP {step_no}/10] store {label}: {outcome.status}"
              + (f" id={outcome.memory_id}" if outcome.memory_id else ""))
        print(f'              "{text}"')

    # STEP 4-7: ask First Brain, it searches Second Brain and answers
    _banner(f"USER: {QUESTION_1}")
    result1 = agent.run(TaskInput(question=QUESTION_1, project_id=project_id, store_result=False))
    _print_result(result1)
    print(f"\nANSWER:\n{result1.answer}\n")

    # STEP 8-9: user provides a new decision -> confirm -> store
    decision = decision_text or DEFAULT_DECISION
    if auto_yes:
        approved = True
    else:
        approved = confirm_action(f'Store this as a DECISION?\n  "{decision}"')
    if not approved:
        print("[STEP 8/10] rejected by user - skipping decision storage")
        return 1

    kind, importance, outcome = agent.store_knowledge(
        decision, kind="decision", importance=0.85, project_id=project_id, allow_cloud=True
    )
    print(f"[STEP 8/10] classified as {kind} (importance={importance:.2f})")
    print(f"[STEP 9/10] stored decision: {outcome.status}"
          + (f" id={outcome.memory_id}" if outcome.memory_id else ""))
    if outcome.status == "queued":
        print("             queued offline - run 'brain sync' when the cloud returns")

    # STEP 10: verify retrievability of the new decision
    _banner(f"VERIFYING: {QUESTION_2}")
    search = client.search(QUESTION_2, project_id=project_id)
    results = search.get("results", [])
    pattern = re.compile(r"14\s*days", re.IGNORECASE)
    hit = next((r for r in results if pattern.search(f"{r.get('title','')} {r.get('content','')}")), None)

    print(f"results returned : {len(results)}")
    if results:
        top = results[0]
        print(f"top result       : ({top.get('type')}, score={top.get('score')}) {top.get('title')}")
    if hit:
        print(f"\n[PASS] New decision retrievable: \"{hit.get('title')}\" score={hit.get('score')}")
        return 0
    print("\n[FAIL] The newly stored decision was NOT retrievable.")
    if not online:
        print("(expected while fully offline: run 'brain sync', then re-run the demo)")
    return 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="First/Second Brain MVP demo (spec section 27)")
    parser.add_argument("--yes", action="store_true", help="auto-approve human-in-the-loop prompts")
    parser.add_argument("--ask", action="store_true", help="prompt for confirmation interactively")
    parser.add_argument("--offline-ok", action="store_true", help="run even when the Memory API is down")
    parser.add_argument(
        "--decision",
        default=None,
        help="override the decision text used in step 8",
    )
    args = parser.parse_args()

    from local.config import get_brain_settings
    from local.llm import get_chat_llm

    settings = get_brain_settings()
    client = SecondBrainClient(settings)
    llm = get_chat_llm(settings)
    return run_demo(
        client=client,
        llm=llm,
        auto_yes=not args.ask,
        offline_ok=args.offline_ok,
        decision_text=args.decision,
    )


if __name__ == "__main__":
    raise SystemExit(main())
