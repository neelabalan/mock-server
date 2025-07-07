import argparse
import dataclasses
import http.server
import json
import logging
import time
import typing

from telemetry.observer import Observer


@dataclasses.dataclass(frozen=True)
class ResponseFormat:
    status: int
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    body: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class ApiFormat:
    url: str
    method: str
    response: ResponseFormat
    delay: int = 0


class MockHandler(http.server.BaseHTTPRequestHandler):
    routes: list[ApiFormat] = []
    observers = []

    def notify_observers(self, event_name: str, data: dict[str, typing.Any] = None):
        for observer in self.observers:
            try:
                observer.observe(event_name, data or {})
            except Exception:
                # Don't let observer errors crash the main application
                pass

    def do_request(self) -> None:
        self.notify_observers(
            'request.started', {'method': self.command, 'url': self.path, 'headers': dict(self.headers)}
        )

        found = False
        for route in self.routes:
            if self.path == route.url and self.command == route.method:
                found = True
                delay = route.delay / 1000.0
                time.sleep(delay)
                expected_response = route.response
                self.send_response(expected_response.status)
                for header, value in expected_response.headers.items():
                    self.send_header(header, value)
                self.end_headers()
                logging.debug(
                    f'API request handled: method={route.method}, url={route.url}, status={expected_response.status}'
                )

                self.notify_observers(
                    'request.handled',
                    {
                        'method': route.method,
                        'url': route.url,
                        'status': expected_response.status,
                        'delay_ms': route.delay,
                    },
                )

                if expected_response.body:
                    self.wfile.write(json.dumps(expected_response.body).encode())
                    return

        if not found:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not found"}')
            self.notify_observers('request.not_found', {'method': self.command, 'url': self.path})

    def do_GET(self) -> None:
        self.do_request()

    def do_POST(self) -> None:
        self.do_request()

    def do_PUT(self) -> None:
        self.do_request()

    def do_DELETE(self) -> None:
        self.do_request()


class MockServer:
    def __init__(self, routes: list[ApiFormat], handler: typing.Type[http.server.BaseHTTPRequestHandler], port: int = 8080):
        super().__init__()
        self.port = port
        self.observers = []
        self.handler = handler
        self.routes = routes

        self.handler.routes = routes

    def register_observer(self, observer: Observer):
        self.observers.append(observer)

        # just do the registering part alone here
        if hasattr(self.handler, "observers"):
            self.handler.observers.append(observer)

    def notify_observers(self, event_name: str, data: dict[str, typing.Any] = None):
        for observer in self.observers:
            try:
                observer.observe(event_name, data or {})
            except Exception:
                # Don't let observer errors crash the main application
                pass

    def start(self) -> None:
        self.notify_observers('server.starting', {'port': self.port})

        self.server = http.server.HTTPServer(('', self.port), self.handler)

        for route in self.routes:
            logging.info(f'Registered endpoint: method={route.method}, url={route.url}')
            self.notify_observers(
                'route.registered', {'method': route.method, 'url': route.url, 'delay_ms': route.delay}
            )

        logging.info(f'Starting server on port {self.port}')
        self.notify_observers('server.started', {'port': self.port})

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        if self.server:
            logging.info('Shutting down server...')
            self.notify_observers('server.shutting_down', {})
            self.server.shutdown()
            self.server.server_close()
            self.notify_observers('server.stopped', {})

        # Shutdown observers
        for observer in self.observers:
            observer.stop()


def load_config(config_path: str) -> list[ApiFormat]:
    config_data = None
    with open(config_path, 'r') as f:
        config_data = json.load(f)
    routes = [
        ApiFormat(
            url=route_data['url'],
            method=route_data['method'],
            response=ResponseFormat(**route_data['response']),
            delay=route_data.get('delay', 0),
        )
        for route_data in config_data
    ]
    return routes


def main() -> None:
    parser = argparse.ArgumentParser(description='Run a mock API server with optional telemetry.')
    parser.add_argument('--mock-data', type=str, required=True, help='Path to the JSON config file.')
    parser.add_argument('--port', type=int, default=8080, help='Port number to run the server on.')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging.')
    parser.add_argument('--enable-telemetry', action='store_true', help='Enable OpenTelemetry instrumentation.')
    parser.add_argument(
        '--otlp-endpoint', type=str, help='OTLP endpoint for exporting traces (e.g., http://localhost:4317)'
    )
    parser.add_argument('--service-name', type=str, default='mock-server', help='Service name for telemetry')
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    routes = load_config(args.mock_data)
    server = MockServer(routes=routes, handler=MockHandler, port=args.port)

    # Register telemetry observer if requested
    if args.enable_telemetry:
        try:
            from telemetry import TelemetryObserver

            telemetry_observer = TelemetryObserver(service_name=args.service_name, otlp_endpoint=args.otlp_endpoint)
            telemetry_observer.start()  # Initialize the observer
            server.register_observer(telemetry_observer)

            logging.info(f'OpenTelemetry instrumentation enabled (service: {args.service_name})')
            if args.otlp_endpoint:
                logging.info(f'OTLP endpoint: {args.otlp_endpoint}')
            else:
                logging.info('Exporting to console')
        except ImportError:
            logging.error('OpenTelemetry dependencies not available')
            return
        except Exception as e:
            logging.error(f'Failed to setup telemetry: {e}')
            return
    else:
        logging.info('Running without telemetry instrumentation')

    server.start()


if __name__ == '__main__':
    main()
