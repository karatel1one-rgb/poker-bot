import json
import os
import time
import traceback
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Conflict, Forbidden, NetworkError, TimedOut
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)


# ============================================================
# 🔑 ТОКЕН БОТА
# ============================================================

TOKEN = os.getenv("BOT_TOKEN", "8871794819:AAH8GyB7Z7VJrlVo77ciCZKJTONvNjSdOg0")


# ============================================================
# 📁 ФАЙЛЫ
# ============================================================

PLAYERS_FILE = "players.json"
GAME_FILE = "game.json"
HISTORY_FILE = "history.json"
OPERATORS_FILE = "operators.json"

BLIND_LEVELS = [
    (5, 10),
    (10, 25),
    (25, 50),
    (50, 100),
    (100, 200),
    (200, 400),
    (300, 600),
    (400, 800),
    (500, 1000),
]

POINTS_BY_PLACE = {1: 10, 2: 5, 3: 3}
PRIZE_SHARE = {1: 0.70, 2: 0.30}
PLAYER_FIELDS = ("points", "money", "wins", "games")

JOB_BLIND_UP = "blind_up"
JOB_BLIND_WARN = "blind_warn"

BTN_TIME = "⏱ Осталось времени"
BTN_BLINDS = "🃏 Блайнды"
BTN_REBUY = "🔁 Ребай"
BTN_OUT = "🚪 Выбыл"
BTN_PAUSE = "⏸ Пауза"
BTN_FINISH = "🏁 Закончить игру"
BTN_GAME = "♠️ Игра"
BTN_BOARD = "🏆 Рейтинг"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        [BTN_TIME, BTN_BLINDS],
        [BTN_REBUY, BTN_OUT],
        [BTN_PAUSE, BTN_FINISH],
        [BTN_GAME, BTN_BOARD],
    ],
    resize_keyboard=True,
)

ACTIVE_GAME = ("running", "paused", "awaiting_bank")
LIVE_TABLE = ("running", "paused")


# ============================================================
# 📥 ЗАГРУЗКА / СОХРАНЕНИЕ
# ============================================================

def default_player():
    return {"points": 0, "money": 0, "wins": 0, "games": 0}


def default_players():
    names = ["Bars", "Vadya", "Kostya", "Tokar", "Vova", "Danya", "Chubasya"]
    return {name: default_player() for name in names}


def load_json(path, fallback):
    if not os.path.exists(path):
        return fallback

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        print(f"⚠️ Не удалось прочитать {path}: {error}")
        backup = f"{path}.corrupt"
        try:
            os.replace(path, backup)
            print(f"⚠️ Повреждённый файл сохранён как {backup}")
        except OSError:
            pass
        return fallback


def save_json(path, data):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    temporary = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def normalize_player_row(row):
    if not isinstance(row, dict):
        return default_player(), True

    normalized = dict(row)
    changed = False
    for key in PLAYER_FIELDS:
        try:
            value = int(normalized.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        if normalized.get(key) != value:
            changed = True
        normalized[key] = value
    return normalized, changed


def load_players():
    raw = load_json(PLAYERS_FILE, None)
    if not isinstance(raw, dict) or not raw:
        data = default_players()
        save_json(PLAYERS_FILE, data)
        return data

    changed = False
    loaded = {}
    for name, row in raw.items():
        if not isinstance(name, str) or not name.strip():
            changed = True
            continue
        loaded[name], row_changed = normalize_player_row(row)
        changed = changed or row_changed

    if not loaded:
        loaded = default_players()
        changed = True
    if changed:
        save_json(PLAYERS_FILE, loaded)
    return loaded


def save_players(data):
    save_json(PLAYERS_FILE, data)


def load_game():
    game = load_json(GAME_FILE, None)
    if not isinstance(game, dict):
        return None
    return game


def save_game(game):
    save_json(GAME_FILE, game)


def clear_game():
    if os.path.exists(GAME_FILE):
        os.remove(GAME_FILE)


def load_history():
    history = load_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        return []
    return history


def save_history(history):
    save_json(HISTORY_FILE, history)


players = load_players()


def load_operators():
    data = load_json(OPERATORS_FILE, {})
    if not isinstance(data, dict):
        return {}
    return data


def save_operators(data):
    save_json(OPERATORS_FILE, data)


def get_operator(chat_id):
    entry = load_operators().get(str(chat_id))
    if isinstance(entry, dict) and entry.get("user_id") is not None:
        return entry
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()):
        return {"user_id": int(entry), "name": "", "username": ""}
    return None


def set_operator(chat, user):
    data = load_operators()
    record = {
        "user_id": user.id,
        "name": user.full_name,
        "username": user.username or "",
    }
    data[str(user.id)] = record
    if chat.id != user.id:
        data[str(chat.id)] = record
    save_operators(data)


def is_operator(chat_id, user_id):
    operator = get_operator(chat_id)
    if not operator:
        return False
    try:
        return int(operator["user_id"]) == int(user_id)
    except (TypeError, ValueError):
        return False


def is_start_command(update: Update):
    message = update.effective_message
    if not message or not message.text:
        return False
    command = message.text.split()[0].split("@")[0].lower()
    return command == "/start"


async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or user.is_bot:
        return
    if is_start_command(update):
        return
    if is_operator(chat.id, user.id) or is_operator(user.id, user.id):
        return

    if update.callback_query:
        try:
            await update.callback_query.answer(
                "Бот работает только у того, кто нажал /start.",
                show_alert=True,
            )
        except BadRequest:
            pass
    elif chat.type == "private" and update.effective_message:
        try:
            await update.effective_message.reply_text("Нажми /start, чтобы включить бота.")
        except (BadRequest, Forbidden):
            pass

    raise ApplicationHandlerStop


# ============================================================
# 🧮 ХЕЛПЕРЫ
# ============================================================

def clip_text(text):
    text = "" if text is None else str(text)
    if len(text) <= 4000:
        return text
    return text[:3980] + "\n…"


def resolve_player(name):
    if not name:
        return None
    cleaned = name.strip()
    if cleaned in players:
        return cleaned
    folded = cleaned.casefold()
    for existing in players:
        if existing.casefold() == folded:
            return existing
    return None


