import asyncio

from text2sql.config.settings import Settings
from text2sql.eval.pipeline_setup import llm_for, local_model_reachable


def test_local_choice_swaps_only_the_generation_model(settings: Settings) -> None:
    main = llm_for(settings, "main")
    local = llm_for(settings, "local")
    assert main.models["main"] == settings.llm_model_main
    assert local.models["main"] == settings.llm_model_local
    assert local.models["fast"] == main.models["fast"]  # same input classifier


async def test_local_model_reachable() -> None:
    server = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await local_model_reachable(f"http://127.0.0.1:{port}")
    finally:
        server.close()
        await server.wait_closed()
    assert not await local_model_reachable(f"http://127.0.0.1:{port}", timeout_s=1.0)
    assert not await local_model_reachable(None)
