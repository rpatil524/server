import typing as t

from django.conf import settings

# Not at the top of the file because we first need to setup django
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from .exceptions import CustomHttpException
from .msgpack import MsgpackResponse
from .routers.authentication import authentication_router
from .routers.collection import collection_router, item_router
from .routers.invitation import invitation_incoming_router, invitation_outgoing_router
from .routers.member import member_router
from .routers.websocket import websocket_router


def create_application(prefix="", middlewares=[]):
    app = FastAPI(
        title="Etebase",
        description="The Etebase server API documentation",
        externalDocs={
            "url": "https://docs.etebase.com",
            "description": "Docs about the API specifications and clients.",
        },
        # FIXME: version="2.5.0",
    )
    VERSION = "v1"  # noqa: N806
    BASE_PATH = f"{prefix}/api/{VERSION}"  # noqa: N806
    COLLECTION_UID_MARKER = "{collection_uid}"  # noqa: N806
    app.include_router(authentication_router, prefix=f"{BASE_PATH}/authentication", tags=["authentication"])
    app.include_router(collection_router, prefix=f"{BASE_PATH}/collection", tags=["collection"])
    app.include_router(item_router, prefix=f"{BASE_PATH}/collection/{COLLECTION_UID_MARKER}", tags=["item"])
    app.include_router(member_router, prefix=f"{BASE_PATH}/collection/{COLLECTION_UID_MARKER}", tags=["member"])
    app.include_router(
        invitation_incoming_router, prefix=f"{BASE_PATH}/invitation/incoming", tags=["incoming invitation"]
    )
    app.include_router(
        invitation_outgoing_router, prefix=f"{BASE_PATH}/invitation/outgoing", tags=["outgoing invitation"]
    )
    app.include_router(websocket_router, prefix=f"{BASE_PATH}/ws", tags=["websocket"])

    if settings.DEBUG:
        from .routers.test_reset_view import test_reset_view_router

        app.include_router(test_reset_view_router, prefix=f"{BASE_PATH}/test/authentication")

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex="https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

    for middleware in middlewares:
        app.add_middleware(middleware)

    @app.on_event("startup")
    async def on_startup() -> None:
        from .redis import redisw

        await redisw.setup()

    @app.on_event("shutdown")
    async def on_shutdown():
        from .redis import redisw

        await redisw.close()

    @app.exception_handler(CustomHttpException)
    async def custom_exception_handler(request: Request, exc: CustomHttpException):
        return MsgpackResponse(status_code=exc.status_code, content=exc.as_dict)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        from pydantic import TypeAdapter

        errors = TypeAdapter(t.Dict[str, t.Any])
        return MsgpackResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=errors.dump_python({"detail": exc.errors()}),
        )

    app.mount(settings.STATIC_URL, StaticFiles(directory=settings.STATIC_ROOT), name="static")

    return app
