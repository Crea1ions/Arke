"""Arke Input Normalizer — robust input sanitization and duplicate prevention."""

from __future__ import annotations

import os


class InputNormalizer:
    """Normalizes and sanitizes user input.
    
    Ensures:
      - `\r` carriage returns removed
      - `\r\n` → `\n` normalization
      - UTF-8 validation
      - Duplicate detection (per-turn)
      - Large paste detection
    """

    def __init__(self):
        """Initialize the normalizer."""
        self._last_input: str = ""
        self._injection_count = 0

    def normalize(self, raw_input: str) -> str:
        """Normalize raw input.
        
        Args:
            raw_input: Raw user input
        
        Returns:
            Normalized input
        
        Raises:
            ValueError: If input is invalid
        """
        if not isinstance(raw_input, str):
            raise ValueError(f"Input must be str, got {type(raw_input)}")
        
        # Strip carriage returns
        normalized = raw_input.replace("\r\n", "\n").replace("\r", "")
        
        # Validate UTF-8
        try:
            normalized.encode("utf-8")
        except UnicodeEncodeError as e:
            raise ValueError(f"Invalid UTF-8 in input: {e}")
        
        # Trim whitespace
        normalized = normalized.strip()
        
        return normalized

    def detect_large_paste(self, text: str) -> bool:
        """Detect if text looks like a large paste.
        
        Args:
            text: The text to check
        
        Returns:
            True if text appears to be a multi-line paste
        """
        # Heuristics for large paste detection
        line_count = text.count("\n")
        char_count = len(text)
        
        # Multi-line paste: >3 lines OR >500 characters
        return line_count > 3 or char_count > 500

    def reset_turn_state(self) -> None:
        """Reset per-turn tracking (call at turn boundary).
        
        Clears injection counter and last input.
        """
        self._injection_count = 0
        self._last_input = ""

    def prevent_double_injection(self, input_text: str) -> None:
        """Check and prevent double-injection of same input.
        
        Args:
            input_text: The input being injected
        
        Raises:
            ValueError: If same input injected twice in same turn
        """
        self._injection_count += 1
        
        if self._injection_count > 1 and input_text == self._last_input:
            raise ValueError("Double injection detected: same input twice in turn")
        
        self._last_input = input_text

    def clean_echo_buffer(self) -> str:
        """Generate cleanup sequence for echo buffer.
        
        Returns:
            ANSI escape sequence to clear echo buffer
        """
        # ANSI sequence to clear line and return to start
        return "\r" + " " * 80 + "\r"


def normalize_input(raw_input: str) -> str:
    """Normalize input (convenience function).
    
    Args:
        raw_input: Raw user input
    
    Returns:
        Normalized input
    """
    normalizer = InputNormalizer()
    return normalizer.normalize(raw_input)


if __name__ == "__main__":
    # Quick test
    print("Testing InputNormalizer:")
    
    normalizer = InputNormalizer()
    
    # Test 1: CRLF normalization
    raw = "Hello\r\nworld\r\n"
    normalized = normalizer.normalize(raw)
    print(f"  CRLF test: {repr(normalized)}")
    
    # Test 2: CR stripping
    raw = "Hello\rWorld"
    normalized = normalizer.normalize(raw)
    print(f"  CR test: {repr(normalized)}")
    
    # Test 3: Large paste detection
    large_text = "\n".join(["line"] * 10)
    is_large = normalizer.detect_large_paste(large_text)
    print(f"  Large paste: {is_large}")
    
    # Test 4: Reset state
    normalizer.reset_turn_state()
    print(f"  State reset OK")
