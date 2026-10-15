"""Browser control layer: CDP connection, DOM observation, action execution."""

from .browser import Browser, StalePage, browser_operation, fingerprint

__all__ = ["Browser", "StalePage", "browser_operation", "fingerprint"]
