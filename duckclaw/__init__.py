"""DuckClaw Python package facade over the native C++ extension."""

__all__ = ["DuckClaw"]


def __getattr__(name: str):
    if name == "DuckClaw":
        from ._duckclaw import DuckClaw
        return DuckClaw
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
