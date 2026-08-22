import asyncio
import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any


def debounce(wait_time: float):
    """
    A decorator that delays a function execution until 'wait_time'
    seconds have passed since the last time it was called.
    """

    def decorator(func: Callable[..., Any]):
        # Track the active background task
        debounced_task: asyncio.Task | None = None

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            nonlocal debounced_task

            # Cancel the previous scheduled call if it exists
            if debounced_task and not debounced_task.done():
                debounced_task.cancel()

            # Define the delayed execution wrapper
            async def delayed_execution():
                await asyncio.sleep(wait_time)
                # Check if the function is a coroutine or normal function
                if inspect.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    func(*args, **kwargs)

            # Schedule the new execution
            debounced_task = asyncio.create_task(delayed_execution())

        return wrapper

    return decorator


# --- Example Usage ---
@debounce(0.5)
async def process_search_query(query: str):
    print(f"Searching API for: '{query}'")


async def main():
    print("User starts typing rapidly...")
    await process_search_query("p")
    await asyncio.sleep(0.00001)
    await process_search_query("py")
    await asyncio.sleep(0.00001)
    await process_search_query("pyth")
    await asyncio.sleep(0.00001)
    await process_search_query("python")  # Only this last call executes

    # Wait long enough for the debounce timer to finish
    await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
