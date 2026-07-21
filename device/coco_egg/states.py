"""Device state machine (spec §4).

LOCAL is the base state — the device is fully useful with zero connectivity.
SYNC is opportunistic. CLOUD_ENHANCED arrives in Phase 2 (M2) and must always
fall back to LOCAL on any timeout/miss.
"""
from enum import Enum, auto


class EggState(Enum):
    LOCAL = auto()           # default: local ASR -> local LLM -> local TTS
    SYNC = auto()            # link available: flush transcripts, pull content/models
    CLOUD_ENHANCED = auto()  # Phase 2 only


class UiState(Enum):
    """Drives the LED ring."""
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    OFFLINE = auto()   # informational only — the egg still works
    ERROR = auto()
