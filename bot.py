import json
import os
import time
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
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

JOB_BLIND_UP = "blind_up"
JOB_BLIND_WARN = "blind_warn"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["⏱ Осталось времени", "🃏 Блайнды"],
        ["🔁 Ребай", "🚪 Выбыл"],
        ["🏁 Закончить игру"],
        ["/game", "/leaderboard"],
    ],
    resize_keyboard=True,
)


# ============================================================
# 📥 ЗАГРУЗКА / СОХРАНЕНИЕ
# ============================================================

def default_players():
    names = ["Bars", "Vadya", "Kostya", "Tokar", "Vova", "Danya", "Chubasya"]
    return {
        name: {"points": 0, "money": 0, "wins": 0, "games": 0}
        for name in names
    }


def load_json(path, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            print(f"⚠️ Не удалось прочитать {path}.")

    return fallback


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def load_players():
    players = load_json(PLAYERS_FILE, None)
    if not players:
        players = default_players()
        save_json(PLAYERS_FILE, players)
    return players


def save_players(players):
    save_json(PLAYERS_FILE, players)


def load_game():
    return load_json(GAME_FILE, None)


def save_game(game):
    save_json(GAME_FILE, game)


def clear_game():
    if os.path.exists(GAME_FILE):
        os.remove(GAME_FILE)


def load_history():
    return load_json(HISTORY_FILE, [])


def save_history(history):
    save_json(HISTORY_FILE, history)


players = load_players()


def load_operators():
    return load_json(OPERATORS_FILE, {})


def save_operators(data):
    save_json(OPERATORS_FILE, data)


def get_operator(chat_id):
    entry = load_operators().get(str(chat_id))
    if isinstance(entry, dict):
        return entry
    if entry:
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
    return bool(operator) and int(operator["user_id"]) == int(user_id)


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
        await update.callback_query.answer(
            "Бот работает только у того, кто нажал /start.",
            show_alert=True,
        )

    raise ApplicationHandlerStop


# ============================================================
# 🧮 ХЕЛПЕРЫ
# ============================================================

async def send_user(context, user_id, text, reply_markup=None, parse_mode=None):
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except Forbidden:
        return False
    except BadRequest:
        return False


async def hide_group_ui(update: Update):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or chat.type == "private":
        return

    try:
        hidden = await message.reply_text(
            "\u2060",
            reply_markup=ReplyKeyboardRemove(selective=True),
            do_quote=True,
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
    sent = await send_user(context, user.id, text, reply_markup, parse_mode)
    await hide_group_ui(update)
    if sent:
        return True

    if update.effective_chat and update.effective_chat.type != "private":
        await update.effective_message.reply_text(
            f"{user.mention_html()}, открой личку с ботом и нажми /start.\n"
            "Тогда ответы будут только у тебя, не в группе.",
            parse_mode=ParseMode.HTML,
            do_quote=True,
        )
    return False


async def safe_edit(query, text, reply_markup=None):
    chat = query.message.chat if query.message else None
    bot = query.get_bot()
    user_id = query.from_user.id if query.from_user else None

    if chat and chat.type != "private" and user_id:
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
            )
        except (Forbidden, BadRequest):
            await query.answer(
                "Открой личку с ботом и нажми /start.",
                show_alert=True,
            )
        return

    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as error:
        message = str(error).lower()
        if "not modified" in message:
            return
        if "message to edit not found" in message or "there is no text" in message:
            if user_id:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=reply_markup,
                    )
                except (Forbidden, BadRequest):
                    return
            return
        raise


def money_text(value):
    return f"{int(value):,} грн".replace(",", " ")


