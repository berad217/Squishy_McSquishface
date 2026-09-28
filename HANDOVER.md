# Handover: Squishy McSquishface

## 1. Orientation

New AI: oriented via `onboarding.md`, glossary in `CONTEXT.md`. v0.3.0 is released.
**v0.4.0 (batch + log file) is built and pushed, not released or tagged.** Plan and
criteria: spec.md Sprint 5. What was checked and what wasn't: the DEVLOG's top entry.

## 2. The Delta

- **Two checks are the user's, on both desktops** (this one and ROG: 3800X, RTX 3090,
  cloned from GitHub; it needs `git pull` and a Squishy restart, since an older copy still
  running makes the new one refuse to start):
  1. Click **Choose folder...** in Chrome: does the picker come up in front of the browser?
  2. Run a real folder of 5+ clips unattended (criterion 9). Afterwards,
     `logs\squishy.log` beside `Squishy.bat` has the record.
- **Release needs the user's explicit go:** tag v0.4.0, publish with the v0.4.0 section of
  RELEASE_NOTES.md as the body, title `v0.4.0 - "Set It and Forget It"`. Same pattern as
  v0.3.0 (annotated tag, `gh release create --verify-tag --notes-file`).
- **Testing pickers without a person:** the session's script (gone with its scratchpad)
  started the pick from the page, then found the dialog by its title ("Squishy: choose..."),
  set the path with `WM_SETTEXT` on its one visible Edit control, and sent `BM_CLICK` to
  "Select Folder" / "&Open". No keystrokes, so nothing can be typed into the wrong window.
  Multiple files go in as `"C:\a.mp4" "C:\b.mp4"`.
- **The user struggles with scope creep and knows it.** This session went v0.3 build, then
  keyframes, then a speed question, then batch, then logging. Each was their call and is
  logged, but propose finishing (checks, release) before new features.
- Parked, not started: the GPU-decode speed spike (spec Parking Lot, under NVENC).

## 3. Next Steps

1. User runs the two checks; fix anything they find (the log helps).
2. On their go: tag and release v0.4.0.
3. Then, if they still want speed: the GPU-decode timing spike from the Parking Lot.
