# Lessons

Patterns captured after user corrections, so the same mistake isn't repeated.

## Audio / realtime backends

- **When a fix has "no audible effect," read the *installed SDK source* — methods
  go silently no-op.** Barge-in "依然沒有停" for many attempts even though detection
  logged correctly. Root cause: `clear_audio_queue` gated on
  `media.backend ∈ {GSTREAMER, GSTREAMER_NO_VIDEO}` to call `clear_player()`, else
  `clear_output_buffer()`. But the SDK's `_resolve_backend` rewrites those legacy
  enums to `LOCAL`, so the check was **always False** → we always called
  `clear_output_buffer()`, which is a **deprecated no-op** on both `GStreamerAudio`
  and `GstWebRTCClient` (only `clear_player()` actually flushes the appsrc; WEBRTC's
  also POSTs the daemon to drop the speaker queue). The detection chain looked fine
  in our code; the bug was one method call into the dependency. Rule: when behavior
  doesn't change, grep the *installed* package (`.venv/.../site-packages`) for the
  exact method you call and confirm it isn't deprecated/no-op/alias-resolved before
  touching your own logic. Don't branch on SDK enums that the SDK may normalize —
  prefer `getattr(obj, "real_method", None)` capability checks.

- **Fixing one thing exposes what it was masking — echo self-interrupt.** Once
  the barge-in flush actually worked (`clear_player`), a new symptom appeared:
  "no response" and the storyteller stopping mid-page. Cause: the robot has no
  echo cancellation, so it hears its *own* voice; Gemini's server VAD fires a
  spurious `interrupted` that — now that the flush is real — kills the robot's own
  reply. Previously the no-op flush hid this. Two defenses, both default-on and
  tunable: (a) an interrupt **grace** (`INTERRUPT_GRACE_MS`) ignoring interrupts
  in the first moments of a reply (covers the tail of the user's own question);
  (b) an **echo gate** — only honor an interrupt if the recent mic peak rose above
  `BARGE_IN_LEVEL` (a real person speaks up; mere echo stays below). Measure the
  robot's echo floor vs. real-speech level from logs (here echo <0.06< speech
  ~0.085) to pick the threshold. Rule: after fixing a masking bug, expect latent
  bugs it hid to surface, and re-test the whole interaction.

- **End-of-turn VAD must be patient for kids.** Gemini Live with
  `END_SENSITIVITY_HIGH` cut a child's turn on the pause inside "等⋯一下",
  answering "等" then asking what "一下" meant. Use `END_SENSITIVITY_LOW` + an
  explicit `silence_duration_ms` (~900ms), keep start sensitivity HIGH so barge-in
  stays instant. The SDK's `AutomaticActivityDetection` exposes
  `silence_duration_ms`/`prefix_padding_ms` — prefer the explicit ms knobs over
  the HIGH/LOW preset.

- **Constrain tool enums in the schema, not just the description.** `play_emotion`
  listed valid names only in the param *description*, so the model emitted
  'shaking1' and the call failed. Add a JSON-schema `enum` of the real names
  (function-calling grammar then forbids invalid values). Degrade to a plain
  string (no empty `enum`, which forbids everything) when the list is unavailable.

- **A client-side barge-in must suppress the rest of the aborted turn, not just
  flush once.** After flushing playback locally (mic energy / heard-child), Gemini
  keeps streaming the *same* interrupted turn until its own server VAD sends
  `interrupted`; those chunks re-enter `output_queue` and resume playback a beat
  later (log: `Mic frames… while robot speaks` reappears right after the flush).
  Fix: a post-barge-in mute window (`_mute_until`) that drops incoming `model_turn`
  audio until the server `interrupted`/`turn_complete` arrives (or the window
  lapses). A server `interrupted` means the turn already stopped → clear the mute
  so the next turn plays. Rule: flushing the buffer is necessary but not
  sufficient when the producer keeps streaming — gate the producer too.

