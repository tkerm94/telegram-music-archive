from io import BytesIO
from math import ceil

from aiogram import F, html
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InputMediaPhoto,
    Message,
    URLInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from cairosvg import svg2png
from PIL import Image

from .base import *


def fetch_tracks(playlist_id, page):
    keyboard = InlineKeyboardBuilder()
    layout = [1]
    sql = "SELECT tracks FROM Playlists WHERE id = ?"
    tracks = cur.execute(sql, [playlist_id]).fetchone()[0]
    if tracks != "":
        tracks = list(map(int, tracks.split(", ")))
        sql = f"SELECT artists, title FROM Tracks WHERE id IN ({', '.join('?' for _ in tracks)})"
        names = list(
            map(lambda x: f"{x[0]} - {x[1]}", cur.execute(sql, tracks).fetchall())
        )
        if page == ceil(len(tracks) / 5):
            page = 0
        elif page == -1:
            page = len(tracks) // 5
        for i, name in enumerate(names[page * 5 : page * 5 + 5]):
            keyboard.button(
                text=name,
                callback_data=Callback(
                    action="show",
                    obj="track",
                    data=f"{playlist_id} {str(tracks[page * 5 + i])}",
                ).pack(),
            )
        if len(names) > 5:
            keyboard.button(
                text="⬅️",
                callback_data=Callback(
                    action="page", obj="left tracks", data=f"{playlist_id} {page}"
                ).pack(),
            )
            keyboard.button(
                text="➡️",
                callback_data=Callback(
                    action="page", obj="right tracks", data=f"{playlist_id} {page}"
                ).pack(),
            )
        layout = [1 for _ in names[page * 5 : page * 5 + 5]] + [2, 1]
    keyboard.button(
        text="Go back",
        callback_data=Callback(action="cancel", obj="playlist", data="").pack(),
    )
    keyboard.adjust(*layout)
    keyboard_markup = keyboard.as_markup()
    return len(tracks), keyboard_markup, page + 1


def fetch_playlists(user_id, page):
    keyboard = InlineKeyboardBuilder()
    layout = [1]
    playlists = cur.execute(
        "SELECT playlists FROM Users WHERE id = ?", [user_id]
    ).fetchone()[0]
    if playlists:
        playlists = list(map(int, playlists.split(", ")))
        names = cur.execute(
            f"SELECT name FROM Playlists WHERE id IN ({', '.join('?' for _ in playlists)})",
            playlists,
        ).fetchall()
        if page == ceil(len(playlists) / 5):
            page = 0
        elif page == -1:
            page = len(playlists) // 5
        for i, name in enumerate(names[page * 5 : page * 5 + 5]):
            keyboard.button(
                text=name[0],
                callback_data=Callback(
                    action="show", obj="playlist", data=str(playlists[page * 5 + i])
                ).pack(),
            )
        if len(names) > 5:
            keyboard.button(
                text="⬅️",
                callback_data=Callback(
                    action="page", obj="left playlists", data=str(page)
                ).pack(),
            )
            keyboard.button(
                text="➡️",
                callback_data=Callback(
                    action="page", obj="right playlists", data=str(page)
                ).pack(),
            )
        layout = [1 for _ in names[page * 5 : page * 5 + 5]] + [2, 1]
    keyboard.button(
        text="Create new playlist",
        callback_data=Callback(action="new", obj="playlist", data="").pack(),
    )
    keyboard.adjust(*layout)
    keyboard_markup = keyboard.as_markup()
    return len(playlists), keyboard_markup, page + 1


@dp.message(F.text.casefold() == "my library")
async def show_library_handler(message: Message):
    playlists, markup, _ = fetch_playlists(message.from_user.id, 0)  # type: ignore
    await message.answer_photo(
        photo=library_img,
        caption=f"{html.bold('Your playlists')}\nTotal: {playlists}, Page: 1",
        reply_markup=markup,
    )


@dp.callback_query(Callback.filter((F.action == "new") & (F.obj == "playlist")))
async def create_playlist_handler(query: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text="Cancel",
        callback_data=Callback(action="cancel", obj="playlist", data="").pack(),
    )
    keyboard_markup = keyboard.as_markup()
    await state.set_state(States.playlist_name)
    logo = InputMediaPhoto(
        media=waiting_img,
        caption="Type the new playlist name",
    )
    await query.message.edit_media(logo, reply_markup=keyboard_markup)  # type: ignore


