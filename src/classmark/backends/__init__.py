from classmark.backends.base import Backend, Response
from classmark.backends.claude import ClaudeBackend
from classmark.backends.jev import JevBackend

BACKENDS = {"jev": JevBackend, "claude": ClaudeBackend}


def get_backend(name: str) -> Backend:
    try:
        return BACKENDS[name]()
    except KeyError:
        raise ValueError(f"unknown backend {name!r}; choose from {', '.join(BACKENDS)}") from None


__all__ = ["Backend", "Response", "BACKENDS", "get_backend"]