def format_mmss(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def current_blinds(game):
    level = min(game.get("blind_level", 0), len(BLIND_LEVELS) - 1)
    return BLIND_LEVELS[level]


def remaining_seconds(game):
    if not game or game.get("status") not in ("running", "paused"):
        return 0

    if game["status"] == "paused":
        return max(0, int(game.get("paused_remaining", 0)))

    elapsed = time.time() - game.get("level_started_at", time.time())
    total = game.get("interval_min", 10) * 60
    return max(0, int(total - elapsed))


def suggested_prize_pool(game):
    buy_in = int(game.get("buy_in", 0))
    selected = game.get("selected", [])
    rebuys = game.get("rebuys", {})
    rebuy_total = sum(int(count) for count in rebuys.values())
    return buy_in * (len(selected) + rebuy_total)


def rebuy_summary(game):
    rebuys = game.get("rebuys", {})
    lines = []
    total = 0
    for name in game.get("selected", []):
        count = int(rebuys.get(name, 0))
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
    if not job_queue or game.get("status") != "running":
        return

    remaining = remaining_seconds(game)
    if remaining <= 0:
        job_queue.run_once(raise_blinds_job, when=1, name=JOB_BLIND_UP)
        return

    job_queue.run_once(raise_blinds_job, when=remaining, name=JOB_BLIND_UP)

    warn_in = remaining - 60
    if warn_in > 0:
        job_queue.run_once(warn_blinds_job, when=warn_in, name=JOB_BLIND_WARN)


def setup_keyboard(game):
    selected = set(game.get("selected", []))
    buttons = []
    row = []

    for name in players.keys():
        mark = "✅" if name in selected else "⬜"
        row.append(
            InlineKeyboardButton(
                f"{mark} {name}",
                callback_data=f"sel:{name}",
            )
        )
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
        [InlineKeyboardButton("⏱ Осталось времени", callback_data="t:time")],
        [InlineKeyboardButton("🃏 Текущие блайнды", callback_data="t:blinds")],
    ]

    if status == "running":
        rows.append([InlineKeyboardButton("⏸ Пауза", callback_data="t:pause")])
    elif status == "paused":
        rows.append([InlineKeyboardButton("▶️ Продолжить", callback_data="t:resume")])

    if status in ("running", "paused"):
        rows.append(
            [
                InlineKeyboardButton("🔁 Ребай", callback_data="t:rebuy"),
                InlineKeyboardButton("🚪 Выбыл", callback_data="t:out"),
            ]
        )
        rows.append(
            [InlineKeyboardButton("🏁 Закончить игру", callback_data="t:finish")]
        )

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
    alive = game.get("alive", [])
    buttons = []
    row = []

    for name in alive:
        row.append(
            InlineKeyboardButton(name, callback_data=f"{action}:{name}")
        )
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [InlineKeyboardButton("⬅️ Назад", callback_data="t:panel")]
    )
    return InlineKeyboardMarkup(buttons)


def blinds_text(game):
    level = min(game.get("blind_level", 0), len(BLIND_LEVELS) - 1)
    small, big = BLIND_LEVELS[level]
    last = level >= len(BLIND_LEVELS) - 1
    left = format_mmss(remaining_seconds(game))
    status = "⏸ пауза" if game.get("status") == "paused" else "▶️ идёт"

    text = (
        f"🃏 Уровень {level + 1}/{len(BLIND_LEVELS)}\n"
        f"МБ {small} / ББ {big}\n"
        f"{status}\n"
    )

    if last:
        text += "Это финальный уровень блайндов."
    else:
        text += f"До повышения: {left}"

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

    level = min(game.get("blind_level", 0), len(BLIND_LEVELS) - 1)
    if level >= len(BLIND_LEVELS) - 1:
        return (
            "⏱ Финальный уровень.\n"
            "Блайнды больше не повышаются."
        )

    return (
        "⏱ Осталось до повышения блайндов:\n"
        f"{format_mmss(remaining_seconds(game))}"
    )


