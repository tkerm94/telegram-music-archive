import os
from math import ceil

import yt_dlp
from aiogram import F, html
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    Message,
    URLInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from thefuzz import fuzz

from .base import *
from .playlists import fetch_tracks


def fetch_playlists_to_add(user_id, track_id, page):
    keyboard = InlineKeyboardBuilder()
    layout = [1]
    playlists = cur.execute(
        "SELECT playlists FROM Users WHERE id = ?", [user_id]
    ).fetchone()[0]
    if playlists:
        playlists = list(map(int, playlists.split(", ")))
        playlists_data = cur.execute(
            f"SELECT id, name, tracks FROM Playlists WHERE id IN ({', '.join('?' for _ in playlists)})",
            playlists,
        ).fetchall()
        names, playlists = [], []
        for playlist_id, name, tracks in playlists_data:
            if str(track_id) not in tracks.split(", "):
                playlists.append(playlist_id)
                names.append(name)
        if page == ceil(len(playlists) / 5):
            page = 0
        elif page == -1:
            page = len(playlists) // 5
        for i, name in enumerate(names[page * 5 : page * 5 + 5]):
            keyboard.button(
                text=name,
                callback_data=Callback(
                    action="add",
                    obj="to_playlist",
                    data=f"{playlists[page * 5 + i]} {track_id}",
                ).pack(),
            )
        if len(names) > 5:
            keyboard.button(
                text="⬅️",
                callback_data=Callback(
                    action="page_add", obj="left", data=f"{page} {track_id}"
                ).pack(),
            )
            keyboard.button(
                text="➡️",
                callback_data=Callback(
                    action="page_add", obj="right", data=f"{page} {track_id}"
                ).pack(),
            )
        layout = [1 for _ in names[page * 5 : page * 5 + 5]] + [2, 1]
    keyboard.button(
        text="Cancel",
        callback_data=Callback(
            action="cancel", obj="adding", data=str(track_id)
        ).pack(),
    )
    keyboard.adjust(*layout)
    keyboard_markup = keyboard.as_markup()
    return len(playlists), keyboard_markup, page + 1


async def search_track_metadata(name):
    track_metadata_uri = "https://music.yandex.ru/handlers/music-search.jsx"
    response = await get_json_response(
        track_metadata_uri,
        params={
            "type": "track",
            "text": name,
        },
    )
    if response is None:
        return None
    tracks = response["tracks"]["items"]
    if not tracks:
        return None
    track = tracks[0]
    title = track["title"]
    artists = []
    artists_data = track["artists"]
    for artist in artists_data:
        artists.append(artist["name"])
    cover_link = "https://" + track["coverUri"][:-2] + "300x300"
    track_data = {
        "title": title,
        "artists": ", ".join(artists),
        "cover_link": cover_link,
    }
    return track_data


def search_track_link(title, artists):
    yt_video = yt_api.search(q=f"{artists} - {title}", count=1, limit=1, return_json=True, search_type="video")["items"]  # type: ignore
    if not yt_video:
        return None
    yt_video = yt_video[0]
    yt_link = "https://www.youtube.com/watch?v=" + yt_video["id"]["videoId"]
    yt_title = yt_video["snippet"]["title"]
    if fuzz.partial_ratio(yt_title.lower(), title.lower()) < 70:
        return None
    return yt_link


@dp.message(F.text.casefold() == "track search")
async def search_track_handler(message: Message, state: FSMContext):
    await state.set_state(States.track_name)
    await message.answer_photo(photo=waiting_img, caption="Type the track name")


