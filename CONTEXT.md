# Context - Squishy McSquishface

A shared language for this project. Terms defined once, used everywhere: in conversation,
in code (names), in the docs.

## Language

**Preset**:
One of the four compression levels (Light, Medium, Heavy, Extreme): a resolution cap, fps
cap and bitrate cap applied to x264 CRF 23. Not the x264 `-preset` (speed setting), which is
always `slow`.
_Avoid_: quality, level, profile

**Ceiling**:
The guaranteed upper bound on a preset's output size, computed before encoding. The real
file lands at or under it. Not a prediction of the actual size.
_Avoid_: estimate (alone), predicted size, target

**Trim**:
Keeping only the part of the source between the in-point and the out-point. Time only.
_Avoid_: crop, cut (as a noun for the result), clip (as a verb)

**Crop**:
Cutting away part of the *picture* (a rectangle). Out of scope. Never means trimming.
_Avoid_: using it for trim

**In-point / Out-point**:
The first and last moments of the trim, in source time. Untouched, they are the start and
end of the source.
_Avoid_: start/end handles, marks

**Original**:
The card that exports the trimmed range without re-encoding (stream copy), in the source's
container. Only exists when trimmed.
_Avoid_: as-is, lossless, passthrough

**Keyframe**:
A frame that decodes on its own (I-frame). Every other frame depends on earlier ones back to
its keyframe.
_Avoid_: I-frame (fine in code comments), anchor

**Snap**:
How far the Original's start moves back from the in-point to reach a keyframe. Zero when
the in-point is on a keyframe. Never moves to a later frame. Only the Original snaps: a
bracket *catches* on the scrubbed spot, and a player *jumps* to a keyframe.
_Avoid_: offset, drift, rounding; "snap" for anything else

**Still**:
One frame saved as a JPEG at full source resolution.
_Avoid_: screenshot, thumbnail, snapshot

**Player**:
The video view with the trim bar. Either the browser playing the file, or the fallback:
silent frames rendered by ffmpeg when the browser can't play it.
_Avoid_: preview (ambiguous with the fallback frames), scrubber (only its slider)

## Relationships

- A **Trim** is one in-point and one out-point, never several segments
- Every **Preset** card and the **Original** card work on the same **Trim**
- A **Preset** has a **Ceiling**; the **Original** has an exact size instead
- The **Original** starts at the in-point minus its **Snap**; presets start exactly at the in-point
- A **Still** comes from the frame the **Player** is showing

## Flagged ambiguities

- "crop the beginning or end" (2026-09-27) meant **Trim**. **Crop** is spatial and out of scope.
- "export as is" became the **Original** card; "as is" means the source's bits, not its
  quality level.