def game_panel_text(game):
    status = game.get("status")
    small, big = current_blinds(game) if status in ("running", "paused", "awaiting_bank") else (0, 0)
    alive = game.get("alive", [])
    eliminated = game.get("eliminated", [])
    rebuy_text, rebuy_count = rebuy_summary(game)
    start_bank = int(game.get("buy_in", 0)) * len(game.get("selected", []))

    status_map = {
        "setup": "настройка",
        "waiting_buyin": "ждём бай-ин",
        "waiting_interval": "выбор таймера",
        "running": "идёт",
        "paused": "пауза",
        "awaiting_bank": "ждём общий банк",
    }

    text = (
        "♠️ ТЕКУЩАЯ ИГРА\n"
        f"Статус: {status_map.get(status, status)}\n"
    )

    if status in ("running", "paused", "awaiting_bank"):
        text += (
            f"Таймер: {game.get('interval_min')} мин\n"
            f"Блайнды: МБ {small} / ББ {big}\n"
            f"До повышения: {format_mmss(remaining_seconds(game))}\n"
            f"За столом: {', '.join(alive) if alive else '—'}\n"
            f"Выбыли: {len(eliminated)}\n"
            f"Стартовый банк: {money_text(start_bank)}\n"
            f"Ребаи ({rebuy_count}): {rebuy_text}\n"
            f"Расчётный банк: {money_text(suggested_prize_pool(game))}"
        )

    return text


# ============================================================
# JOBS
# ============================================================

async def warn_blinds_job(context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") != "running":
        return

    if game.get("blind_level", 0) >= len(BLIND_LEVELS) - 1:
        return

    chat_id = game.get("chat_id")
    if not chat_id:
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text="⚠️ Через 1 минуту блайнды повысятся.",
    )


async def raise_blinds_job(context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") != "running":
        return

    chat_id = game.get("chat_id")
    level = game.get("blind_level", 0)

    if level >= len(BLIND_LEVELS) - 1:
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🃏 Финальный уровень. Блайнды остаются МБ 500 / ББ 1000.",
            )
        return

    game["blind_level"] = level + 1
    game["level_started_at"] = time.time()
    save_game(game)

    small, big = current_blinds(game)
    if chat_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🔺 Блайнды повышены!\n"
                f"Уровень {game['blind_level'] + 1}: МБ {small} / ББ {big}"
            ),
            reply_markup=game_keyboard(game),
        )

    schedule_blind_jobs(context.job_queue, game)


