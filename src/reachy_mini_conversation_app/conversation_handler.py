"""Abstract base for conversation backends.

Both the OpenAI Realtime handler and the Gemini Live handler implement this
interface so the transport layers (``LocalStream`` and ``fastrtc.Stream``) and
``main.py`` can treat either backend uniformly.
"""

import asyncio
from abc import abstractmethod
from typing import Tuple, Callable, Optional

import numpy as np
from fastrtc import AdditionalOutputs, AsyncStreamHandler
from numpy.typing import NDArray


class ConversationHandler(AsyncStreamHandler):
    """Common interface for conversation handlers (OpenAI Realtime, Gemini Live)."""

    # Outgoing speaker audio / UI transcript updates. Set by each subclass __init__.
    output_queue: "asyncio.Queue[Tuple[int, NDArray[np.int16]] | AdditionalOutputs]"
    # Optional hook installed by LocalStream to flush queued playback on barge-in.
    _clear_queue: Optional[Callable[[], None]] = None

    @abstractmethod
    async def start_up(self) -> None:
        """Establish the provider connection and run the session loop."""
        raise NotImplementedError

    @abstractmethod
    async def receive(self, frame: Tuple[int, NDArray[np.int16]]) -> None:
        """Forward a microphone frame to the provider."""
        raise NotImplementedError

    @abstractmethod
    async def emit(self) -> Tuple[int, NDArray[np.int16]] | AdditionalOutputs | None:
        """Return the next speaker-audio frame or UI update (or None)."""
        raise NotImplementedError

    @abstractmethod
    async def shutdown(self) -> None:
        """Close the provider connection and release resources."""
        raise NotImplementedError

    @abstractmethod
    def copy(self) -> "ConversationHandler":
        """Return a fresh handler instance for a new session."""
        raise NotImplementedError
