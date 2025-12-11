import telebot
import requests
from telebot import types
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time
import threading
import os
import re
import json
import urllib.parse

load_dotenv()
TOKEN = os.getenv("TOKEN")
PANDA_SCORE = os.getenv("PANDA_SCORE")
bot = telebot.TeleBot(TOKEN)

headers = {"Authorization": f"Bearer {PANDA_SCORE}"}
user_sub = {}

Games = {
    "lol": "League of Legends",
    "csgo": "CS2",              
    "dota2": "Dota 2",
    "valorant": "Valorant",
    "r6-siege": "Rainbow Six"
}

def md_escape(text: str) -> str:
    if not text:
        return ""
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f"\\{ch}")
    return text

def api_get(path, params=None, timeout=10):
    url = f"https://api.pandascore.co/{path}"
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_upcoming_matches_by_game(game_key, per_page=10):
    try:
        return api_get(f"{game_key}/matches/upcoming", params={"per_page": per_page})
    except Exception:
        return []

def get_running_matches_by_game(game_key):
    try:
        return api_get(f"{game_key}/matches/running")
    except Exception:
        return []

def get_match_details(match_id):
    try:
        return api_get(f"matches/{match_id}")
    except Exception:
        return None

def to_almaty(utc_str):
    if not utc_str:
        return "Неизвестно"
    try:
        utc_time = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        try:
            utc_time = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        except Exception:
            return "Неизвестно"
    almaty_time = utc_time + timedelta(hours=6)
    return almaty_time.strftime("%H:%M, %d.%m.%Y")

def normalize_twitch_url(url: str):
    if not url:
        return None
    if "player.twitch.tv" in url and "channel=" in url:
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query)
        channel = q.get("channel")
        if channel:
            return f"https://www.twitch.tv/{channel[0]}"
    if "twitch.tv" in url or "youtube.com" in url or "youtu.be" in url:
        return url
    return None

def find_stream_link(match_obj):
    if not match_obj:
        return None
    streams = match_obj.get("streams") or {}

    if isinstance(streams, list):
        for s in streams:
            url = s.get("raw_url") or s.get("url") or s.get("embed")
            url = normalize_twitch_url(url)
            if url:
                return url

    if isinstance(streams, dict) and "list" in streams:
        for s in streams["list"]:
            url = s.get("raw_url") or s.get("url") or s.get("embed")
            url = normalize_twitch_url(url)
            if url:
                return url

    try:
        s = json.dumps(match_obj)
        urls = re.findall(r"https?://[^\s\"'\\]+", s)
        for u in urls:
            u = normalize_twitch_url(u)
            if u:
                return u
    except Exception:
        pass
    return None

@bot.message_handler(commands=['start'])
def start(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Посмотреть матчи", callback_data="start_matches"))
    kb.add(types.InlineKeyboardButton("Подписаться на уведомления", callback_data="start_alerts"))
    kb.add(types.InlineKeyboardButton("Отписаться от уведомлений", callback_data="unsubscribe"))

    text = (
        "Привет! Я бот для отслеживания киберспортивных матчей.\n\n"
        "Вот что я умею:\n"
        "/matches — посмотреть ближайшие матчи по выбранной игре\n"
        "/alerts — подписаться на уведомления о начале матчей\n"
        "/unsubscribe — отписаться от уведомлений\n\n"
        "Я поддерживаю игры: League of Legends, CS2, Dota 2, Valorant, Rainbow Six.\n"
        "Все уведомления приходят с ссылками на стримы (Twitch/YouTube).\n\n"
        "Просто выбери команду или кнопку ниже!"
    )
    bot.send_message(message.chat.id, md_escape(text), parse_mode="MarkdownV2", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["start_matches", "start_alerts", "unsubscribe"])
def start_buttons(call):
    if call.data == "start_matches":
        choose_game_for_matches(call.message)
    elif call.data == "start_alerts":
        alert(call.message)
    elif call.data == "unsubscribe":
        user_id = call.message.chat.id
        if user_id in user_sub:
            del user_sub[user_id]
        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "Вы отписаны от всех уведомлений.")
@bot.message_handler(commands=['unsubscribe'])
def unsubscribe(message):
    user = message.chat.id
    if user in user_sub:
        del user_sub[user]
        bot.send_message(user, "Вы отписаны от всех уведомлений.")
    else:
        bot.send_message(user, "Вы не были подписаны ни на одну игру.")