# ============================================================
# КОМАНДЫ
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    set_operator(chat, user)

    await reply_pm(update, context,
        f"♠️ {user.mention_html()}, бот включён только для тебя.\n\n"
        "Клавиатура и команды работают лишь у того, кто нажал /start.\n"
        "Новая игра: /newgame",
        parse_mode=ParseMode.HTML,
        do_quote=True,
        reply_markup=REPLY_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_pm(update, context,
        "♠️ КОМАНДЫ POKER BOT\n\n"
        "/start — включить бота только для себя\n"
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
        "/cancelgame — отменить игру без статистики\n\n"
        "🔧 АДМИНИСТРАТОР:\n"
        "/edit Bars 85 12500 7 12\n\n"
        "Формат /edit:\n"
        "Игрок → Очки → Выиграно грн → Победы → Игры"
    )


async def players_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "♠️ СПИСОК ИГРОКОВ\n\n"
    for i, name in enumerate(players.keys(), 1):
        text += f"{i}. {name}\n"
    await reply_pm(update, context,text)


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

    await reply_pm(update, context,text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context,"Используй:\n/stats Bars")
        return

    name = context.args[0]
    if name not in players:
        await reply_pm(update, context,"❌ Игрок не найден.")
        return

    data = players[name]
    ranking = sorted_players()
    place = next(
        i for i, (player_name, _) in enumerate(ranking, 1) if player_name == name
    )

    await reply_pm(update, context,
        f"♠️ СТАТИСТИКА {name.upper()}\n\n"
        f"🏅 Место: {place}\n"
        f"⭐ Очки: {data['points']}\n"
        f"🎮 Игр: {data['games']}\n"
        f"🏆 Побед: {data['wins']}\n"
        f"💰 Выиграно: {money_text(data['money'])}"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ranking = sorted_players()[:3]
    text = "🏆 TOP PLAYERS\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for i, (name, data) in enumerate(ranking):
        text += f"{medals[i]} {name} — {data['points']} очков\n"

    await reply_pm(update, context,text)


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blinds = "\n".join(
        f"{i}. МБ {sb} / ББ {bb}"
        for i, (sb, bb) in enumerate(BLIND_LEVELS, 1)
    )

    await reply_pm(update, context,
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
        "Таймер блайндов: 10 / 15 / 20 / 25 минут.\n\n"
        f"{blinds}"
    )


async def edit_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 5:
        await reply_pm(update, context,
            "❌ Неверный формат.\n\n"
            "Используй:\n"
            "/edit Bars 85 12500 7 12\n\n"
            "Где:\n"
            "Bars — игрок\n"
            "85 — очки\n"
            "12500 — выиграно грн\n"
            "7 — победы\n"
            "12 — игры"
        )
        return

    name = context.args[0]
    if name not in players:
        await reply_pm(update, context,f"❌ Игрок {name} не найден.")
        return

    try:
        points = int(context.args[1])
        money = int(context.args[2])
        wins = int(context.args[3])
        games_count = int(context.args[4])
    except ValueError:
        await reply_pm(update, context,
            "❌ Очки, деньги, победы и игры должны быть числами."
        )
        return

    players[name]["points"] = points
    players[name]["money"] = money
    players[name]["wins"] = wins
    players[name]["games"] = games_count
    save_players(players)

    await reply_pm(update, context,
        f"✅ Данные игрока {name} обновлены!\n\n"
        f"⭐ Очки: {points}\n"
        f"💰 Выиграно: {money_text(money)}\n"
        f"🏆 Победы: {wins}\n"
        f"🎮 Игр: {games_count}"
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = load_history()
    if not records:
        await reply_pm(update, context,"📜 История игр пока пустая.")
        return

    text = "📜 ИСТОРИЯ ИГР\n\n"
    for record in records[-10:][::-1]:
        places = record.get("places", {})
        first = places.get("1", "—")
        second = places.get("2", "—")
        third = places.get("3", "—")
        text += (
            f"🗓 {record.get('date', '—')}\n"
            f"🥇 {first} | 🥈 {second} | 🥉 {third}\n"
            f"💰 Банк: {money_text(record.get('prize_pool', 0))}\n\n"
        )

    await reply_pm(update, context,text)


async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game:
        await reply_pm(update, context,
            "Сейчас нет активной игры.\nНачни новую: /newgame"
        )
        return

    await reply_pm(update, context,
        game_panel_text(game),
        reply_markup=game_keyboard(game),
    )


async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") not in ("running", "paused"):
        await reply_pm(update, context,"Сейчас нет активного таймера.")
        return

    await reply_pm(update, context,
        time_text(game),
        reply_markup=game_keyboard(game),
    )


async def blinds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game or game.get("status") not in ("running", "paused"):
        await reply_pm(update, context,"Сейчас нет активной игры.")
        return

    await reply_pm(update, context,
        blinds_text(game),
        reply_markup=game_keyboard(game),
    )


# ============================================================
# НОВАЯ ИГРА
# ============================================================

async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if game and game.get("status") in ("running", "paused", "awaiting_bank"):
        await reply_pm(update, context,
            "Уже есть активная игра. Заверши или отмени её: /cancelgame"
        )
        return

    game = {
        "status": "setup",
        "selected": [],
        "buy_in": 0,
        "interval_min": 0,
        "blind_level": 0,
        "level_started_at": 0,
        "paused_remaining": 0,
        "chat_id": update.effective_chat.id,
        "alive": [],
        "eliminated": [],
        "rebuys": {},
        "awaiting": None,
    }
    save_game(game)

    await reply_pm(update, context,
        "♠️ НОВАЯ ИГРА\nОтметь, кто играет:",
        reply_markup=setup_keyboard(game),
    )


async def cancelgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = load_game()
    if not game:
        await reply_pm(update, context,"Активной игры нет.")
        return

    cancel_blind_jobs(context.job_queue)
    clear_game()
    await reply_pm(update, context,"❌ Игра отменена. Статистика не начислена.")


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await pause_timer(update.effective_chat.id, context, update.message)


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await resume_timer(update.effective_chat.id, context, update.message)


async def rebuy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context,"Используй:\n/rebuy Bars")
        return

    await apply_rebuy(context.args[0], update.message)


async def out_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_pm(update, context,"Используй:\n/out Bars")
        return

    await apply_out(context.args[0], context, update.message)


# ============================================================
# ЛОГИКА ИГРЫ
# ============================================================

async def start_tournament(query, context, game):
    now = time.time()
    game["status"] = "running"
    game["blind_level"] = 0
    game["level_started_at"] = now
    game["alive"] = list(game["selected"])
    game["eliminated"] = []
    game["rebuys"] = {name: 0 for name in game["selected"]}
    game["chat_id"] = query.message.chat_id
    save_game(game)

    schedule_blind_jobs(context.job_queue, game)
    small, big = current_blinds(game)

    await safe_edit(query,
        "🎮 ИГРА СТАРТОВАЛА\n\n"
        f"Игроки: {', '.join(game['selected'])}\n"
        f"Бай-ин: {money_text(game['buy_in'])}\n"
        f"Стартовый банк: {money_text(suggested_prize_pool(game))}\n"
        f"Таймер: {game['interval_min']} мин\n"
        f"Блайнды: МБ {small} / ББ {big}\n\n"
        "Ребай каждого игрока учитывается отдельно.\n"
        "Общий банк впишешь в конце — он делится 70% / 30%.",
        reply_markup=game_keyboard(game),
    )
    operator = get_operator(query.message.chat_id)
    mention = "Ведущий"
    if operator:
        mention = f'<a href="tg://user?id={operator["user_id"]}">{operator.get("name") or "Ведущий"}</a>'

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"{mention}, кнопки стола только у тебя. «⏱ Осталось времени» — проверка таймера.",
        parse_mode=ParseMode.HTML,
        reply_markup=REPLY_KEYBOARD,
    )


async def pause_timer(chat_id, context, message=None, query=None):
    game = load_game()
    if not game or game.get("status") != "running":
        text = "Пауза доступна только во время игры."
        if query:
            await query.answer(text, show_alert=True)
        elif message:
            await message.reply_text(text)
        return

    game["paused_remaining"] = remaining_seconds(game)
    game["status"] = "paused"
    save_game(game)
    cancel_blind_jobs(context.job_queue)

    text = (
        "⏸ Таймер на паузе.\n"
        f"Осталось: {format_mmss(game['paused_remaining'])}"
    )
    markup = game_keyboard(game)

    if query:
        await safe_edit(query,text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def resume_timer(chat_id, context, message=None, query=None):
    game = load_game()
    if not game or game.get("status") != "paused":
        text = "Продолжить можно только с паузы."
        if query:
            await query.answer(text, show_alert=True)
        elif message:
            await message.reply_text(text)
        return

    remaining = max(1, int(game.get("paused_remaining", 0)))
    interval = game.get("interval_min", 10) * 60
    game["status"] = "running"
    game["level_started_at"] = time.time() - (interval - remaining)
    game["paused_remaining"] = 0
    save_game(game)
    schedule_blind_jobs(context.job_queue, game)

    text = (
        "▶️ Таймер продолжен.\n"
        f"До повышения: {format_mmss(remaining_seconds(game))}"
    )
    markup = game_keyboard(game)

    if query:
        await safe_edit(query,text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def apply_rebuy(name, message=None, query=None):
    game = load_game()
    if not game or game.get("status") not in ("running", "paused"):
        text = "Ребай доступен только во время игры."
        if query:
            await query.answer(text, show_alert=True)
        elif message:
            await message.reply_text(text)
        return

    if name not in game.get("alive", []):
        text = f"{name} сейчас не за столом."
        if query:
            await query.answer(text, show_alert=True)
        elif message:
            await message.reply_text(text)
        return

    game.setdefault("rebuys", {})
    game["rebuys"][name] = int(game["rebuys"].get(name, 0)) + 1
    save_game(game)

    _, total = rebuy_summary(game)
    text = (
        f"🔁 Ребай: {name} (всего у игрока {game['rebuys'][name]})\n"
        f"Ребаев за стол: {total}\n"
        f"Расчётный банк: {money_text(suggested_prize_pool(game))}"
    )
    markup = game_keyboard(game)

    if query:
        await safe_edit(query,text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def apply_out(name, context, message=None, query=None):
    game = load_game()
    if not game or game.get("status") not in ("running", "paused"):
        text = "Отметить выбывание можно только во время игры."
        if query:
            await query.answer(text, show_alert=True)
        elif message:
            await message.reply_text(text)
        return

    if name not in game.get("alive", []):
        text = f"{name} уже не за столом."
        if query:
            await query.answer(text, show_alert=True)
        elif message:
            await message.reply_text(text)
        return

    game["alive"].remove(name)
    place = len(game["selected"]) - len(game["eliminated"])
    game["eliminated"].append({"name": name, "place": place})
    save_game(game)

    text = f"🚪 {name} выбыл. Место: {place}\nЗа столом: {', '.join(game['alive']) or '—'}"

    if len(game["alive"]) == 1:
        winner = game["alive"][0]
        game["eliminated"].append({"name": winner, "place": 1})
        game["alive"] = []
        game["status"] = "awaiting_bank"
        game["awaiting"] = "bank"
        save_game(game)
        cancel_blind_jobs(context.job_queue)

        suggested = suggested_prize_pool(game)
        rebuy_text, _ = rebuy_summary(game)
        start_bank = int(game["buy_in"]) * len(game["selected"])
        places = places_from_game(game)

        text = (
            "🏁 ТУРНИР ЗАВЕРШЁН\n\n"
            f"🥇 {places.get(1, '—')}\n"
            f"🥈 {places.get(2, '—')}\n"
            f"🥉 {places.get(3, '—')}\n\n"
            f"Стартовый банк: {money_text(start_bank)}\n"
            f"Ребаи:\n{rebuy_text}\n"
            f"Расчёт: {money_text(suggested)}\n\n"
            "Впиши общий банк числом (грн).\n"
            "Он разделится 70% / 30% между 1 и 2 местом."
        )

        if query:
            await safe_edit(query,text, reply_markup=game_keyboard(game))
        else:
            await message.reply_text(text, reply_markup=game_keyboard(game))
        return

    if query:
        await safe_edit(query,text, reply_markup=game_keyboard(game))
    else:
        await message.reply_text(text, reply_markup=game_keyboard(game))


def places_from_game(game):
    mapping = {}
    for item in game.get("eliminated", []):
        mapping[int(item["place"])] = item["name"]
    return mapping


async def finish_with_bank(source, context, prize_pool):
    game = load_game()
    if not game:
        await source.reply_text("Активной игры нет.")
        return

    if game.get("status") != "awaiting_bank":
        await source.reply_text("Сначала определи победителя (должен остаться один игрок).")
        return

    prize_pool = int(prize_pool)
    if prize_pool < 0:
        await source.reply_text("Банк не может быть отрицательным.")
        return

    places = places_from_game(game)
    first = places.get(1)
    second = places.get(2)
    third = places.get(3)

    if not first or not second:
        await source.reply_text("Нужны минимум 1 и 2 место, чтобы закрыть турнир.")
        return

    first_prize = int(round(prize_pool * PRIZE_SHARE[1]))
    second_prize = prize_pool - first_prize

    for name in game.get("selected", []):
        players[name]["games"] += 1

    players[first]["points"] += POINTS_BY_PLACE[1]
    players[first]["wins"] += 1
    players[first]["money"] += first_prize

    players[second]["points"] += POINTS_BY_PLACE[2]
    players[second]["money"] += second_prize

    if third:
        players[third]["points"] += POINTS_BY_PLACE[3]

    save_players(players)

    record = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "players": game.get("selected", []),
        "places": {str(place): name for place, name in places.items()},
        "prize_pool": prize_pool,
        "prizes": {"1": first_prize, "2": second_prize},
        "buy_in": game.get("buy_in", 0),
        "rebuys": game.get("rebuys", {}),
        "interval_min": game.get("interval_min", 0),
    }
    history_records = load_history()
    history_records.append(record)
    save_history(history_records)

    cancel_blind_jobs(context.job_queue)
    clear_game()

    ranking = sorted_players()[:3]
    top_text = "\n".join(
        f"{icon} {name} — {data['points']} очков"
        for icon, (name, data) in zip(["🥇", "🥈", "🥉"], ranking)
    )

    await source.reply_text(
        "✅ РЕЗУЛЬТАТЫ ЗАПИСАНЫ\n\n"
        f"🥇 {first}: +10 очков, +{money_text(first_prize)}\n"
        f"🥈 {second}: +5 очков, +{money_text(second_prize)}\n"
        + (f"🥉 {third}: +3 очка\n" if third else "")
        + f"\nБанк: {money_text(prize_pool)}\n\n"
        f"🏆 Обновлённый топ:\n{top_text}"
    )


# ============================================================
# CALLBACKS + ТЕКСТ
# ============================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    if data != "t:time":
        await query.answer()
    game = load_game()

    if data.startswith("sel:"):
        if not game or game.get("status") != "setup":
            await safe_edit(query,"Сначала начни /newgame")
            return
        name = data.split(":", 1)[1]
        selected = game.get("selected", [])
        if name in selected:
            selected.remove(name)
        else:
            selected.append(name)
        game["selected"] = selected
        save_game(game)
        await safe_edit(query,
            "♠️ НОВАЯ ИГРА\nОтметь, кто играет:",
            reply_markup=setup_keyboard(game),
        )
        return

    if data == "setup:cancel":
        cancel_blind_jobs(context.job_queue)
        clear_game()
        await safe_edit(query,"❌ Создание игры отменено.")
        return

    if data == "setup:next":
        if not game or game.get("status") != "setup":
            await safe_edit(query,"Сначала начни /newgame")
            return
        if len(game.get("selected", [])) < 2:
            await query.answer("Нужно минимум 2 игрока.", show_alert=True)
            return
        game["status"] = "waiting_buyin"
        game["awaiting"] = "buyin"
        save_game(game)
        await safe_edit(query,
            "💵 Впиши стартовый бай-ин одного игрока (грн).\n"
            "Пример: 500\n\n"
            f"Игроки: {', '.join(game['selected'])}"
        )
        return

    if data.startswith("int:"):
        if not game or game.get("status") != "waiting_interval":
            await safe_edit(query,"Сначала выбери бай-ин.")
            return
        game["interval_min"] = int(data.split(":", 1)[1])
        save_game(game)
        await start_tournament(query, context, game)
        return

    if not game:
        if data == "t:time":
            await query.answer("Сейчас нет активного таймера.", show_alert=True)
        await safe_edit(query, "Активной игры нет.")
        return

    if data == "t:time":
        remaining = time_text(game)
        await query.answer(remaining[:180], show_alert=True)
        await safe_edit(query,
            remaining,
            reply_markup=game_keyboard(game),
        )
        return

    if data == "t:blinds":
        await safe_edit(query,
            blinds_text(game),
            reply_markup=game_keyboard(game),
        )
        return

    if data == "t:panel":
        await safe_edit(query,
            game_panel_text(game),
            reply_markup=game_keyboard(game),
        )
        return

    if data == "t:pause":
        await pause_timer(query.message.chat_id, context, query=query)
        return

    if data == "t:resume":
        await resume_timer(query.message.chat_id, context, query=query)
        return

    if data == "t:rebuy":
        await safe_edit(query,
            "🔁 Кому ребай?",
            reply_markup=player_action_keyboard(game, "rebuy"),
        )
        return

    if data == "t:out":
        await safe_edit(query,
            "🚪 Кто выбыл?",
            reply_markup=player_action_keyboard(game, "out"),
        )
        return

    if data.startswith("rebuy:"):
        await apply_rebuy(data.split(":", 1)[1], query=query)
        return

    if data.startswith("out:"):
        await apply_out(data.split(":", 1)[1], context, query=query)
        return

    if data == "t:finish":
        alive = game.get("alive", [])
        if len(alive) > 1:
            await query.answer(
                "Отметь выбывших, пока не останется один победитель.",
                show_alert=True,
            )
            return
        if len(alive) == 1:
            winner = alive[0]
            game["eliminated"].append({"name": winner, "place": 1})
            game["alive"] = []
        game["status"] = "awaiting_bank"
        game["awaiting"] = "bank"
        save_game(game)
        cancel_blind_jobs(context.job_queue)
        suggested = suggested_prize_pool(game)
        rebuy_text, _ = rebuy_summary(game)
        start_bank = int(game["buy_in"]) * len(game["selected"])
        await safe_edit(query,
            "💰 Впиши общий банк турнира (грн).\n\n"
            f"Стартовый банк: {money_text(start_bank)}\n"
            f"Ребаи:\n{rebuy_text}\n"
            f"Расчёт: {money_text(suggested)}\n\n"
            "Деление: 70% / 30% между 1 и 2 местом.",
            reply_markup=game_keyboard(game),
        )
        return

    if data == "t:use_calc":
        class Source:
            async def reply_text(self, text, **kwargs):
                await safe_edit(query,text)

        await finish_with_bank(Source(), context, suggested_prize_pool(game))
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    raw = update.message.text.strip()

    if raw == "⏱ Осталось времени":
        await time_command(update, context)
        return
    if raw == "🃏 Блайнды":
        await blinds_command(update, context)
        return

    game = load_game()
    if not game:
        return

    if raw == "🔁 Ребай" and game.get("status") in ("running", "paused"):
        await reply_pm(update, context,
            "🔁 Кому ребай?",
            reply_markup=player_action_keyboard(game, "rebuy"),
        )
        return
    if raw == "🚪 Выбыл" and game.get("status") in ("running", "paused"):
        await reply_pm(update, context,
            "🚪 Кто выбыл?",
            reply_markup=player_action_keyboard(game, "out"),
        )
        return

    text = raw.replace(" ", "")
    awaiting = game.get("awaiting")

    if awaiting == "buyin" and game.get("status") == "waiting_buyin":
        if not text.isdigit():
            await reply_pm(update, context,"Нужно число. Пример: 500")
            return
        game["buy_in"] = int(text)
        game["status"] = "waiting_interval"
        game["awaiting"] = None
        save_game(game)
        start_bank = game["buy_in"] * len(game["selected"])
        await reply_pm(update, context,
            f"💵 Бай-ин: {money_text(game['buy_in'])}\n"
            f"Стартовый банк: {money_text(start_bank)}\n\n"
            "Выбери интервал повышения блайндов:",
            reply_markup=interval_keyboard(),
        )
        return

    if awaiting == "bank" and game.get("status") == "awaiting_bank":
        if not text.isdigit():
            await reply_pm(update, context,"Впиши общий банк числом. Пример: 7000")
            return
        await finish_with_bank(update.message, context, int(text))


# ============================================================
# ЗАПУСК
# ============================================================

async def on_startup(app: Application):
    game = load_game()
    if game and game.get("status") == "running":
        schedule_blind_jobs(app.job_queue, game)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, BadRequest) and "not modified" in str(error).lower():
        return
    print(f"⚠️ Ошибка бота: {error}")


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
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("♠️ Poker Bot запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