def parse_money(text):
    cleaned = (
        str(text)
        .casefold()
        .replace("грн", "")
        .replace("uah", "")
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace(",", "")
    )
    if not cleaned.isdigit():
        return None
    return int(cleaned)


async def send_user(bot, user_id, text, reply_markup=None, parse_mode=None):
    try:
        await bot.send_message(
            chat_id=int(user_id),
            text=clip_text(text),
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except (Forbidden, BadRequest, ValueError):
        return False


async def answer_message(message, text, **kwargs):
    text = clip_text(text)
    try:
        return await message.reply_text(text, do_quote=True, **kwargs)
    except TypeError as error:
        if "do_quote" not in str(error):
            raise
        return await message.reply_text(text, **kwargs)


async def hide_group_ui(update: Update):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or chat.type == "private":
        return

    try:
        hidden = await answer_message(
            message,
            "\u2060",
            reply_markup=ReplyKeyboardRemove(selective=True),
        )
        await hidden.delete()
    except Exception:
        pass

    try:
        await message.delete()
    except Exception:
        pass


async def reply_pm(update: Update, context: ContextTypes.DEFAULT_TYPE, text, reply_markup=None, parse_mode=None):
    user = update.effective_user
    if not user:
        return False

    sent = await send_user(context.bot, user.id, text, reply_markup, parse_mode)
    if sent:
        await hide_group_ui(update)
        return True

    chat = update.effective_chat
    message = update.effective_message
    if chat and message and chat.type != "private":
        try:
            await answer_message(
                message,
                f"{user.mention_html()}, открой личку с ботом и нажми /start.\n"
                "Тогда ответы будут только у тебя, не в группе.",
                parse_mode=ParseMode.HTML,
            )
        except (BadRequest, Forbidden):
            return False
    return False


async def safe_edit(query, text, reply_markup=None):
    text = clip_text(text)
    chat = query.message.chat if query.message else None
    bot = query.get_bot()
    user_id = query.from_user.id if query.from_user else None

    if chat and chat.type != "private" and user_id:
        try:
            await query.message.delete()
        except Exception:
            pass
        if not await send_user(bot, user_id, text, reply_markup):
            try:
                await query.answer("Открой личку с ботом и нажми /start.", show_alert=True)
            except BadRequest:
                pass
        return

    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as error:
        message = str(error).lower()
        if "not modified" in message:
            return
        if "message to edit not found" in message or "there is no text" in message:
            if user_id:
                await send_user(bot, user_id, text, reply_markup)
            return
        raise


async def respond(update, context, text, reply_markup=None, parse_mode=None, query=None, alert=False):
    if query is not None:
        if alert:
            try:
                await query.answer((text or "")[:200], show_alert=True)
            except BadRequest:
                pass
            return False
        try:
            await query.answer()
        except BadRequest:
            pass
        await safe_edit(query, text, reply_markup=reply_markup)
        return True

    if update is not None:
        return await reply_pm(update, context, text, reply_markup, parse_mode)
    return False


async def notify_host(bot, game, text, reply_markup=None, parse_mode=None):
    host_id = game.get("host_id")
    if host_id and await send_user(bot, host_id, text, reply_markup, parse_mode):
        return True

    chat_id = game.get("chat_id")
    if chat_id and str(chat_id) != str(host_id):
        return await send_user(bot, chat_id, text, reply_markup=None, parse_mode=parse_mode)
    return False


def money_text(value):
    try:
        amount = int(value)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,} грн".replace(",", " ")


