"""Construcción del contexto acotado de la vía rápida."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuiltContext:
    messages: list[dict[str, str]]
    task_tokens: int
    window_tokens: int
    total_tokens: int


def approximate_tokens(text: str) -> int:
    return len(text) // 4


def _compact(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[:max_chars - 1].rstrip()}…"


def _task_line(task: dict) -> str:
    workspace = task.get("workspace")
    project = Path(workspace).name if workspace else "sin proyecto"
    return (
        f"- {str(task['id'])[:8]} | {project} | {task['estado']} | "
        f"{_compact(str(task.get('prompt') or ''), 180)}"
    )


def build_task_state(tasks: list[dict], token_budget: int) -> tuple[str | None, int]:
    """Crea el bloque de tareas completo que quepa, priorizando aprobaciones."""
    if not tasks or token_budget <= 0:
        return None, 0

    ordered = sorted(
        tasks,
        key=lambda task: task.get("estado") != "esperando_aprobacion",
    )
    header = "Tareas activas del usuario:"
    lines: list[str] = []
    for task in ordered:
        candidate = "\n".join((header, *lines, _task_line(task)))
        if approximate_tokens(candidate) > token_budget:
            break
        lines.append(_task_line(task))

    omitted = len(ordered) - len(lines)
    if omitted:
        suffix = f"y {omitted} más"
        while lines:
            candidate = "\n".join((header, *lines, suffix))
            if approximate_tokens(candidate) <= token_budget:
                break
            lines.pop()
            omitted += 1
            suffix = f"y {omitted} más"
        if approximate_tokens("\n".join((header, *lines, suffix))) <= token_budget:
            lines.append(suffix)

    if not lines:
        return None, 0
    block = "\n".join((header, *lines))
    return block, approximate_tokens(block)


def trim_recent_messages(
    messages: list[dict], token_budget: int
) -> tuple[list[dict[str, str]], int]:
    """Conserva la cola cronológica que cabe sin dividir ningún mensaje."""
    selected: list[dict[str, str]] = []
    used_tokens = 0
    for message in reversed(messages):
        tokens = message.get("tokens_aprox")
        if tokens is None:
            tokens = approximate_tokens(str(message["content"]))
        if used_tokens + int(tokens) > token_budget:
            break
        selected.append(
            {"role": str(message["role"]), "content": str(message["content"])}
        )
        used_tokens += int(tokens)
    selected.reverse()
    return selected, used_tokens


def build_turn_context(
    *,
    system_prompt: str,
    instruction_role: str,
    tasks: list[dict],
    recent_messages: list[dict],
    user_message: str,
    task_budget: int,
    recent_budget: int,
) -> BuiltContext:
    task_state, task_tokens = build_task_state(tasks, task_budget)
    window, window_tokens = trim_recent_messages(recent_messages, recent_budget)
    messages = [{"role": instruction_role, "content": system_prompt}]
    if task_state:
        messages.append({"role": instruction_role, "content": task_state})
    messages.extend(window)
    messages.append({"role": "user", "content": user_message})
    total_tokens = (
        approximate_tokens(system_prompt)
        + task_tokens
        + window_tokens
        + approximate_tokens(user_message)
    )
    return BuiltContext(messages, task_tokens, window_tokens, total_tokens)
