"""Curated, high-quality SEL (Social-Emotional Learning) decodable picture books.

The read-along experience is modelled on Ello: the *child* reads aloud and the
robot listens and scaffolds.  To avoid low-quality machine-generated reading
material, the **text** of every book here is hand-authored:

* Early-reader *decodable* English with repetitive sentence frames
  ("I feel ___", "I can ___") that emerging readers can succeed at.
* Each book centres on one **SEL theme** (naming feelings, self-regulation,
  kindness) so reading practice doubles as emotional learning.
* Each page carries a small set of ``tricky`` target words (to pre-teach and to
  highlight on a miss) and an open-ended ``sel_prompt`` for the comprehension /
  feelings conversation after the page is read.

Illustrations are *not* stored here; they are generated on demand by the Gemini
image pipeline and cached on disk (see ``read_along_illustrate``).  Each page
keeps an ``illustration`` prompt describing the scene to draw.
"""

from __future__ import annotations
import re
from typing import List, Optional
from dataclasses import field, dataclass


# Reading modes (Ello book formats).
MODE_DECODABLE = "decodable"        # child reads the page solo
MODE_TURN_TAKING = "turn_taking"    # robot reads a passage, child reads a passage
READING_MODES = (MODE_DECODABLE, MODE_TURN_TAKING)


@dataclass(frozen=True)
class ReadAlongBookPage:
    """A single page of a curated read-along book."""

    text: str
    """The exact English sentence(s) the child reads aloud on this page."""
    tricky: List[str] = field(default_factory=list)
    """Target words to pre-teach and to highlight if the child gets stuck."""
    sel_prompt: str = ""
    """Open-ended feelings / comprehension question asked after reading the page."""
    illustration: str = ""
    """Prompt describing the picture to draw for this page (no text in image)."""


@dataclass(frozen=True)
class ReadAlongBook:
    """A curated SEL decodable picture book."""

    id: str
    title: str
    sel_theme: str
    level: int
    warmup: List[str]
    """Tricky words to warm up on before reading starts (Ello pre-teach)."""
    wrapup: str
    """Warm closing message after the last page (read by the robot)."""
    pages: List[ReadAlongBookPage]

    @property
    def page_count(self) -> int:
        """Return the number of pages in this book."""
        return len(self.pages)


_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def tokenize(text: str) -> List[str]:
    """Split a page's text into display word tokens (punctuation stripped).

    Each token becomes a tappable, individually-animatable word in the reader
    UI, so tokenization is authoritative on the server side (the frontend
    renders exactly this list and refers to words by index).
    """
    return _WORD_RE.findall(text)


def normalize_word(token: str) -> str:
    """Normalize a word for matching (lowercase, strip surrounding punctuation)."""
    m = _WORD_RE.search(token.lower())
    return m.group(0) if m else token.strip().lower()


# --------------------------------------------------------------------------- #
# Curated catalogue
# --------------------------------------------------------------------------- #