def format_mmss(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def blind_index(game):
    try:
        level = int(game.get("blind_level", 0))
    except (TypeError, ValueError):
        level = 0
    return min(max(level, 0), len(BLIND_LEVELS) - 1)


def current_blinds(game):
    small, big = BLIND_LEVELS[blind_index(game)]
    return small, big


def remaining_seconds(game):
    if not game or game.get("status") not in LIVE_TABLE:
        return 0

    if game["status"] == "paused":
        try:
            return max(0, int(game.get("paused_remaining", 0)))
        except (TypeError, ValueError):
            return 0

    try:
        interval = int(game.get("interval_min") or 0) * 60
        started = float(game.get("level_started_at") or 0)
    except (TypeError, ValueError):
        return 0
    if interval <= 0 or started <= 0:
        return 0
    return max(0, int(interval - (time.time() - started)))


def catch_up_blinds(game, force_one=False):
    """Поднимает пропущенные уровни по часам. force_one — если таймер уже сработал."""
    if not game or game.get("status") != "running":
        return []

    try:
        interval = int(game.get("interval_min") or 0) * 60
        started = float(game.get("level_started_at") or 0)
    except (TypeError, ValueError):
        return []

    if interval <= 0 or started <= 0:
        game["level_started_at"] = time.time()
        return []

    raised = []
    last_level = len(BLIND_LEVELS) - 1
    for _ in range(len(BLIND_LEVELS)):
        if blind_index(game) >= last_level and int(game.get("blind_level", 0)) >= last_level:
            break
        elapsed = time.time() - float(game.get("level_started_at") or started)
        overdue = elapsed >= interval
        if not overdue and not (force_one and not raised):
            break

        game["blind_level"] = int(game.get("blind_level", 0)) + 1
        next_start = float(game["level_started_at"]) + interval
        if next_start > time.time():
            next_start = time.time()
        game["level_started_at"] = next_start
        raised.append(game["blind_level"])
        if game["blind_level"] >= last_level:
            break
    return raised


def suggested_prize_pool(game):
    try:
        buy_in = int(game.get("buy_in") or 0)
    except (TypeError, ValueError):
        buy_in = 0
    selected = game.get("selected") or []
    _, rebuy_total = rebuy_summary(game)
    return buy_in * (len(selected) + rebuy_total)


def split_prize(prize_pool):
    first_prize = int(round(int(prize_pool) * PRIZE_SHARE[1]))
    second_prize = int(prize_pool) - first_prize
    return first_prize, second_prize


def rebuy_summary(game):
    rebuys = game.get("rebuys") or {}
    lines = []
    total = 0
    for name in game.get("selected") or []:
        try:
            count = int(rebuys.get(name, 0))
        except (TypeError, ValueError):
            count = 0
        total += count
        if count:
            lines.append(f"• {name}: {count}")
    if not lines:
        return "нет", 0
    return "\n".join(lines), total


def player_sort_key(item):
    name, data = item
    return (data["points"], data["wins"], data["money"], name)


def sorted_players():
    return sorted(players.items(), key=player_sort_key, reverse=True)


def cancel_blind_jobs(job_queue):
    if not job_queue:
        return
    for name in (JOB_BLIND_UP, JOB_BLIND_WARN):
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()


def schedule_blind_jobs(job_queue, game):
    cancel_blind_jobs(job_queue)
    if not job_queue or not game or game.get("status") != "running":
        return
    if blind_index(game) >= len(BLIND_LEVELS) - 1:
        return
    try:
        if int(game.get("interval_min") or 0) <= 0:
            return
    except (TypeError, ValueError):
        return

    remaining = remaining_seconds(game)
    when = 1 if remaining <= 0 else remaining
    job_queue.run_once(raise_blinds_job, when=when, name=JOB_BLIND_UP)

    warn_in = when - 60
    if warn_in > 0:
        job_queue.run_once(warn_blinds_job, when=warn_in, name=JOB_BLIND_WARN)


def setup_keyboard(game):
    selected = set(game.get("selected") or [])
    buttons = []
    row = []

    for name in players.keys():
        mark = "✅" if name in selected else "⬜"
        row.append(InlineKeyboardButton(f"{mark} {name}", callback_data=f"sel:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton("➡️ Дальше", callback_data="setup:next"),
            InlineKeyboardButton("❌ Отмена", callback_data="setup:cancel"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


def interval_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("10 мин", callback_data="int:10"),
                InlineKeyboardButton("15 мин", callback_data="int:15"),
            ],
            [
                InlineKeyboardButton("20 мин", callback_data="int:20"),
                InlineKeyboardButton("25 мин", callback_data="int:25"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="setup:cancel")],
        ]
    )


def game_keyboard(game):
    status = game.get("status")
    rows = [
        [InlineKeyboardButton(BTN_TIME, callback_data="t:time")],
        [InlineKeyboardButton("🃏 Текущие блайнды", callback_data="t:blinds")],
    ]

    if status == "running":
        rows.append([InlineKeyboardButton(BTN_PAUSE, callback_data="t:pause")])
    elif status == "paused":
        rows.append([InlineKeyboardButton("▶️ Продолжить", callback_data="t:resume")])

    if status in LIVE_TABLE:
        rows.append(
            [
                InlineKeyboardButton(BTN_REBUY, callback_data="t:rebuy"),
                InlineKeyboardButton(BTN_OUT, callback_data="t:out"),
            ]
        )
        rows.append([InlineKeyboardButton(BTN_FINISH, callback_data="t:finish")])

    if status == "awaiting_bank":
        suggested = suggested_prize_pool(game)
        rows.append(
            [
                InlineKeyboardButton(
                    f"💰 Банк {money_text(suggested)}",
                    callback_data="t:use_calc",
                )
            ]
        )

    return InlineKeyboardMarkup(rows)


def player_action_keyboard(game, action):
    buttons = []
    row = []
    for name in game.get("alive") or []:
        row.append(InlineKeyboardButton(name, callback_data=f"{action}:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t:panel")])
    return InlineKeyboardMarkup(buttons)


def blinds_text(game):
    level = blind_index(game)
    small, big = BLIND_LEVELS[level]
    last = level >= len(BLIND_LEVELS) - 1
    status = "⏸ пауза" if game.get("status") == "paused" else "▶️ идёт"
    text = (
        f"🃏 Уровень {level + 1}/{len(BLIND_LEVELS)}\n"
        f"МБ {small} / ББ {big}\n"
        f"{status}\n"
    )
    if last:
        text += "Это финальный уровень блайндов."
    else:
        text += f"До повышения: {format_mmss(remaining_seconds(game))}"
    return text


def time_text(game):
    status = game.get("status")
    if status == "paused":
        return (
            "⏸ Таймер на паузе.\n"
            f"До повышения блайндов осталось: {format_mmss(remaining_seconds(game))}"
        )
    if status != "running":
        return "Сейчас нет активного таймера блайндов."
    if blind_index(game) >= len(BLIND_LEVELS) - 1:
        return "⏱ Финальный уровень.\nБлайнды больше не повышаются."
    return "⏱ Осталось до повышения блайндов:\n" + format_mmss(remaining_seconds(game))


def game_panel_text(game):
    status = game.get("status")
    alive = game.get("alive") or []
    eliminated = game.get("eliminated") or []
    rebuy_text, rebuy_count = rebuy_summary(game)
    try:
        start_bank = int(game.get("buy_in") or 0) * len(game.get("selected") or [])
    except (TypeError, ValueError):
        start_bank = 0

    status_map = {
        "setup": "настройка",
        "waiting_buyin": "ждём бай-ин",
        "waiting_interval": "выбор таймера",
        "running": "идёт",
        "paused": "пауза",
        "awaiting_bank": "ждём общий банк",
    }
    text = f"♠️ ТЕКУЩАЯ ИГРА\nСтатус: {status_map.get(status, status)}\n"

    if status in ("running", "paused", "awaiting_bank"):
        small, big = current_blinds(game)
        if blind_index(game) >= len(BLIND_LEVELS) - 1:
            until_up = "финальный уровень"
        else:
            until_up = format_mmss(remaining_seconds(game))
        text += (
            f"Таймер: {game.get('interval_min')} мин\n"
            f"Блайнды: МБ {small} / ББ {big}\n"
            f"До повышения: {until_up}\n"
            f"За столом: {', '.join(alive) if alive else '—'}\n"
            f"Выбыли: {len(eliminated)}\n"
            f"Стартовый банк: {money_text(start_bank)}\n"
            f"Ребаи ({rebuy_count}): {rebuy_text}\n"
            f"Расчётный банк: {money_text(suggested_prize_pool(game))}"
        )
    elif status == "setup":
        selected = game.get("selected") or []
        text += "Игроки: " + (", ".join(selected) if selected else "пока никто")
    elif status == "waiting_buyin":
        text += "Жду бай-ин числом. Пример: 500"
    elif status == "waiting_interval":
        text += f"Бай-ин: {money_text(game.get('buy_in') or 0)}\nВыбери интервал кнопками."
    return text


