import asyncio
from user_handler import UserHandler
from bot_handler import BotHandler


async def main():
    queue_from_bot = asyncio.Queue()
    queue_to_bot = asyncio.Queue()

    user_handler = UserHandler(queue_from_bot, queue_to_bot)
    bot_handler = BotHandler(queue_from_bot, queue_to_bot)

    await user_handler.start()
    await bot_handler.start()

    await asyncio.gather(
        user_handler.run_until_disconnected(),
        bot_handler.run_until_disconnected()
    )


if __name__ == "__main__":
    asyncio.run(main())
