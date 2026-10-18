"""__NAME__ module. Replace this skeleton; keep the build() + __main__ shape."""

from __future__ import annotations

from mycelium_sdk import Module


def build(**kwargs) -> Module:
    """Create the module and register handlers. Tests call build(bus=..., data_dir=..., manifest_path=...)."""
    mod = Module(**kwargs)

    # @mod.on("sense.chat")
    # async def on_chat(msg):
    #     ...

    # @mod.on_request("summary")
    # async def summary(data):
    #     return {...}

    return mod


if __name__ == "__main__":
    build().run()
