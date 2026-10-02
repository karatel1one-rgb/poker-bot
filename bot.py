import json
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

PLAYERS_FILE = "players.json"


def load_players():
    if os.path.exists(PLAYERS_FILE):
        try:
            with open(PLAYERS_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            print("⚠️ Не удалось прочитать players.json. Создаём данные заново.")

    players = {
        "Bars": {"points": 0, "money": 0, "wins": 0, "games": 0},
        "Vadya": {"points": 0, "money": 0, "wins": 0, "games": 0},
        "Kostya": {"points": 0, "money": 0, "wins": 0, "games": 0},
        "Tokar": {"points": 0, "money": 0, "wins": 0, "games": 0},
        "Vova": {"points": 0, "money": 0, "wins": 0, "games": 0},
        "Danya": {"points": 0, "money": 0, "wins": 0, "games": 0},
        "Chubasya": {"points": 0, "money": 0, "wins": 0, "games": 0},
    }

    save_players(players)
    return players


def save_players(players):
    with open(PLAYERS_FILE, "w", encoding="utf-8") as file:
        json.dump(players, file, ensure_ascii=False, indent=4)


players = load_players()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "♠️ Добро пожаловать в Poker Bot!\n\n"
        "Напиши /Help, чтобы увидеть список команд."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "♠️ КОМАНДЫ POKER BOT\n\n"
        "/LeaderBoard — текущий рейтинг\n"
        "/Players — список игроков\n"
        "/Stats Bars — статистика игрока\n"
        "/Top — топ игроков\n"
        "/Rules — правила начисления очков\n"
        "/History — история игр\n"
        "/Game — информация об игре\n\n"
        "🔧 Администратор:\n"
        "/Edit Bars 85 12500 7 12\n\n"
        "Формат /Edit:\n"
        "Игрок → Очки → Выиграно грн → Победы → Игры"
    )


async def players_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "♠️ СПИСОК ИГРОКОВ\n\n"

    for i, name in enumerate(players.keys(), 1):
        text += f"{i}. {name}\n"

    await update.message.reply_text(text)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_players = sorted(
        players.items(),
        key=lambda x: x[1]["points"],
        reverse=True
    )

    text = (
        "♠️ POKER LEAGUE\n"
        "🏆 ОБЩИЙ РЕЙТИНГ\n\n"
    )

    medals = ["🥇", "🥈", "🥉"]

    for place, (name, data) in enumerate(sorted_players, 1):
        if place <= 3:
            icon = medals[place - 1]
        else:
            icon = f"{place}."

        text += (
            f"{icon} {name}\n"
            f"⭐ {data['points']} очков | "
            f"🏆 {data['wins']} побед\n"
            f"💰 {data['money']:,} грн | "
            f"🎮 {data['games']} игр\n\n"
        )

    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Используй:\n/Stats Bars")
        return

    name = context.args[0]

    if name not in players:
        await update.message.reply_text("❌ Игрок не найден.")
        return

    data = players[name]

    sorted_players = sorted(
        players.items(),
        key=lambda x: x[1]["points"],
        reverse=True
    )

    place = next(
        i for i, (player_name, _) in enumerate(sorted_players, 1)
        if player_name == name
    )

    text = (
        f"♠️ СТАТИСТИКА {name.upper()}\n\n"
        f"🏅 Место: {place}\n"
        f"⭐ Очки: {data['points']}\n"
        f"🎮 Игр: {data['games']}\n"
        f"🏆 Побед: {data['wins']}\n"
        f"💰 Выиграно: {data['money']:,} грн"
    )

    await update.message.reply_text(text)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_players = sorted(
        players.items(),
        key=lambda x: x[1]["points"],
        reverse=True
    )

    text = "🏆 TOP PLAYERS\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for i, (name, data) in enumerate(sorted_players[:3]):
        text += f"{medals[i]} {name} — {data['points']} очков\n"

    await update.message.reply_text(text)


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "♠️ ПРАВИЛА НАЧИСЛЕНИЯ ОЧКОВ\n\n"
        "🥇 1 место — 10 очков\n"
        "🥈 2 место — 5 очков\n"
        "🥉 3 место — 3 очка\n"
        "4 место — 2 очка\n"
        "5 место — 1 очко\n"
        "6–10 место — 0 очков\n\n"
        "Очки используются для определения места в общем рейтинге."
    )


async def edit_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 5:
        await update.message.reply_text(
            "❌ Неверный формат.\n\n"
            "Используй:\n"
            "/Edit Bars 85 12500 7 12\n\n"
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
        await update.message.reply_text(f"❌ Игрок {name} не найден.")
        return

    try:
        points = int(context.args[1])
        money = int(context.args[2])
        wins = int(context.args[3])
        games = int(context.args[4])
    except ValueError:
        await update.message.reply_text(
            "❌ Очки, деньги, победы и игры должны быть числами."
        )
        return

    players[name]["points"] = points
    players[name]["money"] = money
    players[name]["wins"] = wins
    players[name]["games"] = games

    save_players(players)

    await update.message.reply_text(
        f"✅ Данные игрока {name} обновлены!\n\n"
        f"⭐ Очки: {points}\n"
        f"💰 Выиграно: {money:,} грн\n"
        f"🏆 Победы: {wins}\n"
        f"🎮 Игр: {games}"
    )


async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Раздел добавления игр пока находится в разработке.\n\n"
        "Пока статистику можно менять вручную через /Edit."
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📜 История игр пока пустая.")


def main():
    if not TOKEN or TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_БОТА":
        print("❌ ОШИБКА: не указан TOKEN бота.")
        print("Открой bot.py и вставь настоящий TOKEN.")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("players", players_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("edit", edit_player))
    app.add_handler(CommandHandler("game", game))
    app.add_handler(CommandHandler("history", history))

    print("♠️ Poker Bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