def places_from_game(game):
    mapping = {}
    for item in game.get("eliminated") or []:
        if not isinstance(item, dict) or "place" not in item or "name" not in item:
            continue
        try:
            mapping[int(item["place"])] = item["name"]
        except (TypeError, ValueError):
            continue
    return mapping


def bank_prompt(game):
    suggested = suggested_prize_pool(game)
    rebuy_text, _ = rebuy_summary(game)
    try:
        start_bank = int(game.get("buy_in") or 0) * len(game.get("selected") or [])
    except (TypeError, ValueError):
        start_bank = 0
    places = places_from_game(game)
    return (
        "🏁 ТУРНИР ЗАВЕРШЁН\n\n"
        f"🥇 {places.get(1, '—')}\n"
        f"🥈 {places.get(2, '—')}\n"
        f"🥉 {places.get(3, '—')}\n\n"
        f"Стартовый банк: {money_text(start_bank)}\n"
        f"Ребаи:\n{rebuy_text}\n"
        f"Расчёт: {money_text(suggested)}\n\n"
        "Впиши общий банк числом (грн) или нажми кнопку с расчётом.\n"
        "Банк делится 70% / 30% между 1 и 2 местом."
    )


def eliminate_player(game, name):
    alive = list(game.get("alive") or [])
    if name not in alive:
        return "missing", f"{name} уже не за столом."

    alive.remove(name)
    game["alive"] = alive
    place = len(game.get("selected") or []) - len(game.get("eliminated") or [])
    game.setdefault("eliminated", []).append({"name": name, "place": place})

    if len(game["alive"]) > 1:
        return "ok", (
            f"🚪 {name} выбыл. Место: {place}\n"
            f"За столом: {', '.join(game['alive'])}"
        )

    if len(game["alive"]) == 1:
        winner = game["alive"][0]
        game["eliminated"].append({"name": winner, "place": 1})
        game["alive"] = []

    game["status"] = "awaiting_bank"
    game["awaiting"] = "bank"
    return "bank", bank_prompt(game)


def valid_player_name(name):
    if not name or len(name) > 20:
        return False
    forbidden = set(":/\\\n\t@")
    return not any(char in forbidden or char.isspace() for char in name)


# ============================================================
# JOBS
# ============================================================

