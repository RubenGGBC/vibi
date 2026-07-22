# Claude Model Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each PWA-created Claude task select and retain its Claude model.

**Architecture:** The HTTP request carries a validated model ID into the task record. The worker reads that persisted value and supplies it to both Claude Agent SDK calls; the PWA sends the selected value from the Inbox composer.

**Tech Stack:** FastAPI, SQLite, Python unittest, React, TypeScript, Vitest.

## Global Constraints

- Allowed IDs: `claude-sonnet-5`, `claude-fable-5`, `claude-opus-4-8`, `claude-haiku-4-5`.
- Default: `claude-sonnet-5`.
- Existing tasks fall back to the default.
- Groq chat and Telegram message flow remain unchanged.

---

### Task 1: Persist and validate the task model

**Files:**
- Modify: `app/db.py`, `app/api.py`, `app/core/messages.py`, `app/tasks.py`, `app/executors/claude_agent.py`
- Modify: `tests/test_api.py`, `tests/test_messages.py`, `tests/test_telegram_core.py`

- [ ] Write failing API and worker tests for the default, valid values, invalid values, and passing the stored model to both SDK phases.
- [ ] Run the focused Python tests and confirm they fail because `modelo` is unsupported.
- [ ] Add the database field/migration fallback, Pydantic validation, task propagation, and `ClaudeAgentOptions(model=...)`.
- [ ] Run focused Python tests and then the complete Python suite.

### Task 2: Send the selected value from the PWA

**Files:**
- Modify: `frontend/src/pages/InboxPage.tsx`, `frontend/src/styles.css`
- Modify: `frontend/src/pages/InboxPage.test.tsx`

- [ ] Write a failing UI test that chooses Opus 4.8 and asserts the POST body has `modelo: "claude-opus-4-8"`.
- [ ] Run the focused Vitest file and confirm it fails because the selector does not exist.
- [ ] Add an accessible, Sonnet-5-default selector next to the new-task composer and include the selection in the mutation request.
- [ ] Run the focused Vitest file and the frontend build.
