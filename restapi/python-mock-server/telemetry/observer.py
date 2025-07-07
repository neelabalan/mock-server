import abc
import typing

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode


def register_event_handler(event_name: str):
    """Decorator to register an event handler method for a specific event."""

    def decorator(func):
        # Store the event name as an attribute on the function
        func._event_name = event_name
        return func

    return decorator


class Observer(abc.ABC):
    @abc.abstractmethod
    def observe(self, event):
        """Receive and process telemetry data or events (e.g., spans, metrics, logs)."""
        pass

    @abc.abstractmethod
    def on_observation(self, event):
        """Handle specific telemetry events (e.g., a log record or span event)."""
        pass

    @abc.abstractmethod
    def initialize(self, config=None):
        """Initialize the observer with optional configuration (e.g., for OpenTelemetry setup)."""
        pass

    @abc.abstractmethod
    def stop(self):
        """Gracefully terminate the observer, releasing resources."""
        pass

    @abc.abstractmethod
    def start(self):
        """Start the observer."""
        pass


class TelemetryObserver(Observer):
    def __init__(self, service_name: str = 'mock-server', otlp_endpoint: str = None):
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint
        self._active_spans: dict[str, trace.Span] = {}
        self._initialized = False

        # Automatically build event handlers from decorated methods
        self.event_handlers: dict[str, typing.Callable[[dict], None]] = {}
        self._register_event_handlers()

    def _register_event_handlers(self):
        for method_name in dir(self):
            method = getattr(self, method_name)
            if callable(method) and hasattr(method, '_event_name'):
                self.event_handlers[method._event_name] = method

    def on_observation(self, event):
        pass

    def initialize(self) -> None:
        if self._initialized:
            return

        resource = Resource.create(
            {
                'service.name': self.service_name,
                'service.version': '1.0.0',
            }
        )

        self.tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(self.tracer_provider)

        if self.otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(endpoint=self.otlp_endpoint)
            self.tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        else:
            console_exporter = ConsoleSpanExporter()
            self.tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))

        self.tracer = trace.get_tracer(__name__)
        self._initialized = True

    def start(self) -> None:
        if not self._initialized:
            self.initialize()

    def observe(self, event_name: str, data: dict[str, typing.Any]) -> None:
        self.on_event(event_name, data)

    def on_event(self, event_name: str, data: dict[str, typing.Any]) -> None:
        if not self._initialized:
            return
        handler = self.event_handlers.get(event_name)
        if handler:
            handler(data)

    @register_event_handler('server.starting')
    def _on_server_starting(self, data: dict[str, typing.Any]):
        span = self.tracer.start_span(
            'server.lifecycle',
            attributes={
                'server.operation': 'startup',
                'server.port': data.get('port'),
            },
        )
        self._active_spans['server.lifecycle'] = span

    @register_event_handler('server.started')
    def _on_server_started(self, data: dict[str, typing.Any]):
        span = self._active_spans.get('server.lifecycle')
        if span:
            span.add_event(
                'server.listening',
                {
                    'server.port': data.get('port'),
                },
            )

    @register_event_handler('server.shutting_down')
    def _on_server_shutting_down(self, data: dict[str, typing.Any]):
        span = self._active_spans.get('server.lifecycle')
        if span:
            span.add_event('server.shutdown_initiated')

    @register_event_handler('server.stopped')
    def _on_server_stopped(self, data: dict[str, typing.Any]):
        span = self._active_spans.get('server.lifecycle')
        if span:
            span.add_event('server.shutdown_completed')
            span.set_status(Status(StatusCode.OK))
            span.end()
            del self._active_spans['server.lifecycle']

    @register_event_handler('route.registered')
    def _on_route_registered(self, data: dict[str, typing.Any]):
        with self.tracer.start_as_current_span('route.registration') as span:
            span.set_attributes(
                {
                    'route.method': data.get('method'),
                    'route.url': data.get('url'),
                    'route.delay_ms': data.get('delay_ms', 0),
                }
            )

    @register_event_handler('request.started')
    def _on_request_started(self, data: dict[str, typing.Any]):
        import time

        request_key = f'{data.get("method")}:{data.get("url")}:{time.time()}'

        span = self.tracer.start_span(
            'http.request',
            attributes={
                'http.method': data.get('method'),
                'http.url': data.get('url'),
                'http.scheme': 'http',
                'http.target': data.get('url'),
            },
        )

        headers = data.get('headers', {})
        for header_name, header_value in headers.items():
            span.set_attribute(f'http.request.header.{header_name.lower()}', str(header_value))

        self._active_spans[request_key] = span

    @register_event_handler('request.handled')
    def _on_request_handled(self, data: dict[str, typing.Any]):
        request_key = self._find_request_span_key(data.get('method'), data.get('url'))
        span = self._active_spans.get(request_key)

        if span:
            span.set_attributes(
                {
                    'http.status_code': data.get('status'),
                    'http.response.delay_ms': data.get('delay_ms', 0),
                }
            )

            status_code = data.get('status', 200)
            if 200 <= status_code < 400:
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(Status(StatusCode.ERROR))

            span.end()
            del self._active_spans[request_key]

    @register_event_handler('request.not_found')
    def _on_request_not_found(self, data: dict[str, typing.Any]):
        request_key = self._find_request_span_key(data.get('method'), data.get('url'))
        span = self._active_spans.get(request_key)

        if span:
            span.set_attributes(
                {
                    'http.status_code': 404,
                    'error': True,
                }
            )
            span.set_status(Status(StatusCode.ERROR, 'Not Found'))
            span.end()
            del self._active_spans[request_key]

    def _find_request_span_key(self, method: str, url: str) -> str | None:
        prefix = f'{method}:{url}:'
        for key in self._active_spans.keys():
            if key.startswith(prefix):
                return key
        return None

    def stop(self) -> None:
        for span in self._active_spans.values():
            span.set_status(Status(StatusCode.ERROR, 'Server shutdown'))
            span.end()
        self._active_spans.clear()

        if hasattr(self.tracer_provider, 'shutdown'):
            self.tracer_provider.shutdown()

        self._initialized = False
