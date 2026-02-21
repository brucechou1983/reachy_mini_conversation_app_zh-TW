# Interactive Storyteller — Implementation Details

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   OpenAI Realtime API                │
│              (voice conversation + tool calls)       │
└──────────┬──────────────────────────────┬────────────┘
           │                              │
     tool dispatch                  conversation
           │                        injection
           ▼                              │
┌─────────────────────┐                   │
│   Story Tools       │                   │
│  ┌───────────────┐  │    ┌──────────────┴──────────┐
│  │ story_book_   │──┼───▶│    _generate_story()    │
│  │ create        │  │    │  (background asyncio    │
│  └───────────────┘  │    │   task via Gemini API)  │
│  ┌───────────────┐  │    └──────────────┬──────────┘
│  │ story_book_   │  │                   │
│  │ go_to_page    │──┼──┐          set_story_ready()
│  └───────────────┘  │  │                │
│  ┌───────────────┐  │  │                ▼
│  │ story_book_   │  │  │    ┌───────────────────┐
│  │ close         │──┼──┼───▶│   StoryStore      │
│  └───────────────┘  │  │    │   (singleton)      │
└─────────────────────┘  │    │                     │
                         │    │  - story state      │
                         │    │  - SSE fan-out      │
                         │    └────────┬────────────┘
                         │             │ broadcast
                         │             ▼
                    ┌────┴─────────────────────────┐
                    │     FastAPI Routes            │
                    │  /reader       → reader.html  │
                    │  /reader/events → SSE stream  │
                    │  /reader/story → REST JSON    │
                    └──────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │     Reader Frontend           │
                    │  (reader.html/js/css)         │
                    │                               │
                    │  - SSE client for live updates│
                    │  - Page illustration + text   │
                    │  - Loading / reading / end    │
                    └──────────────────────────────┘
```

## File Reference

### New Files

| File | Description |
|------|-------------|
| `story_store.py` | Singleton in-process store for story state. Manages story lifecycle (`generating` → `ready` → `reading` → `closed`) and broadcasts events to SSE subscribers via `asyncio.Queue` fan-out. |
| `story_routes.py` | FastAPI route definitions: `GET /reader` serves the reader HTML, `GET /reader/events` provides an SSE stream, `GET /reader/story` returns current story state as JSON. |
| `tools/story_book_create.py` | Tool that accepts a theme, creates a `Story` in the store, and launches a background `asyncio.Task` to generate text (via `gemini-2.5-flash`) and illustrations (via `gemini-2.0-flash-exp`). Injects a system notification into the conversation when generation completes. |
| `tools/story_book_go_to_page.py` | Tool that navigates to a specific page number, updates the store (broadcasting to the reader), and returns page text with reading instructions for the robot. |
| `tools/story_book_close.py` | Tool that closes the story, broadcasts a `story_closed` event to the reader, and clears the store. |
| `profiles/storyteller/instructions.txt` | System prompt defining the storyteller persona, story flow rules, and reading behavior in Traditional Chinese. |
| `profiles/storyteller/tools.txt` | Tool list enabling the 3 story tools plus standard tools (dance, emotions, head control, memory). |
| `profiles/storyteller/voice.txt` | Voice selection (`coral`). |
| `static/reader.html` | Fullscreen reader page with three screens: loading, reading, and end. |
| `static/reader.js` | SSE client that connects to `/reader/events`, handles page changes, and manages screen transitions with animations. |
| `static/reader.css` | Warm children's book aesthetic — dark purple background, golden accents, floating animations, responsive layout. |

### Modified Files

| File | Change |
|------|--------|
| `config.py` | Added `GEMINI_API_KEY` configuration field. |
| `tools/core_tools.py` | Added `realtime_handler: Any \| None` to `ToolDependencies` dataclass, enabling tools to inject messages into the conversation. |
| `main.py` | Sets `deps.realtime_handler = handler` after handler construction. |
| `console.py` | Added `_persist_gemini_key()` method, Gemini status/key API endpoints, story route mounting, and Gemini key loading on startup. |
| `headless_personality_ui.py` | Added `persist_gemini_key` parameter to `mount_personality_routes()` and a `POST /gemini_api_key` endpoint. |
| `.env.example` | Added `GEMINI_API_KEY=` entry. |
| `static/index.html` | Added Gemini API key settings panel between Tavily and Personality panels. |
| `static/main.js` | Added Gemini key status check, save handler, and UI feedback logic. |

## Key Components

### StoryStore (`story_store.py`)

A singleton that holds the current story state and fans out events to SSE subscribers.

**Data model:**

```python
@dataclass
class StoryPage:
    text: str
    image_b64: str = ""
    image_mime: str = "image/png"

