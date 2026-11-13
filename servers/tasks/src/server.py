#!/usr/bin/env python3
"""tasks MCP server (sandbox-ai-mcp): a plan kept outside the model's context, for agents on small local models that
forget their goal after a compaction or a restart, or try the same failing thing again.

Tools:
    - set_goal, add_steps, remove_step: what to reach and the steps to get there
    - start_step, complete_step, block_step: progress, each with a short note
    - add_note: facts and mistakes not to repeat; they come back with next_step
    - next_step: the one step to work on now, with its context
    - list_steps, progress: the plan, compact

The plan is /work/.tasks/plan.json in the project folder (mounted writable at /work), written by this server only, with
a readable copy beside it, /work/.tasks/PLAN.md, for the human. Every change holds an exclusive lock (flock on
/work/.tasks/.lock), reads the plan, changes it and writes it through a temporary file renamed over the old one, so
several connections can share one plan. No tool takes a path; sizes are bounded; nothing else is read or written. No
network.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
import time

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

#: The project folder (mounted writable); the plan lives in its .tasks folder.
WORKSPACE = "/work"
#: Whether WORKSPACE must be a mount point (the image's own /work is an empty folder of the read-only root).
MOUNT_REQUIRED = True
FOLDER = ".tasks"
PLAN = "plan.json"
VIEW = "PLAN.md"
LOCK = ".lock"

STATES = ("todo", "doing", "done", "blocked")
MARKS = {"todo": "[ ]", "doing": "[>]", "done": "[x]", "blocked": "[!]"}
MAX_GOAL = 2000         # characters of the goal
MAX_STEP = 500          # characters of a step
MAX_NOTE = 1000         # characters of a note
MAX_STEPS = 200         # steps of a plan
MAX_ADD = 50            # steps added in one call
MAX_STEP_NOTES = 10     # notes kept per step (the oldest go)
MAX_NOTES = 100         # notes kept of the plan (the oldest go)
MAX_FILE = 4 << 20      # bytes of plan.json read at most
RECENT_NOTES = 5        # plan notes next_step shows
NOTE_PREVIEW = 120      # characters of a note in a list


class ArgumentError(ValueError):
    """A tool argument that is not accepted, or a plan that cannot be used; the text says why and what to do."""


# --- the store: /work/.tasks, locked, written atomically ---------------------------------------------------------------

def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def empty_plan() -> dict:
    return {"version": 1, "goal": "", "steps": [], "notes": [], "next_id": 1, "dropped_notes": 0, "updated": ""}


def workspace_root() -> str:
    root = os.path.realpath(WORKSPACE)
    if not os.path.isdir(root) or (MOUNT_REQUIRED and not os.path.ismount(WORKSPACE)):
        raise ArgumentError(f"no folder is mounted at {WORKSPACE}: add the server with --mount "
                            f"{WORKSPACE}=PROJECT:rw (the project folder; the plan goes to PROJECT/{FOLDER})")
    return root


def open_folder(create: bool) -> int | None:
    """A descriptor of /work/.tasks (made when CREATE), never through a symbolic link; None when it is not there."""
    root = os.open(workspace_root(), os.O_RDONLY | os.O_DIRECTORY)
    try:
        if create:
            try:
                os.mkdir(FOLDER, 0o755, dir_fd=root)
            except FileExistsError:
                pass
            except OSError as error:
                raise ArgumentError(f"cannot create {WORKSPACE}/{FOLDER} ({error.strerror}): mount the project "
                                    f"writable (--mount {WORKSPACE}=PROJECT:rw)") from None
        try:
            return os.open(FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        except FileNotFoundError:
            return None
        except OSError:
            raise ArgumentError(f"{WORKSPACE}/{FOLDER} is not a folder (a file or a symbolic link?): move it away") \
                from None
    finally:
        os.close(root)


def text_field(value, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("not a text")
    return value[:limit]


def checked_plan(data) -> dict:
    """DATA as a plan (every field checked and bounded), ValueError when it is not one."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("not a version 1 plan")
    plan = empty_plan()
    plan["goal"] = text_field(data.get("goal", ""), MAX_GOAL)
    plan["updated"] = text_field(data.get("updated", ""), 40)
    plan["dropped_notes"] = int(data.get("dropped_notes", 0) or 0)
    seen = set()
    steps = data.get("steps", [])
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError("steps: a list of at most %d" % MAX_STEPS)
    for step in steps:
        if not isinstance(step, dict) or isinstance(step.get("id"), bool) or not isinstance(step.get("id"), int) \
                or step["id"] < 1 or step["id"] in seen or step.get("state") not in STATES:
            raise ValueError("a step without a unique id or a known state")
        seen.add(step["id"])
        notes = step.get("notes", [])
        if not isinstance(notes, list):
            raise ValueError("step notes: a list")
        plan["steps"].append({"id": step["id"], "text": text_field(step.get("text", ""), MAX_STEP),
                              "state": step["state"], "updated": text_field(step.get("updated", ""), 40),
                              "notes": [checked_note(note) for note in notes][-MAX_STEP_NOTES:]})
    notes = data.get("notes", [])
    if not isinstance(notes, list):
        raise ValueError("notes: a list")
    plan["notes"] = [checked_note(note) for note in notes][-MAX_NOTES:]
    next_id = data.get("next_id", 1)
    if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id < 1:
        raise ValueError("next_id: a number")
    plan["next_id"] = max(next_id, max(seen, default=0) + 1)
    return plan


