import asyncio
from llama_index.core.workflow import (
    Workflow,
    step,
    Context,
    StartEvent,
    StopEvent,
)


class DebugWorkflow(Workflow):
    @step
    async def start(self, ctx: Context, ev: StartEvent) -> StopEvent:
        print(f"DEBUG: ctx type: {type(ctx)}")
        # print(f"DEBUG: ctx dir: {dir(ctx)}")

        try:
            print(f"DEBUG: ctx.store type: {type(ctx.store)}")
            print(f"DEBUG: ctx.store dir: {dir(ctx.store)}")
        except Exception as e:
            print(f"DEBUG: Error accessing ctx.store: {e}")

        return StopEvent(result="Done")


async def main():
    w = DebugWorkflow(timeout=10, verbose=True)
    await w.run()


if __name__ == "__main__":
    asyncio.run(main())