@dp.message(States.track_name)
async def searching_track_handler(message: Message, state: FSMContext):
    await state.clear()
    msg = await message.answer_photo(
        photo=waiting_img,
        caption=html.italic("Searching..."),
    )
    data = await search_track_metadata(message.text)
    if data is None:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(
            text="Try again",
            callback_data=Callback(action="search", obj="track", data="").pack(),
        )
        keyboard.adjust(1)
        keyboard_markup = keyboard.as_markup()
        logo = InputMediaPhoto(
            media=error_img,
            caption="Nothing was found for this request",
        )
        await msg.edit_media(logo, reply_markup=keyboard_markup)
        return
    tracks = cur.execute(
        "SELECT * FROM Tracks WHERE title = ?", [data["title"]]
    ).fetchall()
    if not tracks:
        yt_link = search_track_link(data["title"], data["artists"])
        if yt_link is None:
            keyboard = InlineKeyboardBuilder()
            keyboard.button(
                text="Try again",
                callback_data=Callback(action="search", obj="track", data="").pack(),
            )
            keyboard.adjust(1)
            keyboard_markup = keyboard.as_markup()
            logo = InputMediaPhoto(
                media=error_img,
                caption="Nothing was found for this request",
            )
            await msg.edit_media(logo, reply_markup=keyboard_markup)
            return
        data["yt_link"] = yt_link
        sql = "INSERT INTO Tracks(title, artists, cover_link, yt_link) VALUES (?, ?, ?, ?)"
        cur.execute(
            sql, [data["title"], data["artists"], data["cover_link"], data["yt_link"]]
        )
        track_id = cur.lastrowid
        con.commit()
    else:
        track = tracks[0]
        data["yt_link"] = track[4]
        track_id = track[0]
    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text="Download",
        callback_data=Callback(
            action="download", obj="track", data=str(track_id)
        ).pack(),
    )
    keyboard.button(
        text="Add to playlist",
        callback_data=Callback(action="add", obj="track", data=str(track_id)).pack(),
    )
    keyboard.button(
        text="Try again",
        callback_data=Callback(action="search", obj="track", data="").pack(),
    )
    keyboard.adjust(1, 1, 1)
    keyboard_markup = keyboard.as_markup()
    cover = URLInputFile(
        data["cover_link"],
        filename="cover.png",
    )
    caption = html.link(f"{data['artists']} - {data['title']}", data["yt_link"])
    cover = InputMediaPhoto(
        media=cover,
        caption=caption,
    )
    await msg.edit_media(cover, reply_markup=keyboard_markup)


@dp.callback_query(Callback.filter((F.action == "search") & (F.obj == "track")))
async def search_track_again_handler(query: CallbackQuery, state: FSMContext):
    await state.set_state(States.track_name)
    logo = InputMediaPhoto(
        media=waiting_img,
        caption="Type the track name",
    )
    await query.message.edit_media(logo)  # type: ignore


@dp.callback_query(Callback.filter((F.action == "add") & (F.obj == "track")))
async def add_track_handler(query: CallbackQuery, callback_data: Callback):
    track_id = int(callback_data.data)
    playlists, markup, _ = fetch_playlists_to_add(query.from_user.id, track_id, 0)
    logo = InputMediaPhoto(
        media=waiting_img,
        caption=f"{html.bold('Select a playlist')}\nTotal: {playlists}, Page: 1",
    )
    await query.message.edit_media(  # type: ignore
        media=logo,
        reply_markup=markup,
    )


@dp.callback_query(Callback.filter((F.action == "add") & (F.obj == "to_playlist")))
async def adding_track_handler(query: CallbackQuery, callback_data: Callback):
    playlist_id, track_id = map(int, callback_data.data.split())
    sql = "SELECT tracks FROM Playlists WHERE id = ?"
    tracks = cur.execute(sql, [playlist_id]).fetchone()[0]
    if tracks == "":
        tracks = str(track_id)
    else:
        tracks += f", {track_id}"
    sql = "UPDATE Playlists SET tracks = ? WHERE id = ?"
    cur.execute(sql, [tracks, playlist_id])
    con.commit()
    callback_data.data = str(track_id)
    await cancel_adding_track_handler(query, callback_data)


