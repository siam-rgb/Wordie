"""
Word Chain game engine.
Players take turns saying a word that starts with the required letter(s)
from the end of the previous word. Wrong/timeout = lose a life.
Last player with lives remaining wins.
"""
import random
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_LIVES = 3
MIN_WORD_LEN = 2
HARD_MODE_CHANCE = 0.3  # chance the next required prefix is 2-3 letters instead of 1


def load_wordlist(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        return {w.strip().lower() for w in f if len(w.strip()) >= MIN_WORD_LEN}


@dataclass
class Player:
    user_id: int
    name: str
    lives: int = DEFAULT_LIVES
    words_played: int = 0

    def alive(self) -> bool:
        return self.lives > 0


class GameError(Exception):
    pass


class WordChainGame:
    def __init__(self, chat_id: int, host_id: int, host_name: str, wordlist: set[str], hard_mode: bool = False):
        self.chat_id = chat_id
        self.players: list[Player] = [Player(host_id, host_name)]
        self.wordlist = wordlist
        self.hard_mode = hard_mode  # if True, always require 2-3 letters (not just occasionally)
        self.used_words: set[str] = set()
        self.current_idx = 0
        self.required_prefix = ""  # letters the next word must start with
        self.last_word = ""
        self.started = False
        self.finished = False
        self.winner: Optional[Player] = None

    # ---------- lobby ----------
    def add_player(self, user_id: int, name: str) -> bool:
        if self.started:
            raise GameError("Game already started.")
        if any(p.user_id == user_id for p in self.players):
            return False
        if len(self.players) >= 8:
            raise GameError("Lobby full (max 8 players).")
        self.players.append(Player(user_id, name))
        return True

    def get_player(self, user_id: int) -> Optional[Player]:
        for p in self.players:
            if p.user_id == user_id:
                return p
        return None

    # ---------- start ----------
    def start(self):
        if len(self.players) < 2:
            raise GameError("Need at least 2 players to start.")
        # pick a reasonable starting word, not too short, not absurdly long
        candidates = [w for w in self.wordlist if 4 <= len(w) <= 7]
        start_word = random.choice(candidates) if candidates else random.choice(list(self.wordlist))
        self.last_word = start_word
        self.used_words.add(start_word)
        self._set_next_requirement(start_word)
        self.current_idx = 0
        self.started = True

    def _set_next_requirement(self, word: str):
        n = 1
        if self.hard_mode or random.random() < HARD_MODE_CHANCE:
            n = random.randint(2, 3)
        n = min(n, len(word))
        self.required_prefix = word[-n:].lower()

    # ---------- helpers ----------
    def current_player(self) -> Player:
        return self.players[self.current_idx]

    def alive_players(self) -> list[Player]:
        return [p for p in self.players if p.alive()]

    def advance_turn(self):
        n = len(self.players)
        for _ in range(n):
            self.current_idx = (self.current_idx + 1) % n
            if self.players[self.current_idx].alive():
                return
        # nobody alive (shouldn't happen, finish() should've caught it)

    def check_finished(self) -> bool:
        alive = self.alive_players()
        if len(alive) <= 1:
            self.finished = True
            self.winner = alive[0] if alive else None
            return True
        return False

    # ---------- core validation ----------
    def validate(self, raw_word: str) -> tuple[bool, str]:
        """Returns (is_valid, reason_if_invalid)."""
        word = raw_word.strip().lower()
        if not word.isalpha():
            return False, "Only letters allowed."
        if not word.startswith(self.required_prefix):
            return False, f"Must start with '{self.required_prefix.upper()}'."
        if word in self.used_words:
            return False, "Already used in this game."
        if word not in self.wordlist:
            return False, "Not a recognized word."
        if word == self.last_word:
            return False, "Can't repeat the same word."
        return True, ""

    def submit_word(self, player: Player, raw_word: str) -> dict:
        """Apply a word submission. Returns result info for the bot layer."""
        valid, reason = self.validate(raw_word)
        result = {"valid": valid, "reason": reason, "word": raw_word.strip().lower()}

        if valid:
            word = result["word"]
            self.used_words.add(word)
            self.last_word = word
            player.words_played += 1
            self._set_next_requirement(word)
            self.advance_turn()
        else:
            player.lives -= 1
            result["lives_left"] = player.lives
            if self.check_finished():
                result["game_over"] = True
                return result
            self.advance_turn()

        result["game_over"] = self.check_finished()
        return result

    def timeout_current(self) -> dict:
        """Called when the current player doesn't answer in time."""
        player = self.current_player()
        player.lives -= 1
        result = {"timed_out": True, "player": player.name, "lives_left": player.lives}
        if self.check_finished():
            result["game_over"] = True
            return result
        self.advance_turn()
        result["game_over"] = self.check_finished()
        return result
