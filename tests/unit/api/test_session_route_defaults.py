from __future__ import annotations

from inspect import signature

from newbro.api.routes.sessions import list_bro_thread_page


def test_bro_thread_page_route_default_limit_is_iot_friendly() -> None:
    params = signature(list_bro_thread_page).parameters

    assert params["limit"].default == 15