def checked_note(note) -> dict:
    if not isinstance(note, dict):
        raise ValueError("a note is {time, text}")
    return {"time": text_field(note.get("time", ""), 40), "text": text_field(note.get("text", ""), MAX_NOTE)}


def read_plan(folder: int | None) -> dict:
    if folder is None:
        return empty_plan()
    try:
        # O_NONBLOCK: a named pipe in its place must not hold this thread (and the lock) until someone writes
        fd = os.open(PLAN, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=folder)
    except FileNotFoundError:
        return empty_plan()
    except OSError:
        raise ArgumentError(f"{WORKSPACE}/{FOLDER}/{PLAN} cannot be read (a symbolic link?): move it away") from None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise ArgumentError(f"{WORKSPACE}/{FOLDER}/{PLAN} is not a plan file of at most {MAX_FILE >> 20} MiB: "
                                "move it away")
        data = handle.read(MAX_FILE + 1)
    try:
        return checked_plan(json.loads(data.decode("utf-8")))
    except (ValueError, UnicodeDecodeError, TypeError, OverflowError, RecursionError) as error:
        raise ArgumentError(f"{WORKSPACE}/{FOLDER}/{PLAN} is not a plan this server can read ({error}); it was changed "
                            f"by hand? Fix it, or move it away to start a new plan ({VIEW} beside it shows the last "
                            "state this server wrote)") from None


def write_file(folder: int, name: str, data: bytes) -> None:
    """DATA as NAME in FOLDER: a new temporary file, synced, renamed over NAME."""
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary, dir_fd=folder)
        raise


