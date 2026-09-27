# Handover: Squishy McSquishface

## 1. Orientation

New AI: oriented via `onboarding.md`, glossary in `CONTEXT.md`. v0.3.0 (trim, Original,
Save frame) is built and committed, **not released**. Plan and criteria: spec.md Sprint 4.
What was checked and what wasn't: the DEVLOG's top entry.

## 2. The Delta

- **Video-mode interaction is unchecked.** Dragging handles, arrow keys and I/O with a
  *playable* file were never run with the browser pane on screen (rVFC needs painting). The
  fallback mode was fully exercised. This is the one gap before release.
- **Release is waiting on the user.** They asked to confirm before publishing a GitHub
  release (like v0.2.x: tag, "Source code (zip)", notes from RELEASE_NOTES.md).
- The reference clip is in `samples/` (gitignored). Spike scripts from this session were in
  a session scratchpad and are gone; the DEVLOG has their method and numbers.

## 3. Next Steps

1. User desktop check of v0.3.0 on the reference clip: drag both handles, I/O, arrows,
   Space; Save frame; a trimmed Medium; an Original. Watch that the time display moves.
2. If it passes: push, tag v0.3.0, publish the release (after the user confirms).