async def warn_blinds_job(context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") != "running":
        return
    if blind_index(game) >= len(BLIND_LEVELS) - 1:
        return
    await notify_host(context.bot, game, "⚠️ Через 1 минуту блайнды повысятся.")


async def raise_blinds_job(context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") != "running":
        return

    raised = catch_up_blinds(game, force_one=True)
    last = len(BLIND_LEVELS) - 1

    if not raised and blind_index(game) >= last:
        small, big = current_blinds(game)
        await notify_host(
            context.bot,
            game,
            f"🃏 Финальный уровень. Блайнды остаются МБ {small} / ББ {big}.",
        )
        return

    if not raised:
        schedule_blind_jobs(context.job_queue, game)
        return

    save_game(game)
    small, big = current_blinds(game)
    level_no = blind_index(game) + 1
    if len(raised) == 1:
        text = f"🔺 Блайнды повышены!\nУровень {level_no}: МБ {small} / ББ {big}"
    else:
        text = (
            f"🔺 Блайнды повышены сразу на {len(raised)} ур.\n"
            f"Сейчас уровень {level_no}: МБ {small} / ББ {big}"
        )
    if blind_index(game) >= last:
        text += "\nДальше блайнды не растут."

    await notify_host(
        context.bot,
        game,
        text,
        reply_markup=game_keyboard(game),
    )
    schedule_blind_jobs(context.job_queue, game)


# ============================================================
# КОМАНДЫ
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    set_operator(chat, user)

    await reply_pm(
        update,
        context,
        f"♠️ {user.mention_html()}, бот включён только для тебя.\n\n"
        "Клавиатура и команды работают лишь у того, кто нажал /start.\n"
        "Новая игра: /newgame",
        parse_mode=ParseMode.HTML,
        reply_markup=REPLY_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_pm(
        update,
        context,
        "♠️ КОМАНДЫ POKER BOT\n\n"
        "/start — включить бота и обновить клавиатуру\n"
        "/leaderboard — текущий рейтинг\n"
        "/players — список игроков\n"
        "/stats Bars — статистика игрока\n"
        "/top — топ игроков\n"
        "/rules — очки, призы и блайнды\n"
        "/history — история игр\n"
        "/game — текущая игра и кнопки\n"
        "/time — сколько осталось до блайндов\n"
        "/blinds — текущие блайнды\n\n"
        "🔧 ИГРА:\n"
        "/newgame — собрать стол\n"
        "/rebuy Bars — ребай игрока\n"
        "/out Bars — игрок выбыл\n"
        "/pause /resume — пауза таймера\n"
        "/cancelgame — отменить игру без статистики\n"
        "/addplayer Name — добавить игрока\n"
        "/removeplayer Name — убрать игрока без статистики\n\n"
        "Кнопки снизу: время, блайнды, ребай, выбытие, пауза и финиш.\n"
        "Имя игрока можно писать в любом регистре.\n\n"
        "🔧 АДМИНИСТРАТОР:\n"
        "/edit Bars 85 12500 7 12\n\n"
        "Формат /edit:\n"
        "Игрок → Очки → Выиграно грн → Победы → Игры",
    )


async def players_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "♠️ СПИСОК ИГРОКОВ\n\n"
    for index, name in enumerate(players.keys(), 1):
        text += f"{index}. {name}\n"
    await reply_pm(update, context, text)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ranking = sorted_players()
    text = "♠️ POKER LEAGUE\n🏆 ОБЩИЙ РЕЙТИНГ\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for place, (name, data) in enumerate(ranking, 1):
        icon = medals[place - 1] if place <= 3 else f"{place}."
        text += (
            f"{icon} {name}\n"
            f"⭐ {data['points']} очков | "
            f"🏆 {data['wins']} побед\n"
            f"💰 {money_text(data['money'])} | "
            f"🎮 {data['games']} игр\n\n"
        )

    await reply_pm(update, context, text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context, "Используй:\n/stats Bars")
        return

    name = resolve_player(context.args[0])
    if not name:
        await reply_pm(update, context, "❌ Игрок не найден.")
        return

    data = players[name]
    ranking = sorted_players()
    place = next(index for index, (player_name, _) in enumerate(ranking, 1) if player_name == name)
    await reply_pm(
        update,
        context,
        f"♠️ СТАТИСТИКА {name.upper()}\n\n"
        f"🏅 Место: {place}\n"
        f"⭐ Очки: {data['points']}\n"
        f"🎮 Игр: {data['games']}\n"
        f"🏆 Побед: {data['wins']}\n"
        f"💰 Выиграно: {money_text(data['money'])}",
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ranking = sorted_players()[:3]
    text = "🏆 TOP PLAYERS\n\n"
    medals = ["🥇", "🥈", "🥉"]
    if not ranking:
        text += "Пока нет игроков."
    for index, (name, data) in enumerate(ranking):
        text += f"{medals[index]} {name} — {data['points']} очков\n"
    await reply_pm(update, context, text)


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blinds = "\n".join(
        f"{index}. МБ {small} / ББ {big}"
        for index, (small, big) in enumerate(BLIND_LEVELS, 1)
    )
    await reply_pm(
        update,
        context,
        "♠️ ПРАВИЛА\n\n"
        "Очки:\n"
        "🥇 1 место — 10 очков\n"
        "🥈 2 место — 5 очков\n"
        "🥉 3 место — 3 очка\n\n"
        "Призы:\n"
        "Общий банк = стартовый бай-ин всех игроков + ребаи.\n"
        "Сумма вводится по завершении турнира.\n"
        "🥇 70% банка\n"
        "🥈 30% банка\n"
        "3 место получает только очки.\n\n"
        "Таймер блайндов: 10 / 15 / 20 / 25 минут.\n"
        "Ребай доступен, пока игрок за столом.\n"
        "Пауза останавливает таймер.\n\n"
        f"{blinds}",
    )


async def edit_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 5:
        await reply_pm(
            update,
            context,
            "❌ Неверный формат.\n\n"
            "Используй:\n"
            "/edit Bars 85 12500 7 12\n\n"
            "Где:\n"
            "Bars — игрок\n"
            "85 — очки\n"
            "12500 — выиграно грн\n"
            "7 — победы\n"
            "12 — игры",
        )
        return

    name = resolve_player(context.args[0])
    if not name:
        await reply_pm(update, context, f"❌ Игрок {context.args[0]} не найден.")
        return

    try:
        points = int(context.args[1])
        money = int(context.args[2])
        wins = int(context.args[3])
        games_count = int(context.args[4])
    except ValueError:
        await reply_pm(update, context, "❌ Очки, деньги, победы и игры должны быть целыми числами.")
        return

    if min(points, money, wins, games_count) < 0:
        await reply_pm(update, context, "❌ Числа не могут быть отрицательными.")
        return
    if wins > games_count:
        await reply_pm(update, context, "❌ Побед не может быть больше, чем игр.")
        return

    players[name]["points"] = points
    players[name]["money"] = money
    players[name]["wins"] = wins
    players[name]["games"] = games_count
    save_players(players)

    await reply_pm(
        update,
        context,
        f"✅ Данные игрока {name} обновлены!\n\n"
        f"⭐ Очки: {points}\n"
        f"💰 Выиграно: {money_text(money)}\n"
        f"🏆 Победы: {wins}\n"
        f"🎮 Игр: {games_count}",
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = [record for record in load_history() if isinstance(record, dict)]
    if not records:
        await reply_pm(update, context, "📜 История игр пока пустая.")
        return

    text = "📜 ИСТОРИЯ ИГР\n\n"
    for record in records[-10:][::-1]:
        places = record.get("places") or {}
        if not isinstance(places, dict):
            places = {}
        text += (
            f"🗓 {record.get('date', '—')}\n"
            f"🥇 {places.get('1', '—')} | 🥈 {places.get('2', '—')} | 🥉 {places.get('3', '—')}\n"
            f"💰 Банк: {money_text(record.get('prize_pool', 0))}\n\n"
        )
    await reply_pm(update, context, text)


async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game:
        await reply_pm(update, context, "Сейчас нет активной игры.\nНачни новую: /newgame")
        return
    await reply_pm(update, context, game_panel_text(game), reply_markup=game_keyboard(game))


async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") not in LIVE_TABLE:
        await reply_pm(update, context, "Сейчас нет активного таймера.")
        return
    await reply_pm(update, context, time_text(game), reply_markup=game_keyboard(game))


async def blinds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") not in LIVE_TABLE:
        await reply_pm(update, context, "Сейчас нет активной игры.")
        return
    await reply_pm(update, context, blinds_text(game), reply_markup=game_keyboard(game))


async def add_player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context, "Используй:\n/addplayer Name")
        return

    name = context.args[0].strip()
    if not valid_player_name(name):
        await reply_pm(
            update,
            context,
            "❌ Имя: одно слово, до 20 символов, без пробелов и знаков : / \\ @",
        )
        return
    if resolve_player(name):
        await reply_pm(update, context, f"❌ Игрок {resolve_player(name)} уже есть.")
        return

    players[name] = default_player()
    save_players(players)
    game = load_game()
    if game and game.get("status") == "setup":
        extra = "\nНабор уже открыт — отправь /newgame, чтобы увидеть его в списке."
    elif game:
        extra = "\nВ текущий турнир он не попадёт, только в следующий."
    else:
        extra = ""
    await reply_pm(update, context, f"✅ {name} добавлен.{extra}")


async def remove_player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context, "Используй:\n/removeplayer Name")
        return

    name = resolve_player(context.args[0])
    if not name:
        await reply_pm(update, context, "❌ Игрок не найден.")
        return

    data = players[name]
    if any(data[key] for key in PLAYER_FIELDS):
        await reply_pm(
            update,
            context,
            f"❌ У {name} уже есть статистика.\n"
            "Сначала обнули её через /edit, если игрока правда нужно убрать.",
        )
        return

    game = load_game()
    if game and name in (game.get("selected") or []) and game.get("status") != "setup":
        await reply_pm(update, context, "❌ Этот игрок в текущей игре. Сначала заверши или отмени её.")
        return
    if game and game.get("status") == "setup" and name in (game.get("selected") or []):
        game["selected"].remove(name)
        save_game(game)

    del players[name]
    save_players(players)
    await reply_pm(update, context, f"✅ {name} убран из списка.")


# ============================================================
# НОВАЯ ИГРА
# ============================================================

def fresh_game(update: Update):
    user = update.effective_user
    chat = update.effective_chat
    return {
        "status": "setup",
        "selected": [],
        "buy_in": 0,
        "interval_min": 0,
        "blind_level": 0,
        "level_started_at": 0,
        "paused_remaining": 0,
        "chat_id": chat.id if chat else None,
        "host_id": user.id if user else None,
        "alive": [],
        "eliminated": [],
        "rebuys": {},
        "awaiting": None,
    }


async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if game and game.get("status") in ACTIVE_GAME:
        await reply_pm(update, context, "Уже есть активная игра. Заверши или отмени её: /cancelgame")
        return

    game = fresh_game(update)
    save_game(game)
    await reply_pm(
        update,
        context,
        "♠️ НОВАЯ ИГРА\nОтметь, кто играет:",
        reply_markup=setup_keyboard(game),
    )


async def cancelgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not load_game():
        await reply_pm(update, context, "Активной игры нет.")
        return
    cancel_blind_jobs(context.job_queue)
    clear_game()
    await reply_pm(update, context, "❌ Игра отменена. Статистика не начислена.")


async def pause_timer(context, update=None, query=None):
    game = load_game()
    if not game or game.get("status") != "running":
        await respond(
            update,
            context,
            "Пауза доступна только во время игры.",
            query=query,
            alert=bool(query),
        )
        return

    game["paused_remaining"] = remaining_seconds(game)
    game["status"] = "paused"
    save_game(game)
    cancel_blind_jobs(context.job_queue)
    text = f"⏸ Таймер на паузе.\nОсталось: {format_mmss(game['paused_remaining'])}"
    await respond(update, context, text, reply_markup=game_keyboard(game), query=query)


async def resume_timer(context, update=None, query=None):
    game = load_game()
    if not game or game.get("status") != "paused":
        await respond(
            update,
            context,
            "Продолжить можно только с паузы.",
            query=query,
            alert=bool(query),
        )
        return

    try:
        interval = int(game.get("interval_min") or 10) * 60
        remaining = int(game.get("paused_remaining", 0))
    except (TypeError, ValueError):
        remaining = 1
        interval = 600
    if interval <= 0:
        interval = 600
    remaining = min(max(1, remaining), interval)

    game["status"] = "running"
    game["level_started_at"] = time.time() - (interval - remaining)
    game["paused_remaining"] = 0
    save_game(game)
    schedule_blind_jobs(context.job_queue, game)
    text = f"▶️ Таймер продолжен.\nДо повышения: {format_mmss(remaining_seconds(game))}"
    await respond(update, context, text, reply_markup=game_keyboard(game), query=query)


async def toggle_pause(update, context):
    game = load_game()
    if game and game.get("status") == "paused":
        await resume_timer(context, update=update)
        return
    await pause_timer(context, update=update)


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await pause_timer(context, update=update)


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await resume_timer(context, update=update)


async def apply_rebuy(name, context, update=None, query=None):
    game = load_game()
    if not game or game.get("status") not in LIVE_TABLE:
        await respond(
            update,
            context,
            "Ребай доступен только во время игры.",
            query=query,
            alert=bool(query),
        )
        return
    if name not in (game.get("alive") or []):
        await respond(update, context, f"{name} сейчас не за столом.", query=query, alert=bool(query))
        return

    game.setdefault("rebuys", {})
    try:
        current = int(game["rebuys"].get(name, 0))
    except (TypeError, ValueError):
        current = 0
    game["rebuys"][name] = current + 1
    save_game(game)

    _, total = rebuy_summary(game)
    text = (
        f"🔁 Ребай: {name} (всего у игрока {game['rebuys'][name]})\n"
        f"Ребаев за стол: {total}\n"
        f"Расчётный банк: {money_text(suggested_prize_pool(game))}"
    )
    await respond(update, context, text, reply_markup=game_keyboard(game), query=query)


async def apply_out(name, context, update=None, query=None):
    game = load_game()
    if not game or game.get("status") not in LIVE_TABLE:
        await respond(
            update,
            context,
            "Отметить выбывание можно только во время игры.",
            query=query,
            alert=bool(query),
        )
        return

    kind, text = eliminate_player(game, name)
    if kind == "missing":
        await respond(update, context, text, query=query, alert=bool(query))
        return

    save_game(game)
    if kind == "bank":
        cancel_blind_jobs(context.job_queue)
    await respond(update, context, text, reply_markup=game_keyboard(game), query=query)


async def rebuy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context, "Используй:\n/rebuy Bars")
        return
    name = resolve_player(context.args[0])
    if not name:
        await reply_pm(update, context, "❌ Игрок не найден.")
        return
    await apply_rebuy(name, context, update=update)


async def out_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context, "Используй:\n/out Bars")
        return
    name = resolve_player(context.args[0])
    if not name:
        await reply_pm(update, context, "❌ Игрок не найден.")
        return
    await apply_out(name, context, update=update)


async def request_finish(update, context, query=None):
    game = load_game()
    if not game or game.get("status") not in ACTIVE_GAME:
        await respond(
            update,
            context,
            "Сейчас нет игры, которую можно закончить.",
            query=query,
            alert=bool(query),
        )
        return

    if game.get("status") != "awaiting_bank":
        alive = list(game.get("alive") or [])
        if len(alive) > 1:
            await respond(
                update,
                context,
                "Отметь выбывших, пока не останется один победитель.",
                query=query,
                alert=bool(query),
            )
            return
        if len(alive) == 1:
            game.setdefault("eliminated", []).append({"name": alive[0], "place": 1})
            game["alive"] = []
        places = places_from_game(game)
        if 1 not in places or 2 not in places:
            await respond(
                update,
                context,
                "Нужны 1 и 2 место. Отметь выбывших через «🚪 Выбыл».",
                query=query,
                alert=bool(query),
            )
            return
        game["status"] = "awaiting_bank"
        game["awaiting"] = "bank"
        save_game(game)
        cancel_blind_jobs(context.job_queue)

    await respond(
        update,
        context,
        bank_prompt(game),
        reply_markup=game_keyboard(game),
        query=query,
    )


# ============================================================
# ЛОГИКА ИГРЫ
# ============================================================

async def start_tournament(query, context, game):
    now = time.time()
    game["status"] = "running"
    game["blind_level"] = 0
    game["level_started_at"] = now
    game["paused_remaining"] = 0
    game["alive"] = list(game.get("selected") or [])
    game["eliminated"] = []
    game["rebuys"] = {name: 0 for name in game["alive"]}
    if query.from_user:
        game["host_id"] = query.from_user.id
    if query.message and not game.get("chat_id"):
        game["chat_id"] = query.message.chat_id
    save_game(game)
    schedule_blind_jobs(context.job_queue, game)

    small, big = current_blinds(game)
    await respond(
        None,
        context,
        "🎮 ИГРА СТАРТОВАЛА\n\n"
        f"Игроки: {', '.join(game['alive'])}\n"
        f"Бай-ин: {money_text(game['buy_in'])}\n"
        f"Стартовый банк: {money_text(suggested_prize_pool(game))}\n"
        f"Таймер: {game['interval_min']} мин\n"
        f"Блайнды: МБ {small} / ББ {big}\n\n"
        "Ребай каждого игрока учитывается отдельно.\n"
        "Общий банк впишешь в конце — он делится 70% / 30%.",
        reply_markup=game_keyboard(game),
        query=query,
    )
    await notify_host(
        context.bot,
        game,
        "Стол запущен. Кнопки снизу: время, блайнды, ребай, выбытие, пауза и финиш.",
        reply_markup=REPLY_KEYBOARD,
    )


async def finish_with_bank(update, context, prize_pool, query=None):
    game = load_game()

    async def say(text):
        await respond(update, context, text, query=query)

    if not game:
        await say("Активной игры нет.")
        return
    if game.get("status") != "awaiting_bank":
        await say("Сначала определи победителя: за столом должен остаться один игрок.")
        return

    try:
        prize_pool = int(prize_pool)
    except (TypeError, ValueError):
        await say("Банк нужно вписать числом.")
        return
    if prize_pool < 0:
        await say("Банк не может быть отрицательным.")
        return

    places = places_from_game(game)
    first = places.get(1)
    second = places.get(2)
    third = places.get(3)
    if not first or not second:
        await say("Нужны минимум 1 и 2 место, чтобы закрыть турнир.")
        return

    updated = {name: dict(row) for name, row in players.items()}

    def bucket(name):
        row = updated.get(name)
        if not isinstance(row, dict):
            row = default_player()
            updated[name] = row
        return row

    for name in game.get("selected") or []:
        bucket(name)["games"] += 1

    first_prize, second_prize = split_prize(prize_pool)
    bucket(first)["points"] += POINTS_BY_PLACE[1]
    bucket(first)["wins"] += 1
    bucket(first)["money"] += first_prize
    bucket(second)["points"] += POINTS_BY_PLACE[2]
    bucket(second)["money"] += second_prize
    if third:
        bucket(third)["points"] += POINTS_BY_PLACE[3]

    save_players(updated)
    players.clear()
    players.update(updated)

    record = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "players": list(game.get("selected") or []),
        "places": {str(place): name for place, name in places.items()},
        "prize_pool": prize_pool,
        "prizes": {"1": first_prize, "2": second_prize},
        "buy_in": game.get("buy_in", 0),
        "rebuys": game.get("rebuys") or {},
        "interval_min": game.get("interval_min", 0),
    }
    try:
        history_records = load_history()
        history_records.append(record)
        save_history(history_records)
    except OSError as error:
        print(f"⚠️ Не удалось записать историю: {error}")

    cancel_blind_jobs(context.job_queue)
    clear_game()

    ranking = sorted_players()[:3]
    top_text = "\n".join(
        f"{icon} {name} — {data['points']} очков"
        for icon, (name, data) in zip(["🥇", "🥈", "🥉"], ranking)
    )
    lines = [
        "✅ РЕЗУЛЬТАТЫ ЗАПИСАНЫ",
        "",
        f"🥇 {first}: +10 очков, +{money_text(first_prize)}",
        f"🥈 {second}: +5 очков, +{money_text(second_prize)}",
    ]
    if third:
        lines.append(f"🥉 {third}: +3 очка")
    lines.extend(["", f"Банк: {money_text(prize_pool)}", "", "🏆 Обновлённый топ:", top_text])
    await say("\n".join(lines))


