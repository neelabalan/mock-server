# uv run --with-requirements requirements.txt websocket_mock_server.py --mock-data="../data/websocket_sample.json"

import argparse
import asyncio
import dataclasses
import json
import logging
import typing

import websockets
from websockets.server import WebSocketServerProtocol


@dataclasses.dataclass
class WebSocketResponse:
    message: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    delay: int = 0


@dataclasses.dataclass
class WebSocketEndpoint:
    path: str
    on_connect: WebSocketResponse | None = None
    on_message: WebSocketResponse | None = None
    on_close: WebSocketResponse | None = None


@dataclasses.dataclass
class WebSocketConfig:
    endpoints: list[WebSocketEndpoint]


class WebSocketMockServer:
    def __init__(self, config: WebSocketConfig, port: int = 8080):
        self.config = config
        self.port = port
        self.connections = set()

    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        self.connections.add(websocket)
        logging.info(f'Client connected to {path}')

        # Find endpoint for this path
        endpoint = self._find_endpoint(path)
        if not endpoint:
            logging.warning(f'No endpoint configured for path: {path}')
            await websocket.close(code=1003, reason='No endpoint configured')
            return

        # Handle connection event
        if endpoint.on_connect:
            await self._send_response(websocket, endpoint.on_connect, 'CONNECT', path)

        try:
            async for message in websocket:
                logging.debug(f'Received message on {path}: {message}')

                # Handle message event
                if endpoint.on_message:
                    await self._send_response(websocket, endpoint.on_message, 'MESSAGE', path)

        except websockets.exceptions.ConnectionClosed:
            logging.info(f'Client disconnected from {path}')
        except Exception as e:
            logging.error(f'Error handling client: {e}')
        finally:
            self.connections.discard(websocket)
            # Handle close event
            if endpoint.on_close:
                await self._send_response(websocket, endpoint.on_close, 'CLOSE', path)

    def _find_endpoint(self, path: str) -> WebSocketEndpoint | None:
        for endpoint in self.config.endpoints:
            if endpoint.path == path:
                return endpoint
        return None

    async def _send_response(
        self, websocket: WebSocketServerProtocol, response: WebSocketResponse, event_type: str, path: str
    ):
        logging.debug(f'WebSocket event handled: event={event_type}, path={path}')

        # Apply delay if specified
        if response.delay > 0:
            await asyncio.sleep(response.delay / 1000.0)

        # Send response if message is specified
        if response.message:
            response_message = json.dumps(response.message)
            try:
                await websocket.send(response_message)
                logging.debug(f'Sent response to {path}: {response_message}')
            except websockets.exceptions.ConnectionClosed:
                logging.warning(f'Could not send response to {path}, connection closed')

    async def broadcast_message(self, message: str):
        if self.connections:
            await asyncio.gather(*[ws.send(message) for ws in self.connections], return_exceptions=True)
            logging.info(f'Broadcasted message to {len(self.connections)} clients')

    def start(self):
        for endpoint in self.config.endpoints:
            events = []
            if endpoint.on_connect:
                events.append('CONNECT')
            if endpoint.on_message:
                events.append('MESSAGE')
            if endpoint.on_close:
                events.append('CLOSE')
            logging.info(f'Registered WebSocket endpoint: path={endpoint.path}, events={events}')

        logging.info(f'Starting WebSocket server on port {self.port}')

        # Start the WebSocket server
        start_server = websockets.serve(self.handle_client, '0.0.0.0', self.port)

        asyncio.get_event_loop().run_until_complete(start_server)
        logging.info('WebSocket server started')

        try:
            asyncio.get_event_loop().run_forever()
        except KeyboardInterrupt:
            logging.info('Shutting down WebSocket server...')
        finally:
            self.shutdown()

    def shutdown(self):
        logging.info('WebSocket server shutdown complete')


def load_config(config_path: str) -> WebSocketConfig:
    with open(config_path, 'r') as f:
        config_data = json.load(f)

    endpoints = []
    for endpoint_data in config_data:
        on_connect = None
        on_message = None
        on_close = None

        if 'on_connect' in endpoint_data:
            on_connect = WebSocketResponse(**endpoint_data['on_connect'])
        if 'on_message' in endpoint_data:
            on_message = WebSocketResponse(**endpoint_data['on_message'])
        if 'on_close' in endpoint_data:
            on_close = WebSocketResponse(**endpoint_data['on_close'])

        endpoints.append(
            WebSocketEndpoint(
                path=endpoint_data['path'], on_connect=on_connect, on_message=on_message, on_close=on_close
            )
        )

    return WebSocketConfig(endpoints=endpoints)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run a WebSocket mock server.')
    parser.add_argument('--mock-data', type=str, required=True, help='Path to the JSON config file.')
    parser.add_argument('--port', type=int, default=8080, help='Port number to run the server on.')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging.')
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    config = load_config(args.mock_data)
    server = WebSocketMockServer(config, port=args.port)
    server.start()


if __name__ == '__main__':
    main()
