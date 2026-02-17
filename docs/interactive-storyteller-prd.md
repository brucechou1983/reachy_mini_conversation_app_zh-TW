# Interactive Storyteller Mode — Product Requirements

## Summary

An AI-powered interactive story book feature for Reachy Mini. The robot creates illustrated story books for children (ages 4-7) using Gemini AI, reads them aloud page by page, and displays them in a fullscreen web reader.

## User Experience

### Target Audience

Children ages 4-7, interacting with a Reachy Mini robot via voice. A caregiver sets up the system and places a tablet or screen nearby to display the story book.

### Interaction Flow

1. **Discovery** — The child talks to the robot. The robot (in storyteller mode) chats warmly and asks what kind of story the child would like.
2. **Creation** — The child picks a theme (e.g., "a brave little rabbit"). The robot confirms and starts generating the story in the background.
3. **Waiting** — While the story generates (1-3 minutes), the robot continues chatting with the child — answering questions, dancing, playing emotions, etc. If asked about the story, it says it's still preparing.
4. **Reading** — When the story is ready, the robot announces it and begins reading page by page. Each page shows a watercolor-style illustration and text on the reader screen.
5. **Interaction** — If the child interrupts with a question mid-story, the robot pauses, answers, then resumes reading.
6. **Ending** — After the last page, the robot closes the reader and asks the child if they enjoyed the story.

```
Child: "我想聽一個關於勇敢小兔子的故事！"

Robot: "好的！我開始幫你創作故事書囉！你可以先跟我聊天。"

  ... (robot chats with the child while story generates) ...

Robot: "故事好了！讓我們一起來聽吧！"

  ... (robot reads each page aloud, reader displays illustrations) ...

Robot: "故事說完啦！你喜歡這個故事嗎？"
```

### Reader Display

A fullscreen web page (`http://localhost:7860/reader`) designed for tablets or secondary screens:

- **Loading screen** — Book icon with animated dots while the story generates, showing the theme title.
- **Reading screen** — Large illustration on top, story text below, page indicator at the bottom. Smooth fade-in animation on each page turn.
- **End screen** — Celebratory icon with "故事結束了！" message.

The reader is purely a display — all interaction happens via the robot's voice.

## Features

### Story Generation

| Attribute | Value |
|-----------|-------|
| Pages | 8 per story |
| Language | Traditional Chinese (Taiwan) |
| Text style | Simple, warm, age-appropriate (2-4 sentences per page) |
| Illustrations | Watercolor-style, soft colors, expressive characters |
| Generation time | ~1-3 minutes (depends on Gemini API latency) |

### Robot Behavior

- Reads each page with warm, vivid expression, using different tones for different characters
- Automatically advances through pages via tool calls
- Pauses when interrupted by the child, answers briefly, then resumes
- Uses the robot's own TTS voice (OpenAI Realtime) for natural speech and interruption support
- Can use other tools (dance, emotions, head movement) naturally during the story session
- Remembers story preferences across sessions via long-term memory tools

### Concurrent Operation

- Story generation runs as a background task — the robot remains fully conversational during generation
- The robot is notified automatically when generation completes (no polling needed)
- Only one story can be generated at a time; if already generating, the tool returns a "please wait" message

## Setup Requirements

### Prerequisites

- Reachy Mini robot with conversation app installed
- Gemini API key (for story generation and image generation)
- OpenAI API key (already required by the conversation app)
- A browser/tablet for the reader display

### Configuration

1. **Gemini API key** — Enter via the settings page (`http://localhost:7860/`) under "Story Book (Gemini)", or add `GEMINI_API_KEY=your_key` to `.env`
2. **Storyteller profile** — Select `storyteller` in the Personality Studio, or set `REACHY_MINI_CUSTOM_PROFILE=storyteller` in `.env`
3. **Reader** — Open `http://localhost:7860/reader` on a display device

### Available Tools in Storyteller Mode

| Tool | Purpose |
|------|---------|
| `story_book_create` | Start generating a new story book (async) |
| `story_book_go_to_page` | Navigate to a page and read it aloud |
| `story_book_close` | Close the reader when finished |
| `dance` / `stop_dance` | Dance animations |
| `play_emotion` / `stop_emotion` | Facial expressions |
| `do_nothing` | Idle behavior |
| `head_tracking` / `move_head` | Head movement |
| `save_memory` / `forget_memory` | Long-term memory |
| `save_profile_memory` / `forget_profile_memory` | Per-profile activity memory |

## Configurable Parameters

| Parameter | Default | Location |
|-----------|---------|----------|
| Gemini text model | `gemini-2.5-flash` | `tools/story_book_create.py` |
| Gemini image model | `gemini-2.5-flash-image` | `tools/story_book_create.py` |
| Number of pages | 8 | `tools/story_book_create.py` |
| Voice | `coral` | `profiles/storyteller/voice.txt` |

## Future Considerations

- **Story bookshelf** — Browse and re-read previously created stories
- **Generation progress** — Show "Page 3/8 generating..." in the reader
- **Story export** — Save stories as PDF or image files
- **Multi-language** — Support English or other languages alongside Traditional Chinese
- **Custom illustration styles** — Let users choose art styles (pixel art, cartoon, realistic)