# ============================================================
# CALLBACKS + ТЕКСТ
# ============================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    game = load_game()

    if data.startswith("sel:"):
        if not game or game.get("status") != "setup":
            await respond(update, context, "Сначала начни /newgame", query=query)
            return
        name = data.split(":", 1)[1]
        if name not in players:
            await respond(update, context, "Этого игрока уже нет в списке.", query=query, alert=True)
            return
        selected = list(game.get("selected") or [])
        if name in selected:
            selected.remove(name)
        else:
            selected.append(name)
        game["selected"] = selected
        save_game(game)
        await respond(
            update,
            context,
            "♠️ НОВАЯ ИГРА\nОтметь, кто играет:",
            reply_markup=setup_keyboard(game),
            query=query,
        )
        return

    if data == "setup:cancel":
        cancel_blind_jobs(context.job_queue)
        clear_game()
        await respond(update, context, "❌ Создание игры отменено.", query=query)
        return

    if data == "setup:next":
        if not game or game.get("status") != "setup":
            await respond(update, context, "Сначала начни /newgame", query=query)
            return
        if len(game.get("selected") or []) < 2:
            await respond(update, context, "Нужно минимум 2 игрока.", query=query, alert=True)
            return
        game["status"] = "waiting_buyin"
        game["awaiting"] = "buyin"
        save_game(game)
        await respond(
            update,
            context,
            "💵 Впиши стартовый бай-ин одного игрока (грн).\n"
            "Пример: 500\n\n"
            f"Игроки: {', '.join(game['selected'])}",
            query=query,
        )
        return

    if data.startswith("int:"):
        if not game or game.get("status") != "waiting_interval":
            await respond(update, context, "Сначала выбери бай-ин.", query=query)
            return
        try:
            minutes = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            minutes = 0
        if minutes not in (10, 15, 20, 25):
            await respond(update, context, "Такого интервала нет.", query=query, alert=True)
            return
        game["interval_min"] = minutes
        save_game(game)
        await start_tournament(query, context, game)
        return

    if not game:
        if data == "t:time":
            try:
                await query.answer("Сейчас нет активного таймера.", show_alert=True)
            except BadRequest:
                pass
        else:
            try:
                await query.answer()
            except BadRequest:
                pass
        await safe_edit(query, "Активной игры нет.")
        return

    if data == "t:time":
        if game.get("status") not in LIVE_TABLE:
            await respond(update, context, "Сейчас нет активного таймера.", query=query, alert=True)
            return
        try:
            await query.answer(time_text(game)[:200], show_alert=True)
        except BadRequest:
            pass
        return

    if data == "t:blinds":
        await respond(update, context, blinds_text(game), reply_markup=game_keyboard(game), query=query)
        return

    if data == "t:panel":
        await respond(update, context, game_panel_text(game), reply_markup=game_keyboard(game), query=query)
        return

    if data == "t:pause":
        await pause_timer(context, update=update, query=query)
        return

    if data == "t:resume":
        await resume_timer(context, update=update, query=query)
        return

    if data == "t:rebuy":
        if not (game.get("alive") or []):
            await respond(update, context, "За столом никого нет.", query=query, alert=True)
            return
        await respond(
            update,
            context,
            "🔁 Кому ребай?",
            reply_markup=player_action_keyboard(game, "rebuy"),
            query=query,
        )
        return

    if data == "t:out":
        if not (game.get("alive") or []):
            await respond(update, context, "За столом никого нет.", query=query, alert=True)
            return
        await respond(
            update,
            context,
            "🚪 Кто выбыл?",
            reply_markup=player_action_keyboard(game, "out"),
            query=query,
        )
        return

    if data.startswith("rebuy:"):
        await apply_rebuy(data.split(":", 1)[1], context, update=update, query=query)
        return

    if data.startswith("out:"):
        await apply_out(data.split(":", 1)[1], context, update=update, query=query)
        return

    if data == "t:finish":
        await request_finish(update, context, query=query)
        return

    if data == "t:use_calc":
        await finish_with_bank(update, context, suggested_prize_pool(game), query=query)
        return

    try:
        await query.answer()
    except BadRequest:
        pass


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    raw = message.text.strip()
    if raw == BTN_TIME:
        await time_command(update, context)
        return
    if raw == BTN_BLINDS:
        await blinds_command(update, context)
        return
    if raw in (BTN_GAME, "/game"):
        await game_command(update, context)
        return
    if raw in (BTN_BOARD, "/leaderboard"):
        await leaderboard(update, context)
        return
    if raw in (BTN_PAUSE, "▶️ Продолжить"):
        await toggle_pause(update, context)
        return
    if raw == BTN_FINISH:
        await request_finish(update, context)
        return

    game = load_game()
    if raw == BTN_REBUY:
        if not game or game.get("status") not in LIVE_TABLE:
            await reply_pm(update, context, "Ребай доступен только во время игры.")
            return
        await reply_pm(
            update,
            context,
            "🔁 Кому ребай?",
            reply_markup=player_action_keyboard(game, "rebuy"),
        )
        return
    if raw == BTN_OUT:
        if not game or game.get("status") not in LIVE_TABLE:
            await reply_pm(update, context, "Отметить выбывание можно только во время игры.")
            return
        await reply_pm(
            update,
            context,
            "🚪 Кто выбыл?",
            reply_markup=player_action_keyboard(game, "out"),
        )
        return

    if not game:
        return

    awaiting = game.get("awaiting")
    if awaiting == "buyin" and game.get("status") == "waiting_buyin":
        amount = parse_money(raw)
        if amount is None:
            await reply_pm(update, context, "Нужно число. Пример: 500")
            return
        game["buy_in"] = amount
        game["status"] = "waiting_interval"
        game["awaiting"] = None
        save_game(game)
        start_bank = amount * len(game.get("selected") or [])
        await reply_pm(
            update,
            context,
            f"💵 Бай-ин: {money_text(amount)}\n"
            f"Стартовый банк: {money_text(start_bank)}\n\n"
            "Выбери интервал повышения блайндов:",
            reply_markup=interval_keyboard(),
        )
        return

    if awaiting == "bank" and game.get("status") == "awaiting_bank":
        amount = parse_money(raw)
        if amount is None:
            await reply_pm(update, context, "Впиши общий банк числом. Пример: 7000")
            return
        await finish_with_bank(update, context, amount)


