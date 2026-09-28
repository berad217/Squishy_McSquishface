# Handover: Squishy McSquishface

## 1. Orientation

New AI: oriented via `onboarding.md`, glossary in `CONTEXT.md`. v0.3.0 (trim, Original,
Save frame, visible keyframes) is built, pushed and desktop-checked by the user; the
GitHub release waits on their go. v0.4 (batch) is planned and grilled: spec.md Sprint 5,
decisions and the picker spike in the DEVLOG's top entry. No v0.4 code yet.

## 2. The Delta

- **Release needs the user's explicit go** (tag v0.3.0 at `9b85601`, "Source code (zip)",
  notes from RELEASE_NOTES.md), like v0.2.x.
- The user runs Squishy on two desktops: this one and ROG (3800X, RTX 3090, cloned from
  GitHub). Encode times differ between them; don't compare across machines.
- Picker spike script lived in the session scratchpad and is gone; method and results are
  in the DEVLOG.

## 3. Next Steps

1. Release v0.3.0 once the user says go.
2. Build v0.4 against Sprint 5, test-first where pure (file listing, totals, naming,
   skip rules, the batch state machine).
