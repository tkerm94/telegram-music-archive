import asyncio
import logging
import sys

from handlers.base import *
from handlers.playlists import *
from handlers.tracks import *


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
