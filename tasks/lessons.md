# Lessons

Patterns captured after user corrections, so the same mistake isn't repeated.

## Audio / realtime backends

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