# ============================================================
# ЗАПУСК
# ============================================================

async def on_startup(app: Application):
    game = load_game()
    if not game or game.get("status") != "running":
        return

    raised = catch_up_blinds(game, force_one=False)
    if raised:
        save_game(game)
        small, big = current_blinds(game)
        await notify_host(
            app.bot,
            game,
            "🔺 Пока бот был выключен, блайнды изменились.\n"
            f"Сейчас уровень {blind_index(game) + 1}: МБ {small} / ББ {big}",
            reply_markup=game_keyboard(game),
        )
    schedule_blind_jobs(app.job_queue, game)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, BadRequest) and "not modified" in str(error).lower():
        return
    if isinstance(error, Conflict):
        print("⚠️ Бот уже запущен в другом месте. Останови второй экземпляр.")
        return
    if isinstance(error, (NetworkError, TimedOut)):
        print(f"⚠️ Сеть: {error}")
        return
    print(f"⚠️ Ошибка бота: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)


def main():
    if not TOKEN or TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_БОТА":
        print("❌ ОШИБКА: не указан TOKEN бота.")
        return

    try:
        app = (
            Application.builder()
            .token(TOKEN)
            .post_init(on_startup)
            .build()
        )
    except Exception as error:
        print("❌ ОШИБКА ПРИ СОЗДАНИИ БОТА:")
        print(error)
        return

    if app.job_queue is None:
        print("⚠️ JobQueue недоступен. Установи: pip install \"python-telegram-bot[job-queue]\"")

    app.add_handler(TypeHandler(Update, access_guard), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("players", players_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("edit", edit_player))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("game", game_command))
    app.add_handler(CommandHandler("time", time_command))
    app.add_handler(CommandHandler("blinds", blinds_command))
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("cancelgame", cancelgame))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("rebuy", rebuy_command))
    app.add_handler(CommandHandler("out", out_command))
    app.add_handler(CommandHandler("addplayer", add_player_command))
    app.add_handler(CommandHandler("removeplayer", remove_player_command))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("♠️ Покерный бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
