# Word Chain Telegram Bot

2-8 players, all in the **group chat** (no DMs needed — nothing to hide here).
Bot says a starting word; each player in turn types a word starting with the
last letter(s) of the previous word. Wrong, unrecognized, repeated, or
too-slow = lose a life. Last one standing wins.

## Setup

1. Get a bot token from [@BotFather](https://t.me/BotFather)
2. **Important**: `/setprivacy` → select bot → **Disable**. This game reads
   plain chat messages (not just commands), so privacy mode MUST be off or
   the bot won't see anyone's word submissions.
3. Copy `.env.example` to `.env`, paste your token
4. Run:
   ```
   docker compose up -d --build
   ```
   or locally:
   ```
   pip install -r requirements.txt --break-system-packages
   export BOT_TOKEN=xxxx
   python bot.py
   ```

## Mobile-only / Render deployment
Same flow as the UNO bot: upload this folder's files to a GitHub repo via
the mobile "Add file → Upload files" button, connect that repo as a new
Render Web Service (free plan, `render.yaml` auto-fills build/start
commands), set `BOT_TOKEN` in the Environment tab, deploy. Use UptimeRobot
to ping the live URL every 5 min so it doesn't sleep.

## Playing

- `/newgame` — create lobby (add `hard` after it, e.g. `/newgame hard`, for
  always-tricky 2-3 letter requirements instead of occasional)
- `/join` — join (2-8 players)
- `/startgame` — host starts; bot picks a random starting word
- Type your word in chat on your turn — no command needed, no `/` prefix
- `/status` — check whose turn, lives, current required prefix
- `/endgame` — cancel

Each turn has a 30-second timer — miss it and you lose a life automatically.

## Rules implemented
- Required prefix is normally the last 1 letter of the previous word, but
  ~30% of the time (or always, in hard mode) it's the last 2-3 letters
- Word must be a real word (checked against a ~370k-word English list),
  unused so far this game, and not a literal repeat of the previous word
- 3 lives per player by default; lose all 3 → eliminated
- Game ends when 1 player remains; they win

## Known simplifications
- The wordlist (`words_alpha.txt`, from the dwyl/english-words project) is
  large but not perfectly curated — a handful of unusual entries (abbreviations,
  etc.) slip through. Fine for casual play.
- No proper-noun filtering, no plural/tense awareness beyond what's literally
  in the wordlist
- Lives are fixed at 3, not configurable via command (easy to add an arg to
  `/newgame` if you want, same pattern as `hard`)
- State is in-memory only — restarting the bot wipes any game in progress

## Files
- `game.py` — pure game logic (validation, turns, lives) — no Telegram code
- `bot.py` — Telegram wiring, including the per-turn timeout task
- `words_alpha.txt` — the wordlist used for validation
