# Vibi Local UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the complete local Vibi console so every route shares the visual identity of the approved red, black, white, tilted-hat companion.

**Architecture:** Preserve the existing React route tree and data contracts. Add one final, explicit design-system stylesheet for cross-route consistency, then make only the small semantic markup changes required in `AppShell` and `LoginPage` to expose the Vibi brand and actual SVG rig.

**Tech Stack:** React 19, TypeScript 6, CSS, SVG DOM rig, Vitest/Testing Library, Vite, Tauri 2.

**Spec:** `docs/superpowers/specs/2026-08-30-vibi-local-ui-redesign-design.md`

## Global Constraints

- Preserve all current routes, API calls, mutations, cache keys and user flows.
- Use `#ff1026` as the only primary interactive accent; purple may exist only as faint ambient background light.
- Use the existing Vibi companion rig; do not draw a second mascot.
- Respect visible keyboard focus and `prefers-reduced-motion`.
- Keep the installed companion window and its approved artwork unchanged.
- Preserve unrelated worktree changes.

---

### Task 1: Lock the new shell and login semantics with tests

**Files:**
- Modify: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/pages/LoginPage.test.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`

**Interfaces:**
- Produces: shell labels `VIBI // LOCAL` and `SISTEMA EN LÍNEA`.
- Produces: one `VibiFace` on the login screen with `state="idle"` and `perfil="companion"`.

- [ ] Write tests that assert the local brand/status in the shell and the real Vibi face on login.
- [ ] Run the two test files and confirm failures because the semantics are absent.
- [ ] Add the smallest markup/import changes needed to satisfy them.
- [ ] Run the two test files and confirm they pass.

### Task 2: Install and wire the canonical visual layer

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/styles/vibi-ui.css`

**Interfaces:**
- Consumes: all current public class names from pages/components.
- Produces: the final token layer and component styling imported after every historical stylesheet.

- [ ] Add `@fontsource-variable/barlow-condensed` and import it from `main.tsx`.
- [ ] Create the root tokens, global typography, focus, scrollbar, form and button rules.
- [ ] Implement the shell, rail, face chamber, navigation and login composition.
- [ ] Implement shared page headers, cards, lists, tabs, messages, tables, modals and status styles.
- [ ] Add reduced-motion and desktop-width responsive rules.
- [ ] Run TypeScript/build after the new stylesheet is wired.

### Task 3: Verify all live surfaces and correct visual regressions

**Files:**
- Modify: `frontend/src/styles/vibi-ui.css`
- Modify only if semantic gaps are found: affected `frontend/src/pages/*.tsx` or `frontend/src/components/*.tsx`.

**Interfaces:**
- Consumes: the running local API and Vite route tree.
- Produces: a coherent render at 1440×900 for login and all authenticated routes.

- [ ] Start the frontend locally and open it in the browser surface.
- [ ] Capture access and at least one authenticated shell route.
- [ ] Inspect route navigation, clipping, overflow, contrast, focus, empty/loading and modal states available locally.
- [ ] Correct concrete rendering defects and repeat screenshots.

### Task 4: Verify, package and deploy

**Files:**
- Modify only for fixes: paths touched by Tasks 1–3.
- Output: `frontend/src-tauri/target/release/bundle/nsis/Vibi_1.0.0_x64-setup.exe`.

**Interfaces:**
- Produces: passing focused tests, full frontend test evidence, lint, web build, companion build and installed local binary.

- [ ] Run focused shell/login tests.
- [ ] Run the full frontend test suite and record any unrelated pre-existing failures exactly.
- [ ] Run `npm run lint`, `npm run build` and `npm run build:companion`.
- [ ] Run the desktop bundle build.
- [ ] Install the generated package into `%LOCALAPPDATA%\\Vibi`, restart Vibi and verify both the companion and wake processes.
- [ ] Compare the installed executable hash with the packaged payload and inspect startup logs for critical errors.

