# aspire.core.reactorsecurity.py | Aspire Security Services | Csware | Feb 5 2020 | MIT

import json
import typing

from aspire.core import Core as Middleware,  status
from aspire.core.reactor import (
    BaseHTTPMiddleware, ExceptionMiddleware, ServerErrorMiddleware, BaseRoute, Router,
    ASGIApp, Receive, Scope, Send,
    BackgroundTasks, run_in_threadpool, Request, 
    HTMLResponse, JSONResponse, PlainTextResponse, Response,
    State, URLPath

)

try:
    import graphene
    from graphql.execution.executors.asyncio import AsyncioExecutor
    from graphql.error import format_error as format_graphql_error
    from graphql.error import GraphQLError
except ImportError:  # pragma: nocover
    graphene = None  # type: ignore
    AsyncioExecutor = None  # type: ignore
    format_graphql_error = None  # type: ignore
    GraphQLError = None  # type: ignore


#---------------------------- Aspiration Application ------------------------------
class Aspiration:
    def __init__(
        self,
        debug: bool = False,
        routes: typing.List[BaseRoute] = None,
        middleware: typing.List[Middleware] = None,
        exception_handlers: typing.Dict[
            typing.Union[int, typing.Type[Exception]], typing.Callable
        ] = None,
        on_startup: typing.List[typing.Callable] = None,
        on_shutdown: typing.List[typing.Callable] = None,
    ) -> None:
        self._debug = debug
        self.state = State()
        self.router = Router(routes, on_startup=on_startup, on_shutdown=on_shutdown)
        self.exception_handlers = (
            {} if exception_handlers is None else dict(exception_handlers)
        )
        self.user_middleware = list(middleware or [])
        self.middleware_stack = self.build_middleware_stack()

    def build_middleware_stack(self) -> ASGIApp:
        debug = self.debug
        error_handler = None
        exception_handlers = {}

        for key, value in self.exception_handlers.items():
            if key in (500, Exception):
                error_handler = value
            else:
                exception_handlers[key] = value

        server_errors = Middleware(
            ServerErrorMiddleware, options={"handler": error_handler, "debug": debug},
        )
        exceptions = Middleware(
            ExceptionMiddleware,
            options={"handlers": exception_handlers, "debug": debug},
        )

        middleware = [server_errors] + self.user_middleware + [exceptions]

        app = self.router
        for cls, options, enabled in reversed(middleware):
            if enabled:
                app = cls(app=app, **options)
        return app

    @property
    def routes(self) -> typing.List[BaseRoute]:
        return self.router.routes

    @property
    def debug(self) -> bool:
        return self._debug

    @debug.setter
    def debug(self, value: bool) -> None:
        self._debug = value
        self.middleware_stack = self.build_middleware_stack()

    def on_event(self, event_type: str) -> typing.Callable:
        return self.router.lifespan.on_event(event_type)

    def mount(self, path: str, app: ASGIApp, name: str = None) -> None:
        self.router.mount(path, app=app, name=name)

    def host(self, host: str, app: ASGIApp, name: str = None) -> None:
        self.router.host(host, app=app, name=name)

    def add_middleware(self, middleware_class: type, **kwargs: typing.Any) -> None:
        self.user_middleware.insert(0, Middleware(middleware_class, options=kwargs))
        self.middleware_stack = self.build_middleware_stack()

    def add_exception_handler(
        self,
        exc_class_or_status_code: typing.Union[int, typing.Type[Exception]],
        handler: typing.Callable,
    ) -> None:
        self.exception_handlers[exc_class_or_status_code] = handler
        self.middleware_stack = self.build_middleware_stack()

    def add_event_handler(self, event_type: str, func: typing.Callable) -> None:
        self.router.lifespan.add_event_handler(event_type, func)

    def add_route(
        self,
        path: str,
        route: typing.Callable,
        methods: typing.List[str] = None,
        name: str = None,
        include_in_schema: bool = True,
    ) -> None:
        self.router.add_route(
            path, route, methods=methods, name=name, include_in_schema=include_in_schema
        )

    def add_websocket_route(
        self, path: str, route: typing.Callable, name: str = None
    ) -> None:
        self.router.add_websocket_route(path, route, name=name)

    def exception_handler(
        self, exc_class_or_status_code: typing.Union[int, typing.Type[Exception]]
    ) -> typing.Callable:
        def decorator(func: typing.Callable) -> typing.Callable:
            self.add_exception_handler(exc_class_or_status_code, func)
            return func

        return decorator

    def route(
        self,
        path: str,
        methods: typing.List[str] = None,
        name: str = None,
        include_in_schema: bool = True,
    ) -> typing.Callable:
        def decorator(func: typing.Callable) -> typing.Callable:
            self.router.add_route(
                path,
                func,
                methods=methods,
                name=name,
                include_in_schema=include_in_schema,
            )
            return func

        return decorator

    def websocket_route(self, path: str, name: str = None) -> typing.Callable:
        def decorator(func: typing.Callable) -> typing.Callable:
            self.router.add_websocket_route(path, func, name=name)
            return func

        return decorator

    def middleware(self, middleware_type: str) -> typing.Callable:
        if not middleware_type == "http":
            raise Exception('Currently only middleware("http") is supported.')
        #assert (
        #    middleware_type == "http"
        #), 'Currently only middleware("http") is supported.'

        def decorator(func: typing.Callable) -> typing.Callable:
            self.add_middleware(BaseHTTPMiddleware, dispatch=func)
            return func

        return decorator

    def url_path_for(self, name: str, **path_params: str) -> URLPath:
        return self.router.url_path_for(name, **path_params)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope["app"] = self
        await self.middleware_stack(scope, receive, send)


#---------------------------- GraphQL Application ------------------------------

