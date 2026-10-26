import os
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Бот берет токен из настроек Render (переменная MAFIA_TOKEN)
TOKEN = os.getenv("MAFIA_TOKEN")

games = {}
ROLES = {"mafia": "🔫 Мафия", "commissar": "🕵️‍♂️ Комиссар", "doctor": "💊 Доктор", "civilian": "👨‍🌾 Мирный житель"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🕵️‍♂️ **Добро пожаловать в Мафию!**\n\nЧтобы начать, напиши `/newgame` (в группе). Игроки должны написать `/join`. Когда наберется 5+ человек, админ пишет `/startgame`.", parse_mode="Markdown")

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games:
        await update.message.reply_text("Игра уже создана! Пишите /join.")
        return
    games[chat_id] = {"players": [], "roles": {}, "alive": [], "phase": "lobby", "night_actions": {}, "votes": {}}
    await update.message.reply_text("🎭 Новая игра создана! Напишите /join, чтобы участвовать.")

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        await update.message.reply_text("Сначала создайте игру: /newgame")
        return
    if games[chat_id]["phase"] != "lobby":
        await update.message.reply_text("Игра уже началась!")
        return
    if user.id in games[chat_id]["players"]:
        await update.message.reply_text("Ты уже в игре!")
        return
    games[chat_id]["players"].append(user.id)
    await update.message.reply_text(f"✅ {user.first_name} в игре! (Всего: {len(games[chat_id]['players'])})")

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in games:
        await update.message.reply_text("Сначала создайте игру.")
        return
    game = games[chat_id]
    if len(game["players"]) < 5:
        await update.message.reply_text(f"Нужно минимум 5 игроков. Сейчас: {len(game['players'])}")
        return
    game["phase"] = "night"
    players = game["players"].copy()
    random.shuffle(players)
    roles = ["mafia", "mafia", "commissar", "doctor"] + ["civilian"] * (len(players) - 4)
    
    for i, player_id in enumerate(players):
        game["roles"][player_id] = roles[i]
        game["alive"].append(player_id)
        try:
            await context.bot.send_message(chat_id=player_id, text=f"Твоя роль: **{ROLES[roles[i]]}**\n\n{get_role_desc(roles[i])}", parse_mode="Markdown")
        except:
            await update.message.reply_text(f"Не могу написать в личку одному из игроков. Убедитесь, что вы нажали Start у бота в личке!")

    await update.message.reply_text("🌙 **Город засыпает.**\nРоли разосланы в личку. Ожидаем ночные действия...")
    await night_phase(update, context)

def get_role_desc(role):
    if role == "mafia": return "Ты — мафия! Ночью выбирай, кого убить. Днем притворяйся мирным."
    if role == "commissar": return "Ты — комиссар! Ночью проверяй одного человека."
    if role == "doctor": return "Ты — доктор! Ночью лечи одного человека."
    return "Ты — мирный житель! Днем голосуй против мафии."

async def night_phase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games[chat_id]
    game["night_actions"] = {}
    for player_id, role in game["roles"].items():
        if player_id not in game["alive"]: continue
        if role == "mafia":
            keyboard = [[InlineKeyboardButton(f"Убить {p}", callback_data=f"kill_{p}")] for p in game["alive"] if p != player_id and game["roles"][p] != "mafia"]
            await context.bot.send_message(player_id, "🔫 Выбери жертву:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif role == "doctor":
            keyboard = [[InlineKeyboardButton(f"Лечить {p}", callback_data=f"heal_{p}")] for p in game["alive"]]
            await context.bot.send_message(player_id, "💊 Выбери, кого лечить:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif role == "commissar":
            keyboard = [[InlineKeyboardButton(f"Проверить {p}", callback_data=f"check_{p}")] for p in game["alive"] if p != player_id]
            await context.bot.send_message(player_id, "🕵️‍♂️ Выбери, кого проверить:", reply_markup=InlineKeyboardMarkup(keyboard))

async def night_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    action, target = data.split("_")
    target = int(target)
    for chat_id, game in games.items():
        if user_id in game["alive"] and game["phase"] == "night":
            game["night_actions"][action] = target
            if action == "check":
                target_role = game["roles"].get(target)
                is_mafia = "Да! Это МАФИЯ! 🔴" if target_role == "mafia" else "Нет, он мирный. 🟢"
                await query.edit_message_text(f"Результат проверки: {is_mafia}")
            else:
                await query.edit_message_text(f"Выбор сделан. Ждем остальных...")
            needed_actions = 3 if len(game["players"]) >= 5 else 2
            if len(game["night_actions"]) >= needed_actions:
                await resolve_night(context, chat_id, game)
            return

async def resolve_night(context: ContextTypes.DEFAULT_TYPE, chat_id, game):
    game["phase"] = "day"
    killed = game["night_actions"].get("kill")
    healed = game["night_actions"].get("heal")
    if killed and killed != healed:
        game["alive"].remove(killed)
        text = f"🌅 **Город просыпается.**\nНочью был убит игрок. (ID: {killed})."
    else:
        text = "🌅 **Город просыпается.**\nЭтой ночью никто не погиб!"
    await context.bot.send_message(chat_id, text)
    await day_phase(context, chat_id, game)

async def day_phase(context: ContextTypes.DEFAULT_TYPE, chat_id, game):
    game["votes"] = {}
    keyboard = [[InlineKeyboardButton(f"Казнить {p}", callback_data=f"vote_{p}")] for p in game["alive"]]
    await context.bot.send_message(chat_id, "🗳 **Голосование!** Кого казним?", reply_markup=InlineKeyboardMarkup(keyboard))

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    voter_id = query.from_user.id
    data = query.data
    _, target = data.split("_")
    target = int(target)
    for chat_id, game in games.items():
        if voter_id in game["alive"] and game["phase"] == "day":
            game["votes"][voter_id] = target
            await query.edit_message_text(f"Ты проголосовал против {target}.")
            if len(game["votes"]) >= len(game["alive"]):
                await resolve_vote(context, chat_id, game)
            return

async def resolve_vote(context: ContextTypes.DEFAULT_TYPE, chat_id, game):
    vote_counts = {}
    for target in game["votes"].values():
        vote_counts[target] = vote_counts.get(target, 0) + 1
    max_votes = max(vote_counts.values())
    most_voted = [p for p, v in vote_counts.items() if v == max_votes]
    if len(most_voted) == 1:
        killed = most_voted[0]
        game["alive"].remove(killed)
        await context.bot.send_message(chat_id, f"⚖️ Город решил казнить игрока (ID: {killed}).")
    else:
        await context.bot.send_message(chat_id, "⚖️ Голоса разделились. Никто не казнен.")
    mafia_alive = [p for p in game["alive"] if game["roles"][p] == "mafia"]
    civ_alive = [p for p in game["alive"] if game["roles"][p] != "mafia"]
    if not mafia_alive:
        await context.bot.send_message(chat_id, "🎉 **Мирные жители победили!** Мафия казнена.")
        del games[chat_id]
    elif len(mafia_alive) >= len(civ_alive):
        await context.bot.send_message(chat_id, "🔴 **Мафия победила!** Город захвачен.")
        del games[chat_id]
    else:
        await context.bot.send_message(chat_id, "🌙 **Снова ночь.**")
        game["phase"] = "night"
        await night_phase(update=None, context=context)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newgame", new_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CallbackQueryHandler(night_action_callback, pattern="^(kill_|heal_|check_)"))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern="^vote_"))
    print("Бот Мафия запущен на сервере!")
    app.run_polling()

if __name__ == "__main__":
    main()