@dataclass
class Story:
    id: str
    title: str
    pages: List[StoryPage]
    current_page: int = 0
    status: str = "generating"  # generating | ready | reading | closed
```

**Lifecycle:**

```
create_story()          → status = "generating", broadcasts {event: "generating"}
set_story_ready()       → status = "ready",      broadcasts {event: "story_ready"}
go_to_page(n)           → status = "reading",    broadcasts {event: "page_change", ...}
close_story()           → status = "closed",     broadcasts {event: "story_closed"}
```

**SSE fan-out:** Each subscriber gets an `asyncio.Queue`. `_broadcast()` calls `put_nowait()` on all subscriber queues. Subscribers are added via `subscribe()` and removed via `unsubscribe()`.

**Thread safety:** All access happens within a single asyncio event loop (tools run as coroutines, background task uses `asyncio.create_task`). No locking is needed for current usage.

### Story Generation Pipeline (`tools/story_book_create.py`)

**Text generation** — Single call to Gemini with `responseMimeType: "application/json"`:

```python
url = f"{GEMINI_API_BASE}/{GEMINI_TEXT_MODEL}:generateContent?key={api_key}"
body = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
        "responseMimeType": "application/json",
        "temperature": 0.9,
    },
}
```

Expected response format: `{"pages": ["page 1 text", "page 2 text", ...]}`

**Illustration generation** — One call per page to Gemini with image modality:

```python
url = f"{GEMINI_API_BASE}/{GEMINI_IMAGE_MODEL}:generateContent?key={api_key}"
body = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
        "responseModalities": ["IMAGE", "TEXT"],
    },
}
```

The response contains `inlineData` parts with `data` (base64) and `mimeType` fields.

**Conversation notification** — After all pages are generated, injects a message into the OpenAI Realtime session:

```python
await handler.connection.conversation.item.create(
    item={
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "[系統通知: 故事書已完成...]"}],
    },
)
await handler.connection.response.create()
```

This follows the same pattern as `send_idle_signal()` in `openai_realtime.py`.

### Tool Dispatch Integration

The three story tools follow the standard tool pattern established in `core_tools.py`:

- Subclass `Tool`, define `name`, `description`, `parameters_schema`
- Implement `async def __call__(self, deps: ToolDependencies, **kwargs) -> Dict[str, Any]`
- Override `is_available()` for conditional registration (Gemini key check)

After tool execution, the existing dispatch flow in `openai_realtime.py` (line 483-487) triggers `response.create()` so the robot speaks the tool result. For `story_book_go_to_page`, the tool result includes an `instruction` field telling the robot to read the page text aloud.

### Reader Frontend

**SSE connection** (`reader.js`):

```javascript
evtSource = new EventSource("/reader/events");
evtSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleEvent(data);  // switches on data.event
};
evtSource.onerror = () => {
    evtSource.close();
    setTimeout(connectSSE, 3000);  // auto-reconnect
};
```

**Screen management** — Three screens (`loading-screen`, `reader-screen`, `end-screen`), toggled via CSS class `active`. Only one is visible at a time.

**Image rendering** — Uses dynamic MIME type from the SSE payload:

```javascript
var mime = data.image_mime || "image/png";
pageImage.src = "data:" + mime + ";base64," + data.image_b64;
```

**Initial state recovery** — On page load, `init()` fetches `GET /reader/story` to recover current state (handles page refresh mid-story).

### Settings UI Integration

The Gemini API key panel in `index.html`/`main.js` follows the exact same pattern as the Tavily panel:

1. `GET /gemini_status` — Check if key is configured
2. `POST /gemini_api_key` — Save key (persisted to `.env` via `_persist_gemini_key()`)
3. UI updates chip status and shows feedback messages

Route registration happens in `console.py:_init_settings_ui_if_needed()`. The `_persist_gemini_key()` method follows the same pattern as `_persist_tavily_key()`: set in-memory config, set env var, update `.env` file.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Robot's own voice for reading** | Uses OpenAI Realtime TTS — natural interruption support, no extra TTS dependency. Page text is returned in the tool result and the robot speaks it naturally. |
| **SSE for reader updates** | One-directional (server → client), no new dependencies. Simpler than WebSocket for this read-only use case. Auto-reconnects on disconnect. |
| **`httpx` for Gemini API** | Already a transitive dependency. Avoids adding the `google-genai` SDK. |
| **StoryStore singleton** | In-process shared state between tools and SSE endpoints. All access is within a single asyncio event loop, so no locking needed. |
| **Background `asyncio.create_task`** | Story generation takes minutes (8 pages x API calls). Fire-and-forget lets the robot continue chatting. Task reference is kept with a done callback to surface exceptions. |
| **Conversation injection for notifications** | Follows the existing `send_idle_signal()` pattern — inject a user message + trigger `response.create()` to wake the LLM. No polling or callback infrastructure needed. |
| **Dynamic MIME types** | Gemini may return JPEG or PNG. The MIME type from the API response is captured in `StoryPage.image_mime` and forwarded through SSE to the reader. |
| **Story ID guards on failure paths** | Background tasks check `store.story.id == story_id` before calling `close_story()`, preventing stale tasks from killing a newer story. |
| **Clamped page values** | `go_to_page` clamps the page number and returns the actual clamped value, not the original request, preventing the LLM from getting confused. |

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Gemini API key missing | `story_book_create` tool is not registered (hidden from LLM) |
| Gemini text generation fails | Background task logs error, closes the current story (with ID guard), SSE broadcasts `story_closed` |
| Gemini image generation fails for a page | Empty `image_b64` for that page, reader hides the image area, story continues |
| Story already generating | `story_book_create` returns `"already_generating"` message |
| No story exists when navigating | `story_book_go_to_page` returns `{"error": "目前沒有故事書可以閱讀"}` |
| SSE connection drops | Reader auto-reconnects after 3 seconds, recovers state from `/reader/story` |
| Background task throws unhandled exception | Done callback surfaces the exception; story stays in `"generating"` state |
| Handler connection not available | Notification injection is guarded with `if handler and getattr(handler, "connection", None)` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/reader` | Serves the reader HTML page |
| `GET` | `/reader/events` | SSE stream of story events (heartbeat every 30s) |
| `GET` | `/reader/story` | Current story state as JSON |
| `GET` | `/gemini_status` | Whether Gemini API key is configured |
| `POST` | `/gemini_api_key` | Set/persist Gemini API key |

## SSE Event Types

| Event | Payload | Trigger |
|-------|---------|---------|
| `generating` | `{title}` | `story_book_create` called |
| `story_ready` | `{story_id, title, page_count}` | Background generation completes |
| `page_change` | `{page, total, text, image_b64, image_mime}` | `story_book_go_to_page` called |
| `story_closed` | `{}` | `story_book_close` called |
| `heartbeat` | `{}` | Every 30s to keep SSE alive |