@dp.callback_query(Callback.filter(F.action == "page_add"))
async def change_page_handler(query: CallbackQuery, callback_data: Callback):
    page, track_id = map(int, callback_data.data.split())
    if callback_data.obj == "left":
        page -= 1
    else:
        page += 1
    playlists, markup, page_num = fetch_playlists_to_add(
        query.from_user.id, track_id, page
    )
    logo = InputMediaPhoto(
        media=library_img,
        caption=f"{html.bold('Select a playlist')}\nTotal: {playlists}, Page: {page_num}",
    )
    await query.message.edit_media(logo, reply_markup=markup)  # type: ignore


@dp.callback_query(Callback.filter((F.action == "cancel") & (F.obj == "adding")))
async def cancel_adding_track_handler(query: CallbackQuery, callback_data: Callback):
    track_id = int(callback_data.data)
    sql = "SELECT title, artists, cover_link, yt_link FROM Tracks WHERE id = ?"
    title, artists, cover_link, yt_link = cur.execute(sql, [track_id]).fetchone()
    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text="Download",
        callback_data=Callback(
            action="download", obj="track", data=str(track_id)
        ).pack(),
    )
    keyboard.button(
        text="Add to playlist",
        callback_data=Callback(action="add", obj="track", data=str(track_id)).pack(),
    )
    keyboard.button(
        text="Try again",
        callback_data=Callback(action="search", obj="track", data="").pack(),
    )
    keyboard.adjust(1, 1, 1)
    keyboard_markup = keyboard.as_markup()
    cover = URLInputFile(cover_link, filename="cover.png")
    caption = html.link(f"{artists} - {title}", yt_link)
    cover = InputMediaPhoto(
        media=cover,
        caption=caption,
    )
    await query.message.edit_media(cover, reply_markup=keyboard_markup)  # type: ignore


@dp.callback_query(Callback.filter((F.action == "download") & (F.obj == "track")))
async def download_track_handler(query: CallbackQuery, callback_data: Callback):
    data = callback_data.data.split()
    track_id = int(data[0])
    playlist_id = None
    if len(data) != 1:
        playlist_id = int(data[1])
    logo = InputMediaPhoto(
        media=waiting_img,
        caption=html.italic("Downloading..."),
    )
    await query.message.edit_media(logo)  # type: ignore
    filename = "track_" + str(
        len([name for name in os.listdir("data/cache") if os.path.isfile(name)]) + 1
    )
    title, artists, cover_link, yt_link = cur.execute(
        "SELECT title, artists, cover_link, yt_link FROM Tracks WHERE id = ?",
        [track_id],
    ).fetchone()
    yt_dlp_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "socket_timeout": 10,
        "outtmpl": f"data/cache/{filename}",
    }
    with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
        try:
            ydl.download([yt_link])
        except Exception:
            keyboard = InlineKeyboardBuilder()
            keyboard.button(
                text="Try again",
                callback_data=Callback(action="search", obj="track", data="").pack(),
            )
            keyboard.adjust(1)
            keyboard_markup = keyboard.as_markup()
            logo = InputMediaPhoto(
                media=error_img,
                caption="An error occurred\nPlease try again later",
            )
            await query.message.edit_media(logo, reply_markup=keyboard_markup)  # type: ignore
            return
    track = FSInputFile(f"data/cache/{filename}.mp3", f"{artists} - {title}")
    cover = InputMediaPhoto(
        media=URLInputFile(
            cover_link,
            filename="cover.png",
        ),
    )
    await query.message.edit_media(cover)  # type: ignore
    await query.message.answer_audio(track)  # type: ignore
    if playlist_id:
        logo, name = cur.execute(
            "SELECT logo, name FROM Playlists WHERE id = ?", [playlist_id]
        ).fetchone()
        tracks, markup, _ = fetch_tracks(playlist_id, 0)
        caption = f"{html.bold(name)}\nTotal: {tracks}, Page: 1"
        await query.message.answer_photo(library_img, caption=caption, reply_markup=markup)  # type: ignore
    os.remove(f"data/cache/{filename}.mp3")
