# uv run --with-requirements requirements.txt fastapi_mock_server.py --mock-data="../data/sample.json"

import argparse
import asyncio
import dataclasses
import json
import logging
import typing

import uvicorn
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse


@dataclasses.dataclass
class ResponseFormat:
    status: int
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    body: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ApiFormat:
    url: str
    method: str
    response: ResponseFormat
    delay: int = 0


@dataclasses.dataclass
class Config:
    routes: list[ApiFormat]


class MockServer:
    def __init__(self, config: Config, port: int = 8080):
        self.config = config
        self.port = port
        self.app = FastAPI(title='Mock API Server')
        self._setup_routes()

    def _setup_routes(self):
        for route in self.config.routes:
            self._add_route(route)
            logging.info(f'Registered endpoint: method={route.method}, url={route.url}')

    def _add_route(self, api: ApiFormat):
        async def route_handler(request: Request):
            # Apply delay if specified
            if api.delay > 0:
                await asyncio.sleep(api.delay / 1000.0)

            logging.debug(f'API request handled: method={api.method}, url={api.url}, status={api.response.status}')

            # Prepare response
            content = api.response.body if api.response.body else None

            return JSONResponse(content=content, status_code=api.response.status, headers=api.response.headers)

        # Add route for the specific HTTP method
        if api.method.upper() == 'GET':
            self.app.get(api.url)(route_handler)
        elif api.method.upper() == 'POST':
            self.app.post(api.url)(route_handler)
        elif api.method.upper() == 'PUT':
            self.app.put(api.url)(route_handler)
        elif api.method.upper() == 'DELETE':
            self.app.delete(api.url)(route_handler)
        elif api.method.upper() == 'PATCH':
            self.app.patch(api.url)(route_handler)
        elif api.method.upper() == 'OPTIONS':
            self.app.options(api.url)(route_handler)

    def start(self):
        logging.info(f'Starting server on port {self.port}')
        uvicorn.run(
            self.app,
            host='0.0.0.0',
            port=self.port,
            log_level='info' if logging.getLogger().getEffectiveLevel() == logging.INFO else 'debug',
        )


def load_config(config_path: str) -> Config:
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
    return Config(routes=routes)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run a FastAPI mock server.')
    parser.add_argument('--mock-data', type=str, required=True, help='Path to the JSON config file.')
    parser.add_argument('--port', type=int, default=8080, help='Port number to run the server on.')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging.')
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    config = load_config(args.mock_data)
    server = MockServer(config, port=args.port)
    server.start()


if __name__ == '__main__':
    main()
