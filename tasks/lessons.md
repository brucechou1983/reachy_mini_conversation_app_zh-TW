# Lessons

Patterns captured after user corrections, so the same mistake isn't repeated.

## Multi-backend parity

- **A feature wired to one backend's connection object silently dies on the
  other.** Story auto-reading (announce book ready → narrate page → time the
  audio → turn the page → close) was built entirely in the OpenAI handler and the
  ready-notification was gated on ``getattr(handler, "connection", None)`` — an
  OpenAI-only attribute. The Gemini handler uses ``.session``, so it generated the
  book then never read it, and never auto-advanced. The user guessed "Gemini tool
  calling doesn't auto-continue"; the real cause was that the whole subsystem was
  OpenAI-only. Fix: extract a backend-agnostic ``StoryReaderMixin`` (state machine
  + timing) with one per-backend primitive (``_story_request_narration``) and the
  shared ``inject_user_text``; drive page-turning client-side (the app fetches each
  page and asks the model to read it) rather than hoping the model calls the tool.
  Rule: when two backends implement the same interface, never gate shared features
  on a backend-specific attribute (``connection`` vs ``session``) — put the logic
  in the shared base and depend only on the common interface; grep both handlers
  for any feature touching ``.connection``/``.session`` directly.

## Audio / realtime backends

- **To time "the speaker finished," measure the actual push stream, don't guess a
  duration.** Story page-turns fired too early. A duration *estimate* (samples/rate
  + buffer, even ×SPEECH_SLOWDOWN) is fragile: realtime backends deliver audio at
  different rates, the player time-stretches it, and push_audio_sample() is
  non-blocking (feeds the speaker faster than realtime), so when generation ends
  there's still buffered audio. The robust method (which we'd built before and a
  refactor regressed): a **sentinel** enqueued behind the page's audio chunks;
  ``play_loop`` tallies the *actual pushed* audio duration (post time-stretch, so
  slowdown is automatically included) and the real first-push timestamp, and when
  it dequeues the sentinel computes ``remaining = pushed_duration − elapsed`` — the
  exact buffer still draining — then waits that + a small buffer. Rule: when you
  need "playback finished," instrument the component that actually feeds the
  speaker; a time estimate computed upstream (at generation end) can't see the
  downstream buffer or the stretch. Keep the estimate only as a fallback for
  transports without that instrumentation.



- **Don't tear down long-running client state on a barge-in that fires on echo.**
  The Gemini story auto-read stalled after page 1: a spurious server ``interrupted``
  (the robot's own narration echoing into the always-on mic during the multi-second
  wait between pages) reached ``_barge_in()``, which unconditionally called
  ``cancel_story_advance()`` and cancelled the pending next-page task — the
  ``CancelledError`` was swallowed, so there was no ``go_to_page`` log and no error
  (the model then improvised ``do_nothing``). The OpenAI handler never had this: it
  cancels story-advance only on ``input_audio_buffer.speech_started`` (a genuine
  user-speech event), never on its own audio. Fix: ``_barge_in(suppress, cancel_story)``
  — always flush playback, but only ``cancel_story=True`` from real-user paths
  (heard-child transcript / local mic energy), and on a bare server ``interrupted``
  only when ``input_transcription_buffer`` is non-empty (a real child spoke). Rule:
  "stop the current audio" and "abandon the multi-step task" are different actions;
  gate the destructive one on a *confirmed* user signal, since on a robot without
  AEC the interrupt signal alone is not proof a human spoke.



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

- **Don't compensate for your own misconfiguration with more code — check the
  working sibling.** After the flush fix, the robot started interrupting *itself*
  ("no response", storyteller stalls mid-page). My first instinct was to bolt on
  defenses (an interrupt grace + a mic-energy "echo gate"). The user asked the
  right question: *gpt-realtime never self-interrupted — are we deviating from the
  official method?* It was: the OpenAI handler uses **default** `server_vad`
  (moderate threshold), while our Gemini config forced
  `START_SENSITIVITY_HIGH` — which I'd added earlier to "help" barge-in fire, back
  when barge-in was actually broken by the no-op flush. With the flush fixed, the
  aggressive sensitivity was pure liability: it tripped on the robot's own echo.
  The fix was to **delete** the override (use Gemini's default sensitivity, like
  OpenAI) and drop the grace + echo-gate entirely. Rule: when one backend
  misbehaves and a sibling backend doesn't, diff their config against the vendor
  default *before* adding compensating machinery — a knob you set is the first
  suspect, and matching the reference beats inventing a workaround. Keep only the
  minimal, legitimate tuning (an explicit `silence_duration_ms`); don't ship
  defenses for a problem you created.

- **End-of-turn VAD must be patient for kids — but tune timing, not sensitivity.**
  Gemini Live's default end-of-turn timing cut a child's turn on the pause inside
  "等⋯一下", answering "等" then asking what "一下" meant. Fix with an explicit
  `silence_duration_ms` (~900ms) + `prefix_padding_ms` from
  `AutomaticActivityDetection`; leave start/end sensitivity at the vendor default
  (forcing it is what caused the self-interrupt above).

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

## Generative content quality (images + copy)

- **For multi-page character consistency, lock the cast with ONE reference image,
  then condition every page on it.** The first storybook pipeline generated each
  page's illustration independently from the page text, so the same character looked
  different on every page. The user's direction was the right pattern: generate a
  single front-view *character reference sheet* first, then feed that image back as
  an input to each page's generation (gemini-2.5-flash-image / "Nano Banana" is
  built for this) with a prompt that restates the cast and demands "exactly
  consistent with the reference image." Also **separate the narration text from the
  image brief**: the page `text` (what the child hears, Traditional Chinese) is a
  poor image prompt — have the writer also emit an English `scene` per page, and use
  that for the illustrator. Rule: consistency across many generations comes from a
  shared *anchor artifact* fed into each call, not from hoping independent calls
  converge; and never reuse human-facing prose as an image prompt.

- **Describe an art style by its visual traits, not only by the artist's name.**
  Naming a living artist (工藤紀子) can be ignored or filtered by the image model. Bake
  a rich description of the look (line weight, flat gouache fills, rounded chunky
  characters, palette, composition) into a reusable `_STYLE` constant applied to
  both the reference sheet and every page, with the name as a soft hint. A generic
  "soft watercolor" prompt yields characterless output.

- **Put picture-book craft in the writing prompt explicitly.** "簡短、溫暖、有趣" gives
  bland copy. Inject concrete techniques the model can act on: a clear story arc
  (want → obstacle → turn → warm resolution), a recurring refrain the child can
  predict and say along, onomatopoeia, show-don't-tell sensory detail, read-aloud
  rhythm, and page-turn hooks. Generate the cast + all pages in one structured-JSON
  call so text and characters stay coherent.

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