@dp.message(States.playlist_name)
async def creating_playlist_handler(message: Message, state: FSMContext):
    await state.clear()
    random_logo_uri = f'https://source.boringavatars.com/bauhaus/320/"{message.text}"'
    response = await get_text_response(
        random_logo_uri,
        params={"square": ""},
    )
    if response is None:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(
            text="Try again",
            callback_data=Callback(action="new", obj="playlist", data="").pack(),
        )
        keyboard.adjust(1)
        keyboard_markup = keyboard.as_markup()
        await message.answer_photo(
            error_img,
            caption="An error occurred\nPlease try again later",
            reply_markup=keyboard_markup,
        )
        return
    logo = svg2png(response)
    logo = Image.open(BytesIO(logo))  # type: ignore
    logo = logo.crop((10, 10, 310, 310))
    logo_bytes = BytesIO()
    logo.save(logo_bytes, format="PNG")
    logo = logo_bytes.getvalue()
    cur.execute("INSERT INTO Playlists(name, logo, tracks) VALUES (?, ?, ?)", [message.text, logo, ""])  # type: ignore
    playlist_id = cur.lastrowid
    user_playlists = cur.execute("SELECT playlists FROM Users WHERE id = ?", [message.from_user.id]).fetchone()[0]  # type: ignore
    if user_playlists == "":
        user_playlists = str(playlist_id)
    else:
        user_playlists += f", {playlist_id}"
    cur.execute("UPDATE Users SET playlists = ? WHERE id = ?", [user_playlists, message.from_user.id])  # type: ignore
    con.commit()
    await bot.edit_message_reply_markup(
        chat_id=message.chat.id, message_id=message.message_id - 1, reply_markup=None
    )
    await show_library_handler(message)


@dp.callback_query(Callback.filter((F.action == "show") & (F.obj == "track")))
async def show_track_handler(query: CallbackQuery, callback_data: Callback):
    playlist_id, track_id = map(int, callback_data.data.split())
    sql = "SELECT title, artists, cover_link, yt_link FROM Tracks WHERE id = ?"
    title, artists, cover_link, yt_link = cur.execute(sql, [track_id]).fetchone()
    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text="Download",
        callback_data=Callback(
            action="download", obj="track", data=f"{track_id} {playlist_id}"
        ).pack(),
    )
    keyboard.button(
        text="Go back",
        callback_data=Callback(
            action="show", obj="playlist", data=str(playlist_id)
        ).pack(),
    )
    keyboard.adjust(1, 1)
    keyboard_markup = keyboard.as_markup()
    cover = URLInputFile(cover_link, filename="cover.png")
    caption = html.link(f"{artists} - {title}", yt_link)
    cover = InputMediaPhoto(
        media=cover,
        caption=caption,
    )
    await query.message.edit_media(cover, reply_markup=keyboard_markup)  # type: ignore


@dp.callback_query(Callback.filter((F.action == "show") & (F.obj == "playlist")))
async def show_playlist_handler(query: CallbackQuery, callback_data: Callback):
    logo, name = cur.execute(
        "SELECT logo, name FROM Playlists WHERE id = ?", [int(callback_data.data)]
    ).fetchone()
    tracks, markup, _ = fetch_tracks(int(callback_data.data), 0)
    photo = InputMediaPhoto(
        media=BufferedInputFile(logo, filename="logo.png"),
        caption=f"{html.bold(name)}\nTotal: {tracks}, Page: 1",
    )
    await query.message.edit_media(photo, reply_markup=markup)  # type: ignore


@dp.callback_query(Callback.filter((F.action == "cancel") & (F.obj == "playlist")))
async def cancel_playlist_handler(query: CallbackQuery, state: FSMContext):
    await state.clear()
    playlists, markup, _ = fetch_playlists(query.from_user.id, 0)  # type: ignore
    logo = InputMediaPhoto(
        media=library_img,
        caption=f"{html.bold('Your playlists')}\nTotal: {playlists}, Page: 1",
    )
    await query.message.edit_media(logo, reply_markup=markup)  # type: ignore


@dp.callback_query(Callback.filter(F.action == "page"))
async def change_page_handler(query: CallbackQuery, callback_data: Callback):
    obj = callback_data.obj.split()
    if obj[1] == "playlists":
        page = int(callback_data.data)
        if obj[0] == "left":
            page -= 1
        else:
            page += 1
        playlists, markup, page_num = fetch_playlists(query.from_user.id, page)
        logo = InputMediaPhoto(
            media=library_img,
            caption=f"{html.bold('Your playlists')}\nTotal: {playlists}, Page: {page_num}",
        )
        await query.message.edit_media(logo, reply_markup=markup)  # type: ignore
    else:
        playlist_id, page = map(int, callback_data.data.split())
        logo, name = cur.execute(
            "SELECT logo, name FROM Playlists WHERE id = ?", [playlist_id]
        ).fetchone()
        if obj[1] == "left":
            page -= 1
        else:
            page += 1
        tracks, markup, page_num = fetch_tracks(playlist_id, page)
        logo = InputMediaPhoto(
            media=BufferedInputFile(logo, "logo.png"),
            caption=f"{html.bold(name)}\nTotal: {tracks}, Page: {page_num}",
        )
        await query.message.edit_media(logo, reply_markup=markup)  # type: ignore
