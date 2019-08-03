from asyncio import get_event_loop
from typing import Any, Awaitable, Callable, Dict, Generic, Type, TypeVar, overload

from httpx import AsyncClient, AsyncRequest, AsyncResponse
from pydantic import ValidationError
from pydantic.generics import GenericModel
from starlette.status import HTTP_200_OK

from fastapi_client.api.pet_api import PetApi
from fastapi_client.api.store_api import StoreApi
from fastapi_client.api.user_api import UserApi
from fastapi_client.exceptions import ApiRequestException, UnexpectedResponse

T = TypeVar("T")


class _ResultMaker(GenericModel, Generic[T]):
    result: T


Send = Callable[[AsyncRequest], Awaitable[AsyncResponse]]
MiddlewareT = Callable[[AsyncRequest, Send], Awaitable[AsyncResponse]]


class BaseMiddleware:
    async def __call__(self, request: AsyncRequest, call_next: Send) -> AsyncResponse:
        return await call_next(request)


class ApiClient:
    def __init__(self, host: str = None, **kwargs: Any) -> None:
        self.host = host
        self.middleware: MiddlewareT = BaseMiddleware()
        self._async_client = AsyncClient()

    @overload
    async def request(
        self, *, type_: Type[T], method: str, url: str, path_params: Dict[str, Any] = None, **kwargs: Any
    ) -> T:
        ...

    @overload  # noqa F811
    async def request(
        self, *, type_: None, method: str, url: str, path_params: Dict[str, Any] = None, **kwargs: Any
    ) -> None:
        ...

    async def request(  # noqa F811
        self, *, type_: Any, method: str, url: str, path_params: Dict[str, Any] = None, **kwargs: Any
    ) -> Any:
        if path_params is None:
            path_params = {}
        url = (self.host or "") + url.format(**path_params)
        request = AsyncRequest(method, url, **kwargs)
        return await self.send(request, type_)

    @overload
    def request_sync(self, *, type_: Type[T], **kwargs: Any) -> T:
        ...

    @overload  # noqa F811
    def request_sync(self, *, type_: None, **kwargs: Any) -> None:
        ...

    def request_sync(self, *, type_: Any, **kwargs: Any) -> Any:  # noqa F811
        return get_event_loop().run_until_complete(self.request(type_=type_, **kwargs))

    async def send(self, request: AsyncRequest, type_: Type[T]) -> T:
        response = await self.middleware(request, self.send_inner)
        if response.status_code == HTTP_200_OK:
            try:
                return _ResultMaker[type_](result=response.json()).result  # type: ignore
            except ValidationError as e:
                raise ApiRequestException(e)
        raise UnexpectedResponse.for_response(response)

    async def send_inner(self, request: AsyncRequest) -> AsyncResponse:
        try:
            response = await self._async_client.send(request)
        except Exception as e:
            raise ApiRequestException(e)
        return response

    def add_middleware(self, middleware: MiddlewareT) -> None:
        current_middleware = self.middleware

        async def new_middleware(request: AsyncRequest, call_next: Send) -> AsyncResponse:
            async def inner_send(request: AsyncRequest) -> AsyncResponse:
                return await current_middleware(request, call_next)

            return await middleware(request, inner_send)

        self.middleware = new_middleware


ClientT = TypeVar("ClientT", bound=ApiClient)


class Apis(Generic[ClientT]):
    def __init__(self, client: ClientT):
        self.client = client

        self.pet_api = PetApi(self.client)
        self.store_api = StoreApi(self.client)
        self.user_api = UserApi(self.client)