@contextlib.contextmanager
def plan_for(write: bool):
    """The plan, under the lock (exclusive to WRITE, shared to read); written back when WRITE and nothing failed."""
    folder = open_folder(create=write)
    lock = None
    try:
        if folder is not None:
            try:
                lock = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644, dir_fd=folder)
            except OSError:
                if write:
                    raise ArgumentError(f"cannot write {WORKSPACE}/{FOLDER}/{LOCK}: mount the project writable "
                                        f"(--mount {WORKSPACE}=PROJECT:rw)") from None
            if lock is not None:
                fcntl.flock(lock, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        plan = read_plan(folder)
        yield plan
        if write:
            plan["updated"] = now()
            try:
                write_file(folder, PLAN, (json.dumps(plan, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
                write_file(folder, VIEW, markdown(plan).encode("utf-8"))
                os.fsync(folder)
            except OSError as error:
                raise ArgumentError(f"the plan could not be saved in {WORKSPACE}/{FOLDER} ({error.strerror}); "
                                    "is the project mounted writable?") from None
    finally:
        if lock is not None:
            os.close(lock)  # releases the flock
        if folder is not None:
            os.close(folder)


# --- what the model and the human read -------------------------------------------------------------------------------

def one_line(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def counts(plan: dict) -> dict:
    found = dict.fromkeys(STATES, 0)
    for step in plan["steps"]:
        found[step["state"]] += 1
    return found


def progress_line(plan: dict) -> str:
    found = counts(plan)
    total = len(plan["steps"])
    text = f"{found['done']} of {total} steps done"
    if found["doing"]:
        text += f", {found['doing']} in progress"
    if found["blocked"]:
        text += f", {found['blocked']} blocked"
    return text


def step_line(step: dict, preview: bool = True) -> str:
    line = f"{step['id']}. {MARKS[step['state']]} {step['text']}"
    if preview and step["notes"]:
        line += f"  -- {one_line(step['notes'][-1]['text'], NOTE_PREVIEW)}"
    return line


def compact(plan: dict) -> str:
    if not plan["goal"] and not plan["steps"]:
        return "No plan yet. Start with set_goal, then add_steps."
    lines = [f"Goal: {plan['goal'] or '(none: set_goal)'}", f"Progress: {progress_line(plan)}"]
    lines += [step_line(step) for step in plan["steps"]]
    if not plan["steps"]:
        lines.append("No steps yet: add_steps.")
    lines.append("Marks: [ ] to do, [>] in progress, [x] done, [!] blocked")
    return "\n".join(lines)


def markdown(plan: dict) -> str:
    lines = ["<!-- Written by the tasks MCP server from plan.json; changes here are overwritten. -->", "# Plan", "",
             f"**Goal:** {plan['goal'] or '(none)'}", "",
             f"**Progress:** {progress_line(plan)} (updated {plan['updated']})", "", "## Steps", ""]
    for step in plan["steps"]:
        box = {"todo": "[ ]", "doing": "[ ]", "done": "[x]", "blocked": "[ ]"}[step["state"]]
        label = {"todo": "", "doing": " **(in progress)**", "done": "", "blocked": " **(blocked)**"}[step["state"]]
        lines.append(f"- {box} {step['id']}. {step['text']}{label}")
        for note in step["notes"]:
            lines.append(f"  - {note['time']}: {one_line(note['text'], MAX_NOTE)}")
    if not plan["steps"]:
        lines.append("(no steps)")
    lines += ["", "## Notes", ""]
    if plan["dropped_notes"]:
        lines.append(f"({plan['dropped_notes']} older notes were dropped)")
    lines += [f"- {note['time']}: {one_line(note['text'], MAX_NOTE)}" for note in plan["notes"]] or ["(none)"]
    return "\n".join(lines) + "\n"


def find_step(plan: dict, number) -> dict:
    if isinstance(number, bool) or not isinstance(number, int):
        raise ArgumentError("step: the step's number, as list_steps shows it")
    for step in plan["steps"]:
        if step["id"] == number:
            return step
    numbers = ", ".join(str(s["id"]) for s in plan["steps"]) or "none yet"
    raise ArgumentError(f"step: there is no step {number} (steps: {numbers}; list_steps shows them)")


def checked_text(value, what: str, limit: int, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ArgumentError(f"{what}: a text")
    text = value.replace("\r\n", "\n").strip()
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    if required and not text:
        raise ArgumentError(f"{what}: must not be empty")
    if len(text) > limit:
        raise ArgumentError(f"{what}: at most {limit} characters (this one has {len(text)}); keep it short")
    return text


def add_note_to(notes: list, text: str, limit: int) -> int:
    """TEXT appended to NOTES, the oldest dropped beyond LIMIT; how many were dropped."""
    notes.append({"time": now(), "text": text})
    dropped = max(0, len(notes) - limit)
    del notes[:dropped]
    return dropped


def next_text(plan: dict) -> str:
    """The one step to work on now, with what the model needs to know for it."""
    if not plan["goal"] and not plan["steps"]:
        return "No plan yet. Call set_goal with what the user wants, then add_steps with the steps to get there."
    steps = plan["steps"]
    doing = [s for s in steps if s["state"] == "doing"]
    todo = [s for s in steps if s["state"] == "todo"]
    blocked = [s for s in steps if s["state"] == "blocked"]
    lines = [f"Goal: {plan['goal'] or '(none: set_goal)'}", f"Progress: {progress_line(plan)}"]
    current = doing[0] if doing else todo[0] if todo else None
    if current is None:
        if blocked:
            lines.append("Only blocked steps are left:")
            for step in blocked:
                reason = step["notes"][-1]["text"] if step["notes"] else "no reason given"
                lines.append(f"  {step['id']}. {step['text']}  -- blocked: {one_line(reason, 300)}")
            lines.append("Solve what blocks one (then start_step), change the plan (add_steps, remove_step), or tell "
                         "the user what you need.")
        elif steps:
            lines.append("All steps are done. Check that the goal is really met (run the tests, look at the result); "
                         "then report to the user. More to do: add_steps.")
        else:
            lines.append("No steps yet: add_steps with the steps to reach the goal.")
    else:
        verb = "Continue with" if current["state"] == "doing" else "Next"
        lines.append(f"{verb} step {current['id']}: {current['text']}")
        for note in current["notes"]:
            lines.append(f"  note ({note['time']}): {one_line(note['text'], 400)}")
        if current["state"] == "todo":
            lines.append(f"Call start_step({current['id']}) when you begin, complete_step({current['id']}, note) when "
                         "it is done, block_step if you cannot go on.")
        else:
            lines.append(f"When it is done: complete_step({current['id']}, note). Stuck: block_step({current['id']}, "
                         "reason).")
        if len(doing) > 1:
            lines.append("Also in progress: " + ", ".join(f"{s['id']}. {one_line(s['text'], 60)}" for s in doing[1:]))
        done = [s for s in steps if s["state"] == "done"]
        if done:
            last = done[-1]
            result = f"  -- {one_line(last['notes'][-1]['text'], 300)}" if last["notes"] else ""
            lines.append(f"Done before: {last['id']}. {one_line(last['text'], 120)}{result}")
        later = [s for s in todo if s is not current][:3]
        if later:
            lines.append("After that: " + "; ".join(f"{s['id']}. {one_line(s['text'], 80)}" for s in later)
                         + (" ..." if len(todo) - (current in todo) > 3 else ""))
        if blocked:
            lines.append("Blocked: " + ", ".join(str(s["id"]) for s in blocked))
    if plan["notes"]:
        lines.append("Notes to keep in mind (newest last):")
        lines += [f"  - {one_line(note['text'], 300)}" for note in plan["notes"][-RECENT_NOTES:]]
    return "\n".join(lines)


def progress_text(plan: dict) -> str:
    if not plan["goal"] and not plan["steps"]:
        return "No plan yet. Start with set_goal, then add_steps."
    lines = [f"Goal: {plan['goal'] or '(none: set_goal)'}", f"Progress: {progress_line(plan)}"
             + (f" (updated {plan['updated']})" if plan["updated"] else "")]
    for state, title in (("done", "Done"), ("doing", "In progress"), ("blocked", "Blocked"), ("todo", "To do")):
        steps = [s for s in plan["steps"] if s["state"] == state]
        if not steps:
            continue
        lines.append(f"{title}:")
        for step in steps:
            last = f"  -- {one_line(step['notes'][-1]['text'], 200)}" if step["notes"] and state != "todo" else ""
            lines.append(f"  {step['id']}. {one_line(step['text'], 160)}{last}")
    if plan["notes"]:
        lines.append(f"Notes: {len(plan['notes'])}, the last: {one_line(plan['notes'][-1]['text'], 200)}")
    return "\n".join(lines)


def split_steps(steps) -> list[str]:
    """STEPS as a list of texts: a list, or one text with a step per line (leading numbers and bullets dropped)."""
    if isinstance(steps, str):
        items = [re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\[[ xX]?\]\s+)+", "", line) for line in steps.splitlines()]
    elif isinstance(steps, list):
        items = steps
    else:
        raise ArgumentError("steps: a list of short texts, one per step")
    texts = [checked_text(item, "steps", MAX_STEP, required=False) for item in items]
    texts = [text for text in texts if text]
    if not texts:
        raise ArgumentError("steps: give at least one step, e.g. [\"read the failing test\", \"fix the parser\"]")
    if len(texts) > MAX_ADD:
        raise ArgumentError(f"steps: at most {MAX_ADD} in one call; keep the plan short and add more later")
    return texts


# --- the MCP server --------------------------------------------------------------------------------------------------

mcp = FastMCP("tasks-mcp", instructions=(
    "Keeps your plan outside your context, in /work/.tasks of the project, so it survives a restart or a compacted "
    "context. At the start of the work, and whenever you are unsure what to do next, call next_step. Plan with "
    "set_goal and add_steps (short steps you can check). Mark progress: start_step, complete_step with a short note "
    "of what you did, block_step with the reason. Write down facts you will need again and mistakes not to repeat "
    "with add_note: next_step shows them."))

CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
REMOVES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
READS = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


async def in_thread(function, *args) -> str:
    return await asyncio.to_thread(function, *args)


def do_set_goal(goal, clear_steps) -> str:
    text = checked_text(goal, "goal", MAX_GOAL)
    if not isinstance(clear_steps, bool):
        raise ArgumentError("clear_steps: true or false")
    with plan_for(write=True) as plan:
        old = plan["goal"]
        plan["goal"] = text
        removed = len(plan["steps"]) if clear_steps else 0
        if clear_steps:
            plan["steps"] = []
        if old and old != text:
            add_note_to(plan["notes"], f"Goal changed from: {one_line(old, 300)}", MAX_NOTES)
        listing = compact(plan)
    said = "Goal set." + (f" {removed} old steps removed." if removed else "")
    hint = "\nNext: add_steps with the steps to reach it." if not plan["steps"] else ""
    return f"{said}\n{listing}{hint}"


def do_add_steps(steps, after_step) -> str:
    texts = split_steps(steps)
    with plan_for(write=True) as plan:
        if len(plan["steps"]) + len(texts) > MAX_STEPS:
            raise ArgumentError(f"the plan would have more than {MAX_STEPS} steps: remove done or unneeded ones first")
        position = len(plan["steps"])
        if after_step is not None and after_step != 0:
            target = find_step(plan, after_step)
            position = plan["steps"].index(target) + 1
        elif after_step == 0:
            position = 0
        new = []
        for text in texts:
            new.append({"id": plan["next_id"], "text": text, "state": "todo", "updated": now(), "notes": []})
            plan["next_id"] += 1
        plan["steps"][position:position] = new
        listing = compact(plan)
    numbers = ", ".join(str(step["id"]) for step in new)
    return f"Added step{'s' if len(new) > 1 else ''} {numbers}.\n{listing}"


def change_state(number, state: str, note, *, note_required: bool = False) -> str:
    text = checked_text(note, "reason" if note_required else "note", MAX_NOTE, required=note_required)
    with plan_for(write=True) as plan:
        step = find_step(plan, number)
        before = step["state"]
        step["state"] = state
        step["updated"] = now()
        if text:
            add_note_to(step["notes"], text, MAX_STEP_NOTES)
        others = [s["id"] for s in plan["steps"] if s["state"] == "doing" and s is not step]
        follow = next_text(plan) if state in ("done", "blocked") else None
    if state == "doing":
        said = f"Step {number} is in progress: {step['text']}"
        if before == "done":
            said += " (it was done; reopened)"
        if others:
            said += f"\nNote: also in progress: {', '.join(map(str, others))}. Finish or block them too."
        said += f"\nWhen it is done: complete_step({number}, note)."
        return said
    if state == "done":
        return f"Step {number} done.\n{follow}"
    return f"Step {number} blocked: {text}\n{follow}"


def do_add_note(text, step) -> str:
    note = checked_text(text, "text", MAX_NOTE)
    with plan_for(write=True) as plan:
        if step is not None:
            target = find_step(plan, step)
            add_note_to(target["notes"], note, MAX_STEP_NOTES)
            return f"Note added to step {step}."
        plan["dropped_notes"] += add_note_to(plan["notes"], note, MAX_NOTES)
        count = len(plan["notes"])
    return f"Note added ({count} notes; next_step shows the last {RECENT_NOTES})."


def do_remove_step(step) -> str:
    with plan_for(write=True) as plan:
        target = find_step(plan, step)
        plan["steps"].remove(target)
        listing = compact(plan)
    return f"Step {step} removed: {target['text']}\n{listing}"


def do_read(render) -> str:
    with plan_for(write=False) as plan:
        return render(plan)


@mcp.tool(annotations=CHANGES, structured_output=False)
async def set_goal(goal: str, clear_steps: bool = False) -> str:
    """Set the goal of the work: what the user wants, in one or two sentences. It stays when your context is reset.

    Args:
        goal: the goal, e.g. "the CSV export handles quotes and all tests pass"
        clear_steps: true removes all steps of the old plan (default false: they stay)
    """
    return await in_thread(do_set_goal, goal, clear_steps)


@mcp.tool(annotations=CHANGES, structured_output=False)
async def add_steps(steps: list[str] | str, after_step: int | None = None) -> str:
    """Add steps to the plan: short, checkable actions in the order you will do them.

    Args:
        steps: the steps, e.g. ["find where the CSV is written", "add quoting", "run the tests"]
        after_step: insert them after this step number (0: at the start; default: at the end)
    """
    return await in_thread(do_add_steps, steps, after_step)


@mcp.tool(annotations=READS, structured_output=False)
async def list_steps() -> str:
    """Show the goal and every step with its state, compactly."""
    return await in_thread(do_read, compact)


@mcp.tool(annotations=CHANGES, structured_output=False)
async def start_step(step: int, note: str = "") -> str:
    """Mark a step as in progress (also to reopen a done or blocked one).

    Args:
        step: the step's number
        note: optional, e.g. how you will do it
    """
    return await in_thread(change_state, step, "doing", note)


@mcp.tool(annotations=CHANGES, structured_output=False)
async def complete_step(step: int, note: str = "") -> str:
    """Mark a step as done, with a short note of what you did or found. Returns the next step.

    Args:
        step: the step's number
        note: what was done, e.g. "quoting added in csv.py write_row; 12 tests pass"
    """
    return await in_thread(change_state, step, "done", note)


@mcp.tool(annotations=CHANGES, structured_output=False)
async def block_step(step: int, reason: str) -> str:
    """Mark a step as blocked, with the reason, so that you do not try the same thing again. Returns the next step.

    Args:
        step: the step's number
        reason: why you cannot go on, e.g. "needs network to install foo; asked the user"
    """
    return await in_thread(change_state, step, "blocked", reason, note_required=True)


@mcp.tool(annotations=CHANGES, structured_output=False)
async def add_note(text: str, step: int | None = None) -> str:
    """Write down a fact you will need again, or a mistake not to repeat. next_step shows the latest notes.

    Args:
        text: the note, e.g. "tests need PYTHONPATH=src" or "do not edit generated.py: it is rebuilt"
        step: attach it to this step instead of the plan (optional)
    """
    return await in_thread(do_add_note, text, step)


@mcp.tool(annotations=READS, structured_output=False)
async def next_step() -> str:
    """The one step to work on now, with the goal, its notes, what was done before and the notes to keep in mind.

    Call it at the start, after a restart, and whenever you are unsure what to do next.
    """
    return await in_thread(do_read, next_text)


@mcp.tool(annotations=READS, structured_output=False)
async def progress() -> str:
    """A short summary: the goal, the steps done (with their notes), in progress, blocked and still to do."""
    return await in_thread(do_read, progress_text)


@mcp.tool(annotations=REMOVES, structured_output=False)
async def remove_step(step: int) -> str:
    """Remove a step that is not needed any more (the plan changed).

    Args:
        step: the step's number
    """
    return await in_thread(do_remove_step, step)


if __name__ == "__main__":
    mcp.run("stdio")
