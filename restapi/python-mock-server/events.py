# not used
import dataclasses
import typing


@dataclasses.dataclass(frozen=True)
class Event:
    name: str
    data: dict[str, typing.Any]
    timestamp: float


class EventEmitter:

    def __init__(self):
        self._listeners: dict[str, list[typing.Callable[[Event], None]]] = {}

    def emit(self, event_name: str, data: dict[str, typing.Any] = None) -> None:
        if event_name not in self._listeners:
            return

        import time
        event = Event(name=event_name, data=data or {}, timestamp=time.time())

        for listener in self._listeners[event_name]:
            try:
                listener(event)
            except Exception:
                pass

    def on(self, event_name: str, listener: typing.Callable[[Event], None]) -> None:
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(listener)

    def off(self, event_name: str, listener: typing.Callable[[Event], None] | None = None) -> None:
        if event_name not in self._listeners:
            return

        if listener is None:
            self._listeners[event_name] = []
        else:
            if listener in self._listeners[event_name]:
                self._listeners[event_name].remove(listener)
