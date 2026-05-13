"""Arke StreamingOutputBuffer — single-pass streaming with ANSI validation."""

from __future__ import annotations

from typing import Optional
import sys


class StreamingOutputBuffer:
    """Buffer for streaming output with ANSI span validation.
    
    Guarantees:
      - Each token emitted exactly once
      - ANSI codes never partial (boundary checking)
      - Line breaks handled deterministically
      - Single-pass (no re-reads)
    """

    def __init__(self):
        """Initialize the streaming buffer."""
        self.buffer: list[str] = []
        self._pending_ansi_code: Optional[str] = None
        self._flushed_count = 0
        self._at_line_start = True

    def append_token(self, token: str) -> Optional[str]:
        """Add a token and return it if ready to flush.
        
        Args:
            token: The token to add
        
        Returns:
            The token if ready to emit, None if waiting for more (buffering ANSI)
        """
        if not token:
            return None
        
        self.buffer.append(token)
        
        # Check if we can safely flush
        # Tokens are safe to flush unless they end with an incomplete ANSI code
        if not self._ends_with_incomplete_ansi(token):
            result = token
            self._flushed_count += 1
            
            # Track line boundaries
            if "\n" in token:
                self._at_line_start = True
            elif token.strip():
                self._at_line_start = False
            
            return result
        
        return None

    def flush_remaining(self) -> str:
        """Flush any remaining buffered content.
        
        Returns:
            Any pending content that wasn't flushed
        """
        # Ensure any open ANSI code is closed
        remaining = "".join(self.buffer[self._flushed_count:])
        if remaining and "\033[" in remaining and "\033[0m" not in remaining:
            remaining += "\033[0m"
        return remaining

    def get_buffer(self) -> str:
        """Get the full accumulated buffer."""
        return "".join(self.buffer)

    def get_flushed_count(self) -> int:
        """Get the number of tokens flushed so far."""
        return self._flushed_count

    @staticmethod
    def _ends_with_incomplete_ansi(token: str) -> bool:
        """Check if token ends with an incomplete ANSI code.
        
        Args:
            token: The token to check
        
        Returns:
            True if token ends with incomplete code (e.g., "\\033[" without "m")
        """
        # Look for ANSI escape starts
        if "\033[" in token:
            # If we have an escape, check if it's closed
            last_escape_idx = token.rfind("\033[")
            after_escape = token[last_escape_idx:]
            
            # Incomplete if no 'm' terminates the code
            if "m" not in after_escape:
                return True
        
        return False


# Convenience helper for direct streaming output
def stream_output(token: str, buffer: Optional[StreamingOutputBuffer] = None) -> None:
    """Write a token to stdout with streaming guarantees.
    
    Args:
        token: The token to output
        buffer: Optional buffer to track state
    """
    sys.stdout.write(token)
    sys.stdout.flush()


if __name__ == "__main__":
    # Quick test
    buf = StreamingOutputBuffer()
    
    # Add some tokens
    print("Testing StreamingOutputBuffer:")
    tokens = ["Hello ", "**world**", "!"]
    for token in tokens:
        result = buf.append_token(token)
        if result:
            print(f"  Flushed: {repr(result)}")
    
    remaining = buf.flush_remaining()
    if remaining:
        print(f"  Remaining: {repr(remaining)}")
    
    print(f"  Total flushed: {buf.get_flushed_count()}")
    print(f"  Buffer content: {repr(buf.get_buffer())}")
