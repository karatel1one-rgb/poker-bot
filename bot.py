    # Header
    draw.rounded_rectangle((40, 35, WIDTH - 40, 135), radius=28, fill=PANEL, outline=(43, 57, 80), width=2)
    draw.text((72, 52), "POKER LEAGUE", font=_font(25, True), fill=GOLD)
    draw.text((72, 82), "ОБЩИЙ РЕЙТИНГ", font=_font(34, True), fill=TEXT)
    draw.text((WIDTH - 75, 78), f"ИГРОКОВ: {len(ranking)}", font=_font(18, True), fill=MUTED, anchor="ra")

    if not ranking:
        draw.text((WIDTH // 2, 260), "Пока нет игроков", font=_font(30, True), fill=MUTED, anchor="mm")
    else:
        podium_top = 170
        card_gap = 18
        card_width = (WIDTH - 80 - 2 * card_gap) // 3
        order = [1, 0, 2] if len(ranking) >= 3 else list(range(len(ranking)))
        # With fewer than three players, keep the podium centered.
        if len(ranking) < 3:
            card_width = min(330, (WIDTH - 80 - 18 * (len(ranking) - 1)) // len(ranking))
            total = card_width * len(ranking) + 18 * (len(ranking) - 1)
            starts = [(WIDTH - total) // 2 + i * (card_width + 18) for i in range(len(ranking))]
            placements = [(idx, starts[idx], podium_top + 8) for idx in range(len(ranking))]
        else:
            placements = [(idx, 40 + i * (card_width + card_gap), podium_top + (0 if idx == 0 else 22)) for i, idx in enumerate(order)]
        for idx, x, y in placements:
            name, data = ranking[idx]
            accent = ACCENTS[idx] if idx < 3 else GOLD
            card_h = 280 if idx == 0 else 258
            draw.rounded_rectangle((x, y, x + card_width, y + card_h), radius=26, fill=PANEL, outline=accent, width=3)
            medal = ["1 МЕСТО", "2 МЕСТО", "3 МЕСТО"][idx] if idx < 3 else f"{idx + 1} МЕСТО"
            draw.text((x + card_width // 2, y + 25), medal, font=_font(19, True), fill=accent, anchor="mm")
            photo_size = 94
            photo = _photo(os.path.join(photos_dir, f"{name}.jpg"), photo_size)
            px, py = x + (card_width - photo_size) // 2, y + 48
            draw.ellipse((px - 4, py - 4, px + photo_size + 4, py + photo_size + 4), outline=accent, width=3)
            if photo:
                image.paste(photo, (px, py), photo)
            else:
                draw.ellipse((px, py, px + photo_size, py + photo_size), fill=(39, 51, 73))
                initials = "".join(part[0] for part in name.replace("_", " ").split()[:2]).upper()[:2] or "?"
                draw.text((px + photo_size // 2, py + photo_size // 2), initials, font=_font(30, True), fill=TEXT, anchor="mm")
            name_font = _font(25 if len(name) < 13 else 20, True)
            draw.text((x + card_width // 2, y + 158), name, font=name_font, fill=TEXT, anchor="mm")
            draw.text((x + card_width // 2, y + 193), f"{int(data.get('points', 0) or 0)} очков", font=_font(22, True), fill=accent, anchor="mm")
            draw.text((x + card_width // 2, y + 226), f"{int(data.get('wins', 0) or 0)} побед  •  {int(data.get('games', 0) or 0)} игр",
                      font=_font(14, True), fill=MUTED, anchor="mm")
            draw.text((x + card_width // 2, y + 250), _money(data.get("money", 0)), font=_font(16, True), fill=TEXT, anchor="mm")

    # Compact list for the remaining players.
    remaining = ranking[3:]
    if remaining:
        list_top = 510
        draw.text((55, list_top), "ОСТАЛЬНЫЕ ИГРОКИ", font=_font(22, True), fill=MUTED)
        y = list_top + 42
        for idx, (name, data) in enumerate(remaining, 4):
            draw.rounded_rectangle((40, y, WIDTH - 40, y + 82), radius=18, fill=PANEL)
            draw.text((65, y + 41), f"{idx:02d}", font=_font(22, True), fill=MUTED, anchor="lm")
            photo = _photo(os.path.join(photos_dir, f"{name}.jpg"), 56)
            px, py = 120, y + 13
            if photo:
                image.paste(photo, (px, py), photo)
            else:
                draw.ellipse((px, py, px + 56, py + 56), fill=(39, 51, 73))
                initials = "".join(part[0] for part in name.replace("_", " ").split()[:2]).upper()[:2] or "?"
                draw.text((px + 28, py + 28), initials, font=_font(18, True), fill=TEXT, anchor="mm")
            draw.text((195, y + 41), name, font=_font(22, True), fill=TEXT, anchor="lm")
            draw.text((590, y + 41), f"{int(data.get('points', 0) or 0)} очков", font=_font(18, True), fill=GOLD, anchor="lm")
            draw.text((800, y + 41), f"{int(data.get('wins', 0) or 0)} побед", font=_font(17), fill=MUTED, anchor="lm")
            draw.text((WIDTH - 65, y + 41), _money(data.get("money", 0)), font=_font(18, True), fill=TEXT, anchor="rm")
            y += row_height
    draw.text((WIDTH // 2, height - 35), "Рейтинг обновляется из статистики игроков", font=_font(15), fill=(105, 119, 143), anchor="mm")

    fd, path = tempfile.mkstemp(prefix="poker_leaderboard_", suffix=".png")
    os.close(fd)
    image.save(path, format="PNG", optimize=True)
    return path

def main():
    if not TOKEN:
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
    app.add_handler(CommandHandler("setphoto", setphoto_command))
    app.add_handler(CommandHandler("removephoto", removephoto_command))
    app.add_handler(CommandHandler("photos", photos_command))
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
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE), receive_player_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("♠️ Покерный бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
