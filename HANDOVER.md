# Handover: Squishy McSquishface

## 1. Orientation

New AI: oriented via `onboarding.md`, glossary in `CONTEXT.md`. v0.3.0 is released.
v0.4.0 (batch: pick a folder or files, one preset, unattended) is built and committed,
**not released**. Plan: spec.md Sprint 5. Results and gaps: the DEVLOG's top entry.

## 2. The Delta

- **Two checks only the user can do:** clicking Choose folder... from Chrome (picker in
  front?) on this PC and on ROG, and an unattended run on a real folder (criterion 9).
- The user runs Squishy on two desktops: this one and ROG (3800X, RTX 3090, cloned from
  GitHub). Encode times differ; don't compare across machines.
- Release needs the user's explicit go (tag, "Source code (zip)", notes from
  RELEASE_NOTES.md).

## 3. Next Steps

1. User: real folder batch on either machine; report anything odd.
2. If it passes: push, tag v0.4.0, publish (after the user confirms).
