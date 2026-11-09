"""API key rotation utility — tries each key in sequence on failure.

Usage:
    rotator = KeyRotator(keys=["key1", "key2"])
    result = rotator.try_keys(lambda key: call_api(key))
"""
from __future__ import annotations

import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class KeyRotator:
    """Rotates through a list of API keys, trying the next on failure.

    On success, moves the successful key to the front (hot cache).
    On failure, logs the error and tries the next key.
    Raises the last exception if all keys fail.
    """

    def __init__(self, keys: list[str], name: str = "api") -> None:
        if not keys:
            raise ValueError(f"No API keys provided for {name}")
        self._keys = list(keys)
        self._name = name
        self._active_index = 0

    @property
    def current_key(self) -> str:
        return self._keys[self._active_index]

    def try_keys(self, fn: Callable[[str], T]) -> T:
        """Try `fn(key)` with each key until one succeeds.

        Args:
            fn: Function that takes an API key and returns a result.
                Should raise an exception on failure (HTTP 4xx/5xx, etc).

        Returns:
            The result from the first successful call.

        Raises:
            The last exception if all keys fail.
        """
        last_exc: Exception | None = None
        n = len(self._keys)

        for i in range(n):
            idx = (self._active_index + i) % n
            key = self._keys[idx]
            try:
                result = fn(key)
                # Success — promote this key to front
                if idx != self._active_index:
                    logger.info(
                        "%s key rotation: promoted key index %d to active",
                        self._name, idx,
                    )
                    self._active_index = idx
                return result
            except Exception as e:
                last_exc = e
                logger.warning(
                    "%s key index %d failed: %s — trying next key",
                    self._name, idx, str(e)[:200],
                )

        raise last_exc  # type: ignore[misc]
