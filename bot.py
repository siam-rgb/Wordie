"""
Word Chain Telegram bot. Everything happens in the group chat — no DMs needed,
since there's nothing private to hide (unlike UNO hands).

Setup:
  1. pip install -r requirements.txt
  2. export BOT_TOKEN=xxxx
  3. python bot.py
"""
import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from game import WordChainGame, GameError, load_wordlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wordchain_bot")

TURN_SECONDS = 30
WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "words_alpha.txt")

GAMES: dict[int, WordChainGame] = {}
TIMEOUT_TASKS: dict[int, asyncio.Task] = {}  # chat_id -> pending timeout task

_wordlist_cache = None


def get_wordlist():
    global _wordlist_cache
    if _wordlist_cache is None:
        log.info("Loading wordlist...")
        _wordlist_cache = load_wordlist(WORDLIST_PATH)
        log.info(f"Loaded {len(_wordlist_cache)} words")
    return _wordlist_cache


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 Word Chain! /newgame to start a lobby here, /join to enter, "
        "/startgame when ready. Then just type words in chat on your turn."
    )


async def newgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("Start this in a group chat, not DM.")
        return
    if chat.id in GAMES and not GAMES[chat.id].finished:
        await update.message.reply_text("A game's already active here. /endgame to cancel it first.")
        return

    hard_mode = bool(context.args and context.args[0].lower() in ("hard", "hardmode"))
    game = WordChainGame(chat.id, user.id, user.first_name, get_wordlist(), hard_mode=hard_mode)
    GAMES[chat.id] = game
    mode_note = " (hard mode: always 2-3 letters)" if hard_mode else ""
    await update.message.reply_text(
        f"🔗 Word Chain lobby created by {user.first_name}!{mode_note}\n"
        f"Players: {user.first_name}\n\n"
        "Others type /join to enter (2-8 players).\n"
        "Host runs /startgame when everyone's in.\n"
        "(Tip: /newgame hard for always-tricky 2-3 letter requirements.)"
    )


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = GAMES.get(chat.id)
    if not game or game.finished:
        await update.message.reply_text("No active lobby. Use /newgame first.")
        return
    try:
        added = game.add_player(user.id, user.first_name)
    except GameError as e:
        await update.message.reply_text(str(e))
        return
    if not added:
        await update.message.reply_text("You're already in.")
        return
    names = ", ".join(p.name for p in game.players)
    await update.message.reply_text(f"✅ {user.first_name} joined! ({len(game.players)}/8): {names}")


async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = GAMES.get(chat.id)
    if not game:
        await update.message.reply_text("No lobby here. /newgame to create one.")
        return
    if game.players[0].user_id != user.id:
        await update.message.reply_text("Only the host can start the game.")
        return
    try:
        game.start()
    except GameError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(
        f"🎮 Game on! Starting word: *{game.last_word.upper()}*\n"
        f"Next word must start with: *{game.required_prefix.upper()}*\n"
        f"❤️ Each player has {game.players[0].lives} lives.\n\n"
        f"👉 {game.current_player().name}'s turn — {TURN_SECONDS}s, just type your word!",
        parse_mode="Markdown",
    )
    await schedule_timeout(context, chat.id)


async def endgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cancel_timeout(chat_id)
    if chat_id in GAMES:
        del GAMES[chat_id]
        await update.message.reply_text("🛑 Game ended.")
    else:
        await update.message.reply_text("No game to end here.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(update.effective_chat.id)
    if not game:
        await update.message.reply_text("No active game here.")
        return
    if not game.started:
        names = ", ".join(p.name for p in game.players)
        await update.message.reply_text(f"Lobby ({len(game.players)}/8): {names}")
        return
    lives = ", ".join(f"{p.name}: {'❤️' * max(p.lives,0)}" for p in game.players)
    await update.message.reply_text(
        f"Last word: {game.last_word}\n"
        f"Next must start with: *{game.required_prefix.upper()}*\n"
        f"Turn: {game.current_player().name}\n{lives}",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Turn timer
# ---------------------------------------------------------------------------

def cancel_timeout(chat_id: int):
    task = TIMEOUT_TASKS.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


async def schedule_timeout(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    cancel_timeout(chat_id)

    async def _timeout_job():
        try:
            await asyncio.sleep(TURN_SECONDS)
        except asyncio.CancelledError:
            return
        game = GAMES.get(chat_id)
        if not game or game.finished:
            return
        result = game.timeout_current()
        msg = f"⏰ {result['player']} took too long! Lost a life ({result['lives_left']} left)."
        if result.get("game_over"):
            await finish_game(context, chat_id, msg)
        else:
            await context.bot.send_message(
                chat_id,
                f"{msg}\n👉 {game.current_player().name}'s turn — starts with "
                f"*{game.required_prefix.upper()}* ({TURN_SECONDS}s)",
                parse_mode="Markdown",
            )
            await schedule_timeout(context, chat_id)

    TIMEOUT_TASKS[chat_id] = asyncio.create_task(_timeout_job())


async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lead_msg: str = ""):
    cancel_timeout(chat_id)
    game = GAMES.get(chat_id)
    if not game:
        return
    prefix = f"{lead_msg}\n\n" if lead_msg else ""
    if game.winner:
        await context.bot.send_message(chat_id, f"{prefix}🏆 {game.winner.name} wins the chain! GG 🎉")
    else:
        await context.bot.send_message(chat_id, f"{prefix}Game over — no survivors!")
    GAMES.pop(chat_id, None)


# ---------------------------------------------------------------------------
# Plain text = word submissions
# ---------------------------------------------------------------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = GAMES.get(chat_id)
    if not game or not game.started or game.finished:
        return

    user = update.effective_user
    player = game.get_player(user.id)
    if not player or game.current_player().user_id != user.id:
        return  # ignore chatter from non-current players / non-participants

    text = update.message.text or ""
    if text.startswith("/"):
        return

    result = game.submit_word(player, text)
    cancel_timeout(chat_id)

    if result["valid"]:
        await update.message.reply_text(
            f"✅ {result['word']} — next must start with *{game.required_prefix.upper()}*",
            parse_mode="Markdown",
        )
        if result.get("game_over"):
            await finish_game(context, chat_id)
            return
        await context.bot.send_message(
            chat_id,
            f"👉 {game.current_player().name}'s turn ({TURN_SECONDS}s)",
        )
        await schedule_timeout(context, chat_id)
    else:
        msg = f"❌ {result['reason']} ({player.name} loses a life — {result.get('lives_left', player.lives)} left)"
        if result.get("game_over"):
            await finish_game(context, chat_id, msg)
            return
        await update.message.reply_text(
            f"{msg}\n👉 {game.current_player().name}'s turn — starts with "
            f"*{game.required_prefix.upper()}* ({TURN_SECONDS}s)",
            parse_mode="Markdown",
        )
        await schedule_timeout(context, chat_id)


# ---------------------------------------------------------------------------
# Keep-alive (Render free tier) + entrypoint
# ---------------------------------------------------------------------------

def start_keepalive_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Word Chain bot is alive")

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info(f"Keep-alive HTTP server listening on port {port}")


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Set BOT_TOKEN environment variable.")

    start_keepalive_server()
    get_wordlist()  # preload at startup, not on first game

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("newgame", newgame_cmd))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("startgame", startgame_cmd))
    app.add_handler(CommandHandler("endgame", endgame_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Word Chain bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
