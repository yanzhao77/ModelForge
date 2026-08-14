from __future__ import annotations

from .errors import RunCancelledError


class CancellationToken:
    """Cooperative cancellation shared across an Agent Run (spec 24 / 59).

    The ExecutionEngine checks it between steps; Tools and ModelProviders
    may check it as well.
    """

    def __init__(self):
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """Raise RunCancelledError if cancellation was requested."""
        if self._cancelled:
            raise RunCancelledError()

    def __repr__(self) -> str:
        return f"<CancellationToken cancelled={self._cancelled}>"