@bot.message_handler(commands=['alerts'])
def alert(message):
    kb = types.InlineKeyboardMarkup()
    for key, title in Games.items():
        kb.add(types.InlineKeyboardButton(title, callback_data=f"alertgame_{key}"))
    bot.send_message(message.chat.id, "На какую игру вы хотите получать уведомления?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("alertgame_"))
def choose_game_for_alerts(call):
    user = call.message.chat.id
    game_key = call.data.split("_", 1)[1]
    user_sub[user] = game_key
    bot.answer_callback_query(call.id)
    bot.send_message(user, f"Вы подписаны на уведомления по игре: *{md_escape(Games.get(game_key, game_key))}*", parse_mode="MarkdownV2")

@bot.message_handler(commands=['matches'])
def choose_game_for_matches(message):
    kb = types.InlineKeyboardMarkup()
    for key, title in Games.items():
        kb.add(types.InlineKeyboardButton(title, callback_data=f"matchgame_{key}"))
    bot.send_message(message.chat.id, "Выберите игру, по которой хотите посмотреть предстоящие матчи:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("matchgame_"))
def show_upcoming_matches(call):
    game_key = call.data.split("_", 1)[1]
    game_name = Games.get(game_key, game_key)
    bot.answer_callback_query(call.id)

    matches = get_upcoming_matches_by_game(game_key, per_page=10)
    if not matches:
        bot.send_message(call.message.chat.id, f"Матчи по игре {game_name} отсутствуют.")
        return

    kb = types.InlineKeyboardMarkup()
    text_lines = [f"🎮 Ближайшие матчи — {game_name}: \n"]
    for m in matches:
        m_id = m.get("id")
        opponents = m.get("opponents", [])
        t1 = opponents[0]["opponent"]["name"] if len(opponents) > 0 else "-"
        t2 = opponents[1]["opponent"]["name"] if len(opponents) > 1 else "-"
        time_local = to_almaty(m.get("scheduled_at") or m.get("begin_at"))
        text_lines.append(f"• {t1} vs {t2} — {time_local}")
        kb.add(types.InlineKeyboardButton(f"{t1} vs {t2}", callback_data=f"matchinfo_{m_id}"))
    bot.send_message(call.message.chat.id, "\n".join(text_lines), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("matchinfo_"))
def show_match_info(call):
    match_id = call.data.split("_", 1)[1]
    match = get_match_details(match_id)
    if not match:
        bot.answer_callback_query(call.id, "Не удалось получить данные матча.")
        return

    opponents = match.get("opponents", [])
    t1 = opponents[0]["opponent"]["name"] if len(opponents) > 0 else "-"
    t2 = opponents[1]["opponent"]["name"] if len(opponents) > 1 else "-"
    game = match.get("videogame", {}).get("name", "-")
    start = to_almaty(match.get("scheduled_at") or match.get("begin_at"))
    status = match.get("status", "Неизвестно")

    text = (
        f"Подробности матча\n\n"
        f"Игра: {game}\n"
        f"Команды: {t1} vs {t2}\n"
        f"Начало: {start}\n"
        f"Статус: {status}"
    )

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text)

_sent_notifications = set()
def check_matches():
    while True:
        try:
            for user_id, game_key in user_sub.items():
                try:
                    running = get_running_matches_by_game(game_key)
                except Exception as e:
                    print(f"Ошибка запроса running для {game_key}: {e}")
                    continue

                for m in running:
                    match_id = m.get("id")
                    if not match_id:
                        continue

                    unique_key = (user_id, match_id)
                    if unique_key in _sent_notifications:
                        continue

                    opponents = m.get("opponents", [])
                    t1 = md_escape(opponents[0]["opponent"]["name"]) if len(opponents) > 0 else "-"
                    t2 = md_escape(opponents[1]["opponent"]["name"]) if len(opponents) > 1 else "-"
                    game_name = md_escape(Games.get(game_key, game_key))
                    start_local = md_escape(to_almaty(m.get("begin_at") or m.get("scheduled_at")))

                    stream = find_stream_link(m)

                    text = f"Матч начался\\!\n {t1} vs {t2}\n {game_name}\n {start_local}"
                    if stream:
                        text += f"\n\n▶ [Прямая трансляция]({stream})"

                    try:
                        bot.send_message(user_id, text, parse_mode="MarkdownV2")
                        _sent_notifications.add(unique_key)
                    except Exception as send_err:
                        print(f"Ошибка при отправке уведомления {user_id} {match_id}: {send_err}")

        except Exception as e:
            print("Ошибка фоновой проверки:", e)
        time.sleep(60)

threading.Thread(target=check_matches, daemon=True).start()
bot.polling(none_stop=True)

