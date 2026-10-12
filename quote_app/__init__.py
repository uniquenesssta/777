"""Windows Tk/file adapters. The independent business package is quote_core."""

from .integration import QuoteApplicationMixin
from .background import BackgroundApplicationMixin

__all__ = ["QuoteApplicationMixin", "BackgroundApplicationMixin"]
