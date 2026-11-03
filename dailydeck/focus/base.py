from dataclasses import dataclass, field


class FocusUnavailable(Exception):
    """Raised when a focus backend cannot currently answer."""


@dataclass(frozen=True)
class WindowInfo:
    """Platform neutral description of the focused window.

    ``ids`` holds every identifier the backend knows for the application
    (WM class, desktop file id, executable name, bundle id, ...). Profiles
    match against any of them, so one profile can list the ids of all
    platforms.
    """

    ids: tuple[str, ...] = ()
    title: str = ""
    name: str = ""
    pid: int = 0
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def empty(self) -> bool:
        return not self.ids and not self.title

    @property
    def display_name(self) -> str:
        return self.name or (self.ids[0] if self.ids else "")


class FocusProvider:
    name = "base"

    def get(self) -> WindowInfo:
        raise NotImplementedError

    def close(self) -> None:
        pass
