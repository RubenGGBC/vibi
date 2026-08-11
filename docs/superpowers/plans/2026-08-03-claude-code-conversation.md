# Claude Code Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. The user explicitly requested implementation without tests.

**Goal:** Replace the Groq/router conversation path with a resumable Claude Code Haiku 4.5 session that can use the terminal and Vibi tools, with persistent Thinking and per-message tool attachments in chat.

**Architecture:** Each active Vibi conversation stores its Claude session id and Thinking state. A focused Claude chat executor starts or resumes that SDK session, exposes enabled Vibi tools through an in-process MCP server, and runs directly with Claude Code file and terminal tools. PWA, Telegram, and transcribed voice share the same core path.

**Tech Stack:** FastAPI, SQLite, Claude Agent SDK, SDK MCP tools, React, React Query, TypeScript.

## Global Constraints

- Use `claude-haiku-4-5` for conversational Claude Code sessions.
- Groq remains only for speech-to-text.
- Do not route conversational requests through Groq or the task plan/approval flow.
- Permit direct Claude Code terminal and editing tools.
- Thinking remains in its selected state until the user toggles it again.
- Do not add or run automated tests at the user's request; verify only Python syntax and frontend type/build checks.
- Preserve unrelated local changes in the dirty worktree.

---

### Task 1: Persist conversation runtime state

**Files:**
- Modify: `app/db.py`
- Modify: `app/api.py`
- Modify: `frontend/src/types.ts`

**Interfaces:**
- Produces: conversation fields `claude_session_id` and `thinking_enabled`.
- Produces: `db.update_conversation_session(...)` and `db.set_conversation_thinking(...)`.
- Produces: authenticated endpoint for updating the active conversation's Thinking state.

- [ ] Add idempotent SQLite columns and migrations.
- [ ] Include Thinking state in conversation page/reset responses and preserve it across reset.
- [ ] Add the API model and endpoint that updates Thinking immediately.
- [ ] Extend the frontend conversation type.

### Task 2: Add the resumable Claude Code chat executor

**Files:**
- Create: `app/executors/claude_chat.py`
- Modify: `app/tools.py`

**Interfaces:**
- Consumes: the visible tool catalog and `tools.execute(tool_id, user, arguments)`.
- Produces: `claude_chat.respond(user, text, origin, client_ref, attached_tool_ids)` returning response text and artifacts.

- [ ] Build dynamic SDK MCP tools from enabled system, personal, and lab tools, removing pre-bound fields from their exposed input schemas.
- [ ] Start or resume a Claude SDK session using the stored id, Haiku 4.5, direct Read/Write/Edit/Glob/Grep/Bash/Web tools, and the active Thinking setting.
- [ ] Capture the final text, new session id, and artifacts created or located by Vibi tools.
- [ ] Serialize tool results only for Claude's internal tool response; never return raw JSON as the conversational answer.
- [ ] Serialize turns per conversation so concurrent devices do not resume the same session simultaneously.

### Task 3: Replace conversational routing

**Files:**
- Modify: `app/core/messages.py`
- Modify: `app/api.py`

**Interfaces:**
- Consumes: optional `tool_ids` from the PWA request.
- Produces: all normal chat, Telegram, and voice turns through the Claude chat executor.

- [ ] Remove router/Groq/task dispatch from normal messages while retaining explicit `/skill` compatibility.
- [ ] Pass attached tool ids from `/api/mensaje` to the core.
- [ ] Keep voice transcription on Groq Whisper, then send the transcript to the same Claude conversation.
- [ ] Preserve existing response shapes for text and downloadable artifacts.

### Task 4: Add Thinking and tool attachments to chat

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/styles/console.css`

**Interfaces:**
- Consumes: `/api/herramientas`, active conversation `thinking_enabled`, and the Thinking update endpoint.
- Produces: `tool_ids` on each chat message.

- [ ] Replace the obsolete Claude task model picker with a fixed `Claude Code · Haiku 4.5` runtime label.
- [ ] Add an accessible persistent Thinking switch with optimistic feedback.
- [ ] Add a compact tool picker and removable attachment chips; clear attachments after a successful send.
- [ ] Preserve responsive layout, keyboard focus, and reduced-motion behavior.

### Task 5: Align configuration and documentation

**Files:**
- Modify: `app/ai_providers.py`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `README.md`

**Interfaces:**
- Produces: settings copy that identifies Claude Code Haiku as the fixed conversation runtime and Groq as speech-only.

- [ ] Change new-user conversation defaults to Anthropic Haiku without affecting tool inference or the legacy task agent settings.
- [ ] Make the conversation lane read-only in Settings so it cannot claim Groq controls chat.
- [ ] Document persistent Claude sessions, direct terminal access, Thinking, tool selection, and Groq's remaining speech role.

### Task 6: Non-test verification

**Files:** none.

- [ ] Compile changed Python modules with `python -m compileall app`.
- [ ] Run frontend TypeScript/build checks without Vitest.
- [ ] Review `git diff --check` and the scoped diff for accidental edits.