_BIG_FEELINGS = ReadAlongBook(
    id="sel-big-feelings",
    title="My Big Feelings",
    sel_theme="naming emotions",
    level=1,
    warmup=["happy", "sad", "mad", "scared"],
    wrapup=(
        "You read about big feelings! Naming how we feel helps us feel better. "
        "I am so proud of you."
    ),
    pages=[
        ReadAlongBookPage(
            text="I have many feelings.",
            tricky=["feelings"],
            sel_prompt="What is one feeling you know?",
            illustration=(
                "A cheerful young child standing with arms open, surrounded by "
                "soft floating heart and star shapes, warm watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I feel happy.",
            tricky=["happy"],
            sel_prompt="Can you show me a happy face? When do you feel happy?",
            illustration=(
                "A smiling child jumping with joy in a sunny park, soft "
                "watercolor, warm colors, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I feel sad.",
            tricky=["sad"],
            sel_prompt="What makes you feel sad sometimes?",
            illustration=(
                "A child with a gentle sad face holding a teddy bear by a "
                "rainy window, soft watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I feel mad.",
            tricky=["mad"],
            sel_prompt="What can you do when you feel mad?",
            illustration=(
                "A small child with crossed arms and a frowning face, puffs of "
                "cartoon steam, gentle watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I feel scared.",
            tricky=["scared"],
            sel_prompt="Is it okay to feel scared? Yes, it is!",
            illustration=(
                "A child peeking out from under a cozy blanket with wide eyes, "
                "soft nightlight glow, gentle watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="All my feelings are okay.",
            tricky=["okay"],
            sel_prompt="All feelings are okay, even the big ones.",
            illustration=(
                "A calm child hugging themselves with a soft smile under a "
                "rainbow, warm watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can name my feelings.",
            tricky=["name"],
            sel_prompt="You did it! Can you name how you feel right now?",
            illustration=(
                "A proud child pointing to a row of friendly emotion faces, "
                "bright cheerful watercolor, no text"
            ),
        ),
    ],
)

_CALM_DOWN = ReadAlongBook(
    id="sel-calm-down",
    title="I Can Calm Down",
    sel_theme="self-regulation",
    level=1,
    warmup=["mad", "stop", "breath", "calm"],
    wrapup=(
        "You learned to calm down with big deep breaths! That is a super power. "
        "Great job, my friend."
    ),
    pages=[
        ReadAlongBookPage(
            text="Sometimes I feel mad.",
            tricky=["mad"],
            sel_prompt="It is okay to feel mad. What makes you feel mad?",
            illustration=(
                "A young child with a frustrated face and clenched hands, soft "
                "warm watercolor, gentle and kind, no text"
            ),
        ),
        ReadAlongBookPage(
            text="My body feels hot.",
            tricky=["body", "hot"],
            sel_prompt="Where do you feel it in your body?",
            illustration=(
                "A child with rosy warm cheeks pointing to their tummy, soft "
                "watercolor with warm glow, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can stop.",
            tricky=["stop"],
            sel_prompt="We can stop and think. Let's try it.",
            illustration=(
                "A calm child holding up one hand in a gentle stop gesture, "
                "soft watercolor, peaceful, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I take a deep breath.",
            tricky=["deep", "breath"],
            sel_prompt="Let's take a deep breath together. Breathe in slowly...",
            illustration=(
                "A child breathing in with a flower near their nose, swirls of "
                "soft air, calming watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="In and out.",
            tricky=["out"],
            sel_prompt="Breathe in... and out. One more time with me!",
            illustration=(
                "A serene child blowing out gently, soft ripples of air, calm "
                "blue and green watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I feel calm now.",
            tricky=["calm"],
            sel_prompt="Do you feel calmer now?",
            illustration=(
                "A relaxed smiling child sitting peacefully cross-legged, soft "
                "warm watercolor, gentle light, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can calm down.",
            tricky=["down"],
            sel_prompt="You can calm down too. I am proud of you!",
            illustration=(
                "A confident happy child giving a thumbs up under a calm sky, "
                "bright gentle watercolor, no text"
            ),
        ),
    ],
)

_WE_ARE_KIND = ReadAlongBook(
    id="sel-we-are-kind",
    title="We Are Kind",
    sel_theme="kindness and empathy",
    level=1,
    warmup=["kind", "share", "help", "hug"],
    wrapup=(
        "You read about being kind! Kindness makes the whole world happy. "
        "You are so kind, my friend."
    ),
    pages=[
        ReadAlongBookPage(
            text="I can be kind.",
            tricky=["kind"],
            sel_prompt="What is one kind thing you can do?",
            illustration=(
                "Two children smiling warmly at each other, soft hearts "
                "floating, warm watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can share my toys.",
            tricky=["share", "toys"],
            sel_prompt="What can you share with a friend?",
            illustration=(
                "A child happily handing a toy block to a friend, bright "
                "cheerful watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can help my friend.",
            tricky=["help", "friend"],
            sel_prompt="Who do you help at home?",
            illustration=(
                "A child helping a friend who fell, reaching out a hand, gentle "
                "warm watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can say sorry.",
            tricky=["sorry"],
            sel_prompt="Saying sorry is brave. It helps friends feel better.",
            illustration=(
                "Two children making up, one with a gentle apologetic smile, "
                "soft watercolor, kind mood, no text"
            ),
        ),
        ReadAlongBookPage(
            text="I can give a hug.",
            tricky=["hug"],
            sel_prompt="Who do you like to hug?",
            illustration=(
                "Two children sharing a warm, gentle hug, soft glowing "
                "watercolor, cozy, no text"
            ),
        ),
        ReadAlongBookPage(
            text="Being kind feels good.",
            tricky=["good"],
            sel_prompt="How do you feel when you are kind?",
            illustration=(
                "A group of happy children playing together kindly, sunny "
                "cheerful watercolor, no text"
            ),
        ),
        ReadAlongBookPage(
            text="We are kind friends.",
            tricky=["friends"],
            sel_prompt="You are a kind friend! Let's be kind today.",
            illustration=(
                "A circle of diverse smiling children holding hands, warm "
                "rainbow watercolor, joyful, no text"
            ),
        ),
    ],
)


_BOOKS: dict[str, ReadAlongBook] = {
    book.id: book for book in (_BIG_FEELINGS, _CALM_DOWN, _WE_ARE_KIND)
}


def all_books() -> List[ReadAlongBook]:
    """Return all curated books in catalogue order (by level then title)."""
    return sorted(_BOOKS.values(), key=lambda b: (b.level, b.title))


def get_book(book_id: str) -> Optional[ReadAlongBook]:
    """Return the curated book with the given id, or None if unknown."""
    return _BOOKS.get(book_id)


def catalog() -> List[dict[str, object]]:
    """Return a compact listing of the curated books for the LLM to choose from."""
    return [
        {
            "id": b.id,
            "title": b.title,
            "sel_theme": b.sel_theme,
            "level": b.level,
            "page_count": b.page_count,
        }
        for b in all_books()
    ]
