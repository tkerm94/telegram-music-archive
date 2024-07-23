import sqlite3
from os import getenv

import aiohttp
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from pyyoutube import Api


class Callback(CallbackData, prefix="button", sep="^"):
    action: str
    obj: str
    data: str


class States(StatesGroup):
    playlist_name = State()
    track_name = State()


def init_db():
    sql = "CREATE TABLE IF NOT EXISTS Users (id INTEGER UNIQUE, playlists TEXT)"
    cur.execute(sql)
    sql = "CREATE TABLE IF NOT EXISTS Playlists (id INTEGER PRIMARY KEY, name TEXT, logo BLOB, tracks TEXT)"
    cur.execute(sql)
    sql = "CREATE TABLE IF NOT EXISTS Tracks (id INTEGER PRIMARY KEY, title TEXT, artists TEXT, cover_link TEXT, yt_link TEXT)"
    cur.execute(sql)
    con.commit()


async def get_json_response(url, params=None):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if not resp.ok:
                return None
            return await resp.json()


async def get_text_response(url, params=None):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if not resp.ok:
                return None
            return await resp.text()


BOT_TOKEN = getenv("BOT_TOKEN")
YT_TOKEN = getenv("YT_TOKEN")

library_img = FSInputFile("data/img/library.png", "library.png")
waiting_img = FSInputFile("data/img/waiting.png", "waiting.png")
error_img = FSInputFile("data/img/error.png", "error.png")

con = sqlite3.connect("data/db/music.db")
cur = con.cursor()
init_db()
dp = Dispatcher()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))  # type: ignore
yt_api = Api(api_key=YT_TOKEN)


@dp.message(CommandStart())
async def command_start_handler(message: Message):
    cur.execute("INSERT OR IGNORE INTO Users(id, playlists) VALUES (?, ?)", [message.from_user.id, ""])  # type: ignore
    con.commit()
    keyboard = ReplyKeyboardBuilder()
    keyboard.button(text="My library")
    keyboard.button(text="Track search")
    keyboard.adjust(1)
    keyboard_markup = keyboard.as_markup(row_width=1, resize_keyboard=True)
    text = [
        html.bold("Hi! I'm the telegram music storage bot!\n"),
        "I know how to search and download tracks,",
        "and I can maintain and organize your music library.",
        "You can control me with the buttons you now have.",
        html.spoiler(html.italic("\nGood luck!")),
    ]
    await message.answer_photo(
        photo=waiting_img, caption="\n".join(text), reply_markup=keyboard_markup
    )