- **A regression test can lock in the bug.** `test_console_barge_in` asserted that
  real backends (LOCAL/WEBRTC) call `clear_output_buffer()` and *not*
  `clear_player()` — i.e. it pinned the no-op as correct, so it stayed green
  through the whole broken period. When a feature "works in tests but not on
  device," re-derive what the test *should* assert from the dependency's real
  behavior, don't trust that green = correct.

- **Mirror the reference handler's full audio I/O conversion, not just the happy path.**
  When adding the Gemini Live backend I forwarded mic frames with a bare
  `array.squeeze().tobytes()`. The robot mic delivers **stereo and/or float at a
  native rate**, so the Live server rejected every spoken frame with
  `1007 invalid audio format: 16khz s16le pcm, mono channel`. The OpenAI handler
  already did mono-downmix → resample → int16; the new backend must do the same.
  Rule: when porting a streaming backend, copy the input/output format conversion
  (channels, sample rate, dtype) verbatim, then unit-test it with stereo/float/
  off-rate input.

## Hardware debugging

- **Don't jump to "permission" / "silent mic" conclusions — verify with a direct
  device test first.** I told the user the macOS mic permission was the problem;
  they correctly pushed back ("權限本來就是開的"). A `sounddevice` capture straight
  from the device (peak=7817) proved the hardware + permission were fine. Always
  isolate hardware vs pipeline with the lowest-level probe before blaming config.

- **The Desktop App runtime ≠ a hand-launched CLI daemon.** My CLI daemon's
  GStreamer audio returned silence; the official Desktop App captured audio fine
  and surfaced the *real* bug (format 1007). Reproduce in the supported runtime
  before concluding "SDK/platform bug".

## CI / tooling

- **A `pyproject.toml` version bump requires regenerating `uv.lock`** (`uv lock`)
  or the `uv-lock-check` job fails. Bump version and lock in the same commit.

## FastAPI / packaging

- **With `from __future__ import annotations`, a FastAPI body model must be a
  module-level class.** A Pydantic model defined *inside* the route-mounting
  function had its annotation stored as a string; `get_type_hints` couldn't
  resolve the local name, so FastAPI silently treated the `payload` param as a
  **query** param and every POST returned `422` (`loc: ["query","payload"]`).
  Rule: declare request/response models at module scope, not inside a closure.

- **Package-data globs must list every shipped extension.** `package-data` only
  had `profiles/**/*.txt`, so `SKILL.md` files (and any new `*.md`) were absent
  from the built wheel / HF Space — skills silently "disappeared" in deployment
  though they worked in dev. Added `profiles/**/*.md`. When adding a new asset
  type under the package, add its glob too.

- **Don't unit-test an endless SSE endpoint through the HTTP layer.** Both
  `TestClient.stream` (blocking portal) and httpx `ASGITransport` hang on an
  infinite `StreamingResponse` generator. Extract the async generator to a
  module-level function and drive it directly with `anext()` + `asyncio.wait_for`.

## LLM-driven interactions

- **Enforce hard rules in code, not in the prompt.** First cut of the read-along
  let the LLM decide when a page was "done" and when to flag a misread; on real
  hardware Gemini Flash advanced after marking only one word green and missed a
  deliberate misread (user: 「一個字綠就給我過了」). Fix: a server-side gate —
  `read_along_next_page` refuses to advance unless every word is `success`, plus a
  batched `read_along_grade(correct, incorrect)` so per-word grading is one
  reliable call instead of N hoped-for `cue` calls. Rule: any invariant the user
  expects ("all words read before advancing") must be enforced deterministically
  in the tool/store; the LLM supplies observations, the code polices the rule.

## Test isolation

- **Don't inject `sys.modules[...] = MagicMock()` for installed deps in a test
  that sorts early.** `test_camera.py` mocked `openai`/`gradio`/`fastrtc`; because
  it collects before `test_gemini_realtime`/`test_openai_realtime`, it replaced
  those real modules and 25 handler tests failed. Those packages are real deps —
  just import normally (like `test_take_photo.py`). Only mock truly-absent
  hardware modules, and prefer not to pollute global `sys.modules` at all.
