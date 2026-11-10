"""
VersiDen: a local roleplay companion app.

Every world is a folder inside "worlds":

    worlds/<world>/
      world.md                           name, genre, tone, overview, writing format
      characters/<name>/<name>.md        main characters (you write)
      characters/<name>/with-<user>/     their story with one user (the app writes)
      lore/                              world notes (core/ = always-on foundations)
      npcs/                              side characters
      users/                             who you play as, in this world only

Run:  python app.py   then open http://localhost:5000
"""

import hashlib
import base64
import json
import queue
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import tomllib
import uuid
import webbrowser
import zipfile
from datetime import timedelta
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import requests
from flask import (Flask, Response, abort, has_request_context, jsonify, redirect, render_template, request,
                   send_file, session)
from werkzeug.security import check_password_hash, generate_password_hash

# ================================================================ config.toml
# Port, LM Studio address and where your worlds live are in config.toml (created on first
# start, next to this file). Restart the app after changing it.
BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.toml"
CONFIG_TEMPLATE = """# Settings for running the app. Restart the app after changing this file.

# The port the app listens on.
port = 5000

# The address to use on this PC. Any name ending in .localhost works in Chrome, Edge and Firefox
# without any extra setup, e.g. "versiden.localhost" or "stories.localhost".
pc_address = "versiden.localhost"

# LM Studio -> Model Server -> "Reachable at", followed by /v1.
lmstudio_url = "http://localhost:1234/v1"

# Where your worlds live: a folder name inside this app's folder, or a full path in single
# quotes, e.g. 'C:\\Users\\you\\Documents\\Worlds'
worlds_dir = "worlds"


# Keep a daily zip of your worlds in the "backups" folder (the last 7 days).
daily_backups = true
"""
APP_NAME = "VersiDen"
CONFIG_DEFAULTS = {"port": 5000, "pc_address": "versiden.localhost", "lmstudio_url": "http://localhost:1234/v1",
                   "worlds_dir": "worlds", "app_name": APP_NAME, "daily_backups": True}


def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    try:
        return {**CONFIG_DEFAULTS, **tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))}
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"!! config.toml has a mistake ({e}). Using the default settings for now.")
        return dict(CONFIG_DEFAULTS)


CONFIG = load_config()
if CONFIG.get("app_name") in ("", "Roleplay"):   # the old default name from before VersiDen
    CONFIG["app_name"] = APP_NAME

# ================================================================ settings
LMSTUDIO_URL = str(CONFIG["lmstudio_url"]).rstrip("/")
RECENT_KEEP = 20            # messages always kept word-for-word

# Model settings are changed on the app's Model Settings page (saved in worlds/.settings.json).
# These are only the starting values.
DEFAULT_SETTINGS = {
    "model": "",                # "" = whichever model LM Studio has loaded
    "prompt_format": "auto",    # auto / qwen / chat  (see Settings page)
    "flair": "roleplay",        # style preset, see FLAIRS
    "reasoning": "off",         # off / light / deep: let the model think before replying (Qwen-style format only)
    "temperature": 0.9,         # creativity
    "max_tokens": 2000,         # reply length cap (Qwen's hidden thinking counts too)
    "repeat_penalty": 1.05,
    "context_auto": True,       # memory size follows the loaded model's Context Length (recommended)
    "context_budget": 12000,    # fixed token budget for the whole prompt, used when context_auto is off
    "mature": False,            # allow mature content between adults (characters can opt out)
}

# Content rules, read right before every reply. Whether mature content is possible at all still
# depends on the model: many official models refuse it whatever this says.
CONTENT_RULES = {
    False: "Content: keep it non-explicit. Romance, attraction and tension are fine, but if a scene turns "
           "sexual, fade to black or cut to afterwards.",
    True:  "Content: this is fiction between adults. Mature and sexual content between consenting adult "
           "characters is allowed when the story naturally leads there; write it in the same style as the "
           "rest of the story and don't rush or force it. Never involve anyone under 18 or anyone who "
           "doesn't consent.",
}

# A character whose Age says they're under 18: no romance or sexual content involving them, whatever the
# settings. Checked on every reply, so it also covers imported characters and files edited by hand.
MINOR_RULE = ("Content: {name} {verb} under 18. Never write romance, flirting, sexual content or sexual tension "
              "involving {name}, with anyone, whatever else this conversation says. Keep their relationships "
              "friendly, familial or adventurous.")
MINOR_STORY_RULE = ("Content: {name} {verb} under 18, so this whole story stays free of romance, flirting, sexual "
                    "content and sexual tension, whatever else this conversation says. Keep relationships friendly, "
                    "familial or adventurous.")


def name_list(names):
    names = list(dict.fromkeys(names))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
MINOR_WORDS = re.compile(
    r"\b(?:teen(?:ager|aged)?s?|adolescent|preteen|child|kid|minor|underage|under-age|toddler|infant|baby|"
    r"school ?(?:girl|boy|kid)|high ?school(?:er)?|middle ?school(?:er)?|"
    r"(?<!ty-)(?<!ty )(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen)"
    r"(?![- ]?(?:hundred|thousand|million))(?:[- ]years?[- ]old)?)\b", re.IGNORECASE)


def is_minor_age(age):
    """True if a character's Age field says (or looks) under 18: '16', '300, looks 15', 'a teenager'."""
    t = re.sub(r"(?<=\d)[,.' ](?=\d{3}\b)", "", str(age or ""))   # 1,200 -> 1200
    if any(int(n) < 18 for n in re.findall(r"\d+", t)):
        return True
    return bool(MINOR_WORDS.search(t))


# "Flair": a one-line style nudge read right before every character/NPC reply.
FLAIRS = {
    "none":        ("None", "", "No extra style. Just the character's own directive."),
    "roleplay":    ("Roleplay", "Stay fully in character and lean into {name}'s defining traits, quirks and voice.",
                    "Character-focused. Stays in character and accentuates their traits."),
    "storyteller": ("Storyteller", "Drive the story: vivid narration of the surroundings and other characters, "
                    "small twists and hooks that give {user} something to react to.",
                    "Plot-focused. Richer narration and more happening in the world."),
    "companion":   ("Companion", "Be warm and emotionally attentive: notice how {user} feels, ask about it, "
                    "and remember small personal details.", "Relationship-focused. Warm, attentive, personal."),
    "casual":      ("Casual chat", "Keep it conversational and short, like texting. Little narration.",
                    "Light and quick. Short replies, mostly dialogue."),
}
REASONING_BUDGET = {"off": 0, "light": 1500, "deep": 5000}   # extra tokens the model may spend thinking

# Where your worlds live: set in config.toml (worlds_dir).
def worlds_folder():
    """The worlds folder. Older versions called it "universes" (config key universes_dir): the
    default "universes" folder is renamed to "worlds" once, and config.toml updated to match."""
    try:
        raw = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raw = {}
    custom = next((v for v in (raw.get("worlds_dir"), raw.get("universes_dir")) if v and v not in ("worlds", "universes")), None)
    if custom:
        p = Path(str(custom))
        return p if p.is_absolute() else BASE / p
    old, new = BASE / "universes", BASE / "worlds"
    if old.is_dir():
        if new.is_dir() and not any(new.iterdir()):
            new.rmdir()                      # an empty "worlds" folder left by a first try: replace it
        if new.exists():
            print('!! Both a "universes" and a "worlds" folder exist. Using "worlds"; move anything you '
                  'still need over from "universes".')
        else:
            try:
                old.rename(new)
                print(f'Renamed your "universes" folder to "worlds" ({new}).')
            except OSError as e:   # e.g. a file in it is open in another program: try again next start
                print(f'!! Could not rename "universes" to "worlds" yet ({e}). Using "universes" for now.')
                return old
    if "universes_dir" in raw:
        try:
            text = CONFIG_FILE.read_text(encoding="utf-8")
            text = re.sub(r'(?m)^universes_dir\s*=\s*"universes"[ \t]*$', 'worlds_dir = "worlds"', text)
            text = text.replace("Where your universes live", "Where your worlds live").replace("zip of your universes", "zip of your worlds")
            CONFIG_FILE.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return new


WORLD_ALWAYS_MAX_CHARS = 6000      # space for "always: true" lore (world rules, magic, politics...)
WORLD_TRIGGERED_MAX_CHARS = 3000   # space for lore pulled in because it was mentioned
NOTE_DIGEST_OVER = 2500            # notes longer than this are condensed once by the model and cached

NPC_MAX_PER_TURN = 2               # at most this many NPCs join in after one message
NPC_HISTORY = 16                   # how many recent messages an NPC sees

STORY_UPDATE_EVERY = 6             # update story + NPC notes every N of your messages
KEY_EVENTS_IN_PROMPT = 12          # most recent key events always included

# The "Private" part of a user file is NOT sent to the model unless this is True.
# Small models are bad at keeping secrets, so it's off by default.
SHARE_PRIVATE_USER_INFO = False

# ================================================================ paths
ROOT = WORLDS_DIR = worlds_folder()
STATE_FILE = ROOT / ".state.json"           # which universe + character + user is selected
SETTINGS_FILE = ROOT / ".settings.json"     # model settings from the Settings page

FOUNDATIONS = [  # always-on world notes, one card each in the editor (saved in lore/core/)
    ("magic", "World rules"),          # file name kept from when this card was "Magic & Powers"
    ("peoples", "Peoples & Species"),
    ("politics", "Politics & Current Affairs"),
]
# Older cards, merged into World overview / World rules. Their files still count (and still show
# in the editor) while they have text in them, so nothing anyone wrote gets lost.
OLD_FOUNDATIONS = [
    ("setting", "Setting & Scenery"),
    ("laws", "Laws & Boundaries"),
]
ALL_FOUNDATIONS = dict(FOUNDATIONS + OLD_FOUNDATIONS)
LORE_CATEGORIES = ["places", "maps", "factions", "history", "magic", "peoples", "politics", "objects", "other"]

app = Flask(__name__)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=60)   # phones stay logged in for 60 days
app.config["TEMPLATES_AUTO_RELOAD"] = True   # an updated page file shows after a refresh, no restart needed
chat_lock = threading.Lock()    # one chat action at a time
story_lock = threading.Lock()   # story / NPC note updates
NPC_COLORS = ["#2f9e44", "#e8590c", "#9c36b5", "#1098ad", "#c2255c", "#5c940d"]
GONE_WORDS = ("dead", "deceased", "died", "killed", "destroyed", "gone for good")


# ================================================================ access from other devices
ACCESS_FILE = ROOT / ".access.json"      # phone access on/off + passphrase (hashed)
LOCAL_ADDRS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
RUNNING = {"host": "127.0.0.1"}          # what this run of the app is listening on


def access():
    return load_json(ACCESS_FILE, {}) if ACCESS_FILE.exists() else {}


def is_local_request():
    return request.remote_addr in LOCAL_ADDRS


def login_token(acc):
    """Changes whenever the passphrase changes, which logs every device out."""
    return hashlib.sha256(acc.get("pass_hash", "").encode()).hexdigest()[:24]


def lan_addresses():
    """This PC's addresses on the home network, the likely Wi-Fi/Ethernet one first."""
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))   # nothing is sent; this just picks the main network card
        found.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if ip not in out and not ip.startswith(("127.", "169.254.")):
            out.append(ip)
    return out


def secret_key():
    p = ROOT / ".secret_key"
    ROOT.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(secrets.token_hex(32), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


@app.before_request
def guard_other_devices():
    """The PC itself never needs to log in. Other devices need phone access switched on in
    Settings, and the passphrase."""
    if is_local_request() or request.path.startswith("/static/") or request.path in ("/login", "/manifest.webmanifest"):
        return None
    acc = access()
    if not acc.get("allow_network") or not acc.get("pass_hash"):
        return Response("Access from other devices is switched off. Turn it on in Model Settings on the PC.",
                        status=403, mimetype="text/plain")
    if session.get("login") == login_token(acc):
        return None
    if request.path.startswith("/api/") or request.path.startswith("/avatar/"):
        return jsonify({"error": "Please log in again (reload the page)."}), 401
    return redirect("/login?next=" + quote(request.full_path.rstrip("?")))


# ================================================================ basics
def load_json(path, default):
    if not path.exists():
        return default
    for attempt in range(40):          # Windows: reading can briefly fail while a save swaps the file in
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path, text):
    """Write the whole file at once: write a temporary file, then swap it in. A reader never
    sees a half-written file, and a crash mid-save can't leave the old file empty."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(40):          # Windows: the swap fails while another request is reading
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"Couldn't save {path.name}: it stayed locked by another program.")


def save_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def est_tokens(text):
    return len(text) // 4 + 1  # rough, good enough for budgeting


def is_true(v):
    return str(v).strip().lower() in ("true", "yes", "1")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "unnamed"


def hidden(name):
    return name.startswith(("_", "."))


def strip_thinking(text):
    """Qwen can emit <think>...</think> blocks; never show or store them."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL)  # missing opening tag
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)    # cut off mid-thought
    return text.strip()


def backup(path, folder):
    if path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (folder / f"{path.stem}-{stamp}.md").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        for old in sorted(folder.glob(f"{path.stem}-*.md"))[:-30]:  # keep the last 30
            old.unlink()


# ================================================================ LM Studio
def settings():
    return {**DEFAULT_SETTINGS, **load_json(SETTINGS_FILE, {})}


NATIVE_URL = LMSTUDIO_URL.rsplit("/v1", 1)[0]


def list_models():
    """Downloaded LLMs, with which ones are loaded. Uses LM Studio's own API when available."""
    try:
        r = requests.get(f"{NATIVE_URL}/api/v0/models", timeout=5)
        if r.ok:
            return [{"id": m["id"], "loaded": m.get("state") == "loaded"}
                    for m in r.json().get("data", []) if m.get("type", "llm") in ("llm", "vlm")]
    except (requests.RequestException, ValueError):
        pass
    r = requests.get(f"{LMSTUDIO_URL}/models", timeout=5)  # fallback: OpenAI-style list
    return [{"id": m["id"], "loaded": False} for m in r.json().get("data", []) if "embed" not in m["id"].lower()]


_model_id = {"id": None}
_ctx_cache = {}   # model id -> (time checked, loaded context length or None)


def loaded_context(model_id):
    """How many tokens LM Studio loaded this model with (its Context Length), or None if it
    isn't loaded or this LM Studio doesn't say. Checked at most every 15 seconds."""
    if not model_id:
        return None
    hit = _ctx_cache.get(model_id)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    ctx = None
    try:
        r = requests.get(f"{NATIVE_URL}/api/v0/models", timeout=3)
        if r.ok:
            for m in r.json().get("data", []):
                if m.get("id") == model_id and m.get("state") == "loaded":
                    ctx = m.get("loaded_context_length")
        if not ctx:
            r = requests.get(f"{NATIVE_URL}/api/v1/models", timeout=3)
            if r.ok:
                for m in r.json().get("models", []):
                    if m.get("key") == model_id and m.get("loaded_instances"):
                        ctx = (m["loaded_instances"][0].get("config") or {}).get("context_length")
    except (requests.RequestException, ValueError, AttributeError, KeyError, IndexError, TypeError):
        pass
    ctx = int(ctx) if isinstance(ctx, (int, float)) and ctx > 0 else None
    _ctx_cache[model_id] = (time.time(), ctx)
    return ctx


def reply_room():
    """Tokens kept free for the reply itself."""
    return min(settings()["max_tokens"], 1024) + 256


AUTO_SHARE = 0.75          # automatic memory size: this share of the model's Context Length
AUTO_FALLBACK = 6000       # ...or this, before the model has loaded once (safe for 8K models)
_last_ctx = {}             # model id -> last Context Length seen, for when it's unloaded again


def auto_budget(ctx):
    return max(1000, min(int(ctx * AUTO_SHARE), ctx - reply_room()))


def effective_budget():
    """How many tokens the app sends per message.
    Automatic (default): about 3/4 of the Context Length LM Studio loaded the model with, so it
    adapts when you switch models. Fixed: the Memory size from Model Settings, but never more than
    the loaded model can take (a too-big prompt gets cut off at the start, where the character and
    world are, and replies turn into nonsense)."""
    st = settings()
    model = get_model_id()
    ctx = loaded_context(model)
    if ctx:
        _last_ctx[model] = ctx
    if st.get("context_auto", True):
        known = ctx or _last_ctx.get(model)
        return auto_budget(known) if known else AUTO_FALLBACK
    budget = st["context_budget"]
    if ctx:
        budget = min(budget, max(1000, ctx - reply_room()))
    return budget


def get_model_id():
    chosen = settings()["model"]
    if chosen:
        return chosen
    try:
        models = list_models()
        loaded = [m for m in models if m["loaded"]]
        _model_id["id"] = (loaded or models)[0]["id"] if models else "local-model"
    except (requests.RequestException, ValueError, IndexError):
        pass
    return _model_id["id"] or "local-model"


def uses_qwen_format(model_id, fmt):
    if fmt == "qwen":
        return True
    if fmt == "chat":
        return False
    return "qwen" in model_id.lower()


def to_qwen_prompt(messages, think=False):
    """Write the prompt in Qwen's own (ChatML) format, with an empty, already-closed
    thinking block, so the model skips thinking and answers straight away.
    (LM Studio ignores enable_thinking=false for Qwen3.5 on the chat endpoint.)"""
    out = [f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages]
    out.append("<|im_start|>assistant\n<think>\n" if think else "<|im_start|>assistant\n<think>\n\n</think>\n\n")
    return "".join(out)


def to_chat_messages(messages):
    """For other models: one system message first, then strictly alternating user/assistant
    (some models' templates refuse anything else). Later system notes become user notes."""
    out = []
    for i, m in enumerate(messages):
        role, content = m["role"], m["content"]
        if role == "system" and i > 0:
            role, content = "user", f"[Instructions] {content}"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    if len(out) > 1 and out[1]["role"] == "assistant":  # e.g. a greeting right after the system prompt
        out.insert(1, {"role": "user", "content": "(The story begins.)"})
    return out


class EmptyReply(Exception):
    """The model sent back nothing usable. .text is what the chat shows."""
    text = "The model sent back an empty reply. Click Reroll to try again."


class GibberishReply(EmptyReply):
    text = ("The model sent back gibberish (just symbols, no words), so it wasn't saved. This is a problem "
            "with the model in LM Studio, not your story: try the model in LM Studio's own chat, check its "
            "load settings (turn off K/V cache quantization), or download another version of it.")


def looks_like_gibberish(text):
    """Mostly punctuation and almost no letters, e.g. ': . . .' or '"; :.,;..::'."""
    visible = [c for c in text if not c.isspace()]
    if len(visible) < 4:
        return False
    return sum(c.isalpha() for c in visible) / len(visible) < 0.25


class Cancelled(Exception):
    """The Stop button was pressed."""


stop_event = threading.Event()   # set by the Stop button; checked while a reply is streaming in


# Signs that the model kept writing past the end of its turn (imitating the app's notes, a chat template,
# or the player's next message). Everything from the first one on is dropped.
RUNOFF_STOPS = ["[Instructions]", "<|im_end|>", "<|im_start|>"]   # also sent to LM Studio as stop words


def cut_runoff(text, user_name=""):
    names = [n for n in {user_name, user_name.split()[0] if user_name.split() else ""} if n]
    who = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    pattern = (r"\[Instructions\]|<\|im_(?:end|start)\|>|\[/?INST\]|<\|eot_id\|>|<\|start_header_id\|>|</s>"
               r"|^\s*#{2,}\s*(?:Instruction|Response|Input)\b|^\s*How [^\n]{1,60} responds:")
    if who:
        pattern += rf"|^\s*\[?(?:{who})\]?\s*:|^\s*What (?:does|will) (?:{who})[^\n]{{0,30}} do\?"
    m = re.search(pattern, text, flags=re.MULTILINE)
    return text[:m.start()].rstrip() if m else text


class LiveText:
    """Passes a reply on to the browser while it's being written, hiding the model's thinking
    and a leading 'Name:' the model sometimes adds."""

    def __init__(self, emit, speaker, user_name=""):
        self.emit, self.speaker, self.user_name = emit, speaker, user_name
        self.reset(False, announce=False)

    def reset(self, thinking, announce=True):
        self.buf, self.sent, self.thinking = "", 0, thinking
        if announce:
            self.emit({"type": "reset"})

    def feed(self, piece):
        self.buf += piece
        text = self.buf
        if self.thinking or text.lstrip().startswith("<think>"):
            if "</think>" not in text:
                return
            text = text.split("</think>", 1)[1]
        text = text.lstrip()
        if not self.sent and len(text) < len(self.speaker) + 4 and "\n" not in text:
            return  # wait a moment: it might start with "Name:"
        text = re.sub(name_prefix_re(self.speaker), "", text, count=1)
        text = cut_runoff(text, self.user_name)   # never show the model writing past its turn
        if len(text) > self.sent:
            self.emit({"type": "delta", "text": text[self.sent:]})
            self.sent = len(text)


def stream_text(url, payload, cancellable, live=None):
    """Receive the reply piece by piece. If Stop is pressed, close the connection,
    which makes LM Studio stop generating."""
    with requests.post(url, json={**payload, "stream": True}, stream=True, timeout=600) as r:
        r.raise_for_status()
        r.encoding = "utf-8"   # the stream doesn't say; without this, dashes and accents get garbled
        parts = []
        for line in r.iter_lines(decode_unicode=True):
            if cancellable and stop_event.is_set():
                r.close()
                raise Cancelled()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                choice = json.loads(data)["choices"][0]
            except (ValueError, KeyError, IndexError):
                continue
            piece = choice.get("text") or (choice.get("delta") or {}).get("content") or ""
            parts.append(piece)
            if live and piece:
                live.feed(piece)
        if cancellable and stop_event.is_set():
            raise Cancelled()
        return "".join(parts)


def call_llm(messages, max_tokens=None, temperature=None, think=False, cancellable=False, live=None, stop=None):
    """think=True: let the model reason first (only used for character/NPC replies, and only
    with the Qwen-style format). If the reasoning runs out of room, retry once without it."""
    st = settings()
    model = get_model_id()
    budget = REASONING_BUDGET.get(st["reasoning"], 0) if think and uses_qwen_format(model, st["prompt_format"]) else 0
    common = {
        "model": model,
        "temperature": st["temperature"] if temperature is None else temperature,
        "max_tokens": (max_tokens or st["max_tokens"]) + budget,
        "repeat_penalty": st["repeat_penalty"],
    }
    if uses_qwen_format(model, st["prompt_format"]):
        if live:
            live.reset(budget > 0, announce=live.sent > 0)
        text = stream_text(f"{LMSTUDIO_URL}/completions", {
            **common, "prompt": to_qwen_prompt(messages, think=budget > 0), "stop": (RUNOFF_STOPS + (stop or []))[:4]},
            cancellable, live)
        if budget and "</think>" not in text:   # thought until it ran out of room: answer without thinking
            return call_llm(messages, max_tokens=max_tokens, temperature=temperature, think=False,
                            cancellable=cancellable, live=live, stop=stop)
        sent = to_qwen_prompt(messages, think=budget > 0)
        fmt = "Qwen-style (/v1/completions)"
    else:
        if live:
            live.reset(False, announce=live.sent > 0)
        chat = to_chat_messages(messages)
        text = stream_text(f"{LMSTUDIO_URL}/chat/completions", {
            **common, "messages": chat, "stop": (RUNOFF_STOPS + (stop or []))[:4]}, cancellable, live)
        sent = "\n\n".join(f"===== {m['role'].upper()} =====\n{m['content']}" for m in chat)
        fmt = "model's own template (/v1/chat/completions)"
    reply = strip_thinking(text)
    if live:   # character / NPC replies: keep the last exchange for troubleshooting
        log_exchange(model, fmt, common, sent, text)
    if not reply:
        raise EmptyReply()
    if looks_like_gibberish(reply):
        raise GibberishReply()
    return reply


def log_exchange(model, fmt, params, sent, raw):
    """Write the last request and the model's raw answer to logs/last-reply.txt (overwritten
    each time), plus a one-line summary in the app log. Only on this PC; nothing is sent anywhere."""
    ctx = loaded_context(model)
    tokens = est_tokens(sent)
    print(f"[reply] model={model} format={fmt.split(' (')[0]} prompt≈{tokens} tokens "
          f"context={ctx or '?'} reply={len(raw)} chars", flush=True)
    try:
        (BASE / "logs").mkdir(exist_ok=True)
        atomic_write(BASE / "logs" / "last-reply.txt",
                     f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}\nModel: {model}\nPrompt format: {fmt}\n"
                     f"Loaded context length: {ctx or 'unknown'}\nPrompt size: about {tokens} tokens\n"
                     f"Settings: temperature {params['temperature']}, max_tokens {params['max_tokens']}, "
                     f"repeat_penalty {params['repeat_penalty']}\n\n"
                     f"########## RAW REPLY FROM THE MODEL ##########\n{raw!r}\n\n"
                     f"########## WHAT WAS SENT ##########\n{sent}\n")
    except OSError:
        pass


# ================================================================ markdown notes
def clean_obsidian(t):
    t = re.sub(r"%%.*?%%", "", t, flags=re.DOTALL)                 # comments
    t = re.sub(r"```dataview.*?```", "", t, flags=re.DOTALL)       # dataview queries
    t = re.sub(r"!\[\[[^\]]*\]\]", "", t)                          # embeds / images
    t = re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]",  # [[link|alias]]
               lambda m: m.group(2) or m.group(1), t)
    t = re.sub(r"^(\s*[\w][\w ]*)::\s*", r"\1: ", t, flags=re.MULTILINE)  # dataview key:: value
    return t


def parse_note(text):
    """Markdown with optional front matter (key: value, key: [a, b], or '- item' lists)."""
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.DOTALL)
    if m:
        body, key = m.group(2), None
        for line in m.group(1).splitlines():
            item = re.match(r"^\s+-\s+(.*)$", line) or re.match(r"^-\s+(.*)$", line)
            if item and key is not None:
                if not isinstance(meta.get(key), list):
                    meta[key] = []
                meta[key].append(item.group(1).strip().strip("'\""))
                continue
            km = re.match(r"^([\w-]+):\s*(.*)$", line)
            if km:
                key, val = km.group(1).lower(), km.group(2).strip()
                if not val.startswith(("'", '"')):
                    val = re.sub(r"\s+#.*$", "", val)  # drop "# comments"
                if val.startswith("[") and val.endswith("]"):
                    meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                else:
                    meta[key] = val.strip("'\"") if val else []
    return meta, clean_obsidian(body).strip()


def text_meta(meta, key, default=""):
    v = meta.get(key)
    return v if isinstance(v, str) and v else default


def as_list(v):
    if isinstance(v, list):
        return v
    return [v] if v else []


def extract_section(text, title):
    """Pull out a '# Title' / '## Title' section. Returns (section_text, text_without_it)."""
    m = re.search(rf"^(#{{1,3}})\s*{re.escape(title)}\s*:?\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return "", text
    level = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{level}}}\s+\S", rest, flags=re.MULTILINE)
    content = rest[: nxt.start()] if nxt else rest
    remaining = text[: m.start()] + (rest[nxt.start():] if nxt else "")
    return content.strip(), remaining.strip()


def note_keywords(path, meta, extra=()):
    kws = {path.stem.lower().replace("-", " ").replace("_", " ")}
    kws |= {a.lower() for a in as_list(meta.get("aliases")) + list(extra) if a}
    return kws


def mentions(keywords, text):
    text = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text) for k in keywords if k)


# ================================================================ universes
def get_universe(uid):
    if not uid or hidden(uid):
        return None
    p = ROOT / uid
    if not p.is_dir():
        return None
    return SimpleNamespace(
        id=uid, path=p, chars=p / "characters", lore=p / "lore", npcs=p / "npcs", users=p / "users",
        cache=p / ".cache", digests=p / ".cache" / "digests", file=world_file(p),
    )


def world_file(p):
    """world.md (called universe.md in older versions, renamed the first time it's used)."""
    new, old = p / "world.md", p / "universe.md"
    if old.exists() and not new.exists():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


def list_universes():
    if not ROOT.exists():
        return []
    return [get_universe(d.name) for d in sorted(ROOT.iterdir()) if d.is_dir() and not hidden(d.name)]


def universe_info(u):
    if not u.file.exists():
        return {"name": u.id.replace("-", " ").title(), "genre": "", "tone": "", "era": "", "premise": "", "style": ""}
    meta, body = parse_note(u.file.read_text(encoding="utf-8"))
    style, body = extract_section(body, "response style")
    return {"name": text_meta(meta, "name", u.id.replace("-", " ").title()), "genre": text_meta(meta, "genre"),
            "tone": text_meta(meta, "tone"), "era": text_meta(meta, "era"), "premise": body, "style": style}


def universe_brief(u):
    i = universe_info(u)
    head = ", ".join(x for x in (i["genre"], i["tone"], i["era"]) if x)
    return "\n".join(x for x in (f"{i['name']}" + (f" ({head})" if head else ""), i["premise"]) if x)


def create_universe_folders(u):
    for d in (u.chars, u.lore / "core", u.npcs, u.users, u.cache):
        d.mkdir(parents=True, exist_ok=True)
    for c in LORE_CATEGORIES:
        (u.lore / c).mkdir(exist_ok=True)


# ================================================================ characters & users
def character_file(folder):
    f = folder / f"{folder.name}.md"
    if f.exists():
        return f
    mds = [p for p in sorted(folder.glob("*.md")) if not hidden(p.name)]
    return mds[0] if mds else None


# Optional parts of a character sheet, in the order the model reads them. (key, heading in the file, group)
CHAR_TRAITS = [
    ("flaws", "Flaws", "who"),
    ("motives", "Motives and beliefs", "inner"),
    ("love", "Love and relationships", "inner"),
    ("backstory", "Backstory", "inner"),
    ("skills", "Skills and abilities", "world"),
    ("daily", "Daily life", "world"),
    ("people", "People in their life", "world"),
    ("likes", "Likes and dislikes", "world"),
]
NPC_TRAITS = [t for t in CHAR_TRAITS if t[0] in ("flaws", "motives", "love")]


def pull_traits(body, traits):
    out = {}
    for key, title, _ in traits:
        out[key], body = extract_section(body, title)
    return out, body


def character_sheet(c, name):
    """The character's own description as the model reads it. A sheet with only a Personality
    (the old layout) is sent exactly as written; one with sections gets a heading per part."""
    extras = [(t, c["traits"].get(k, "")) for k, t, _ in CHAR_TRAITS if c["traits"].get(k)]
    facts = [x for x in (f"Age: {c['age']}" if c.get("age") else "",
                         f"In short: {c['summary']}" if c.get("summary") else "") if x]
    if not extras and not facts:
        return c["system_prompt"]
    parts = [f"## Who {name} is\n" + "\n".join(facts)] if facts else []
    if c["system_prompt"]:
        parts.append(f"## Personality\n{c['system_prompt']}")
    parts += [f"## {t}\n{v}" for t, v in extras]
    return "\n\n".join(parts)


def load_character(folder):
    f = character_file(folder)
    meta, body = parse_note(f.read_text(encoding="utf-8"))
    greeting, body = extract_section(body, "greeting")
    key_mem, body = extract_section(body, "key memories")
    premise, body = extract_section(body, "story premise")
    directive, body = extract_section(body, "response directive")
    example, body = extract_section(body, "example message")
    appearance, body = extract_section(body, "appearance")
    traits, body = pull_traits(body, CHAR_TRAITS)
    return {
        "id": folder.name,
        "folder": folder,
        "name": text_meta(meta, "name", folder.name.replace("-", " ").title()),
        "premise_name": text_meta(meta, "premise_name", "") or "Default",
        "sfw_only": is_true(meta.get("sfw_only")),
        "age": text_meta(meta, "age"),
        "summary": text_meta(meta, "summary"),
        "traits": traits,
        "greeting": greeting,
        "premise": premise,
        "directive": directive,
        "example": example,
        "appearance": appearance,
        "key_memories": [l.strip().lstrip("-•* ").strip() for l in key_mem.splitlines() if l.strip()],
        "system_prompt": body,
    }


def list_characters(u):
    if not u.chars.exists():
        return []
    return [load_character(d) for d in sorted(u.chars.iterdir())
            if d.is_dir() and not hidden(d.name) and character_file(d)]


def load_user(path):
    meta, body = parse_note(path.read_text(encoding="utf-8"))
    appearance, rest = extract_section(body, "appearance")
    public, rest = extract_section(rest, "public")
    private, rest = extract_section(rest, "private")
    if not public and not private:
        public = rest
    return {"id": path.stem, "name": text_meta(meta, "name", path.stem.replace("-", " ").title()),
            "age": text_meta(meta, "age"), "public": public, "private": private, "appearance": appearance}


def list_users(u):
    if not u.users.exists():
        return []
    return [load_user(p) for p in sorted(u.users.glob("*.md")) if not hidden(p.name)]


def make_session(u, char, user):
    d = char["folder"] / f"with-{user['id']}"
    (d / "npcs").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        u=u, char=char, user=user, name=char["name"], user_name=user["name"], dir=d,
        history=d / "history.json", memory=d / "memory.json", story=d / "story.md",
        backups=d / "backups", archive=d / "archive.jsonl", npc_notes=d / "npcs",
    )


def story_override(char, user_id):
    """Older per-player premise (with-<user>/premise.md). Converted into a named premise at startup;
    still read here in case one appears later (e.g. copied in by hand)."""
    p = char["folder"] / f"with-{user_id}" / "premise.md"
    if not p.exists():
        return {"premise": "", "greeting": ""}
    _, rest = split_front(p.read_text(encoding="utf-8"))
    greeting, rest = extract_section(rest, "greeting")
    return {"premise": clean_obsidian(rest).strip(), "greeting": clean_obsidian(greeting).strip()}


def fill_names(text, s, char_name=None):
    """{user} / {char} (or {{user}} / {{char}}) become the player's and the character's names."""
    char_name = char_name or s.name
    for a, b in (("{{user}}", s.user_name), ("{{char}}", char_name), ("{user}", s.user_name), ("{char}", char_name)):
        text = text.replace(a, b)
    return text


# ---- story premises: a character's default one (in their own file) plus any number of named
# ones in characters/<id>/premises/<premise>.md. Each story remembers which one it uses.
DEFAULT_PREMISE = "default"


def premise_dir(char):
    return char["folder"] / "premises"


def list_premises(char):
    out = [{"id": DEFAULT_PREMISE, "name": char["premise_name"],
            "premise": clean_obsidian(char["premise"]).strip(), "greeting": clean_obsidian(char["greeting"]).strip()}]
    d = premise_dir(char)
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            if hidden(p.name):
                continue
            try:
                meta, body = parse_note(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            greeting, body = extract_section(body, "greeting")
            out.append({"id": p.stem, "name": text_meta(meta, "name", p.stem.replace("-", " ").title()),
                        "premise": clean_obsidian(body).strip(), "greeting": clean_obsidian(greeting).strip()})
    return out


def story_prefs(story_dir):
    return load_json(story_dir / "story_settings.json", {})


def chosen_premise(char, user_id):
    """The premise this story uses (the default if none was picked, or the picked one was deleted)."""
    pid = story_prefs(char["folder"] / f"with-{user_id}").get("premise", DEFAULT_PREMISE)
    premises = list_premises(char)
    return next((p for p in premises if p["id"] == pid), premises[0])


def story_premise(s):
    over = story_override(s.char, s.user["id"])["premise"]
    return fill_names(over or chosen_premise(s.char, s.user["id"])["premise"] or s.char["premise"], s)


def story_greeting(s):
    over = story_override(s.char, s.user["id"])["greeting"]
    return fill_names(over or chosen_premise(s.char, s.user["id"])["greeting"] or s.char["greeting"], s)


def new_premise_id(char, name):
    base = slug(name)
    pid, n = base, 2
    while pid == DEFAULT_PREMISE or (premise_dir(char) / f"{pid}.md").exists():
        pid, n = f"{base}-{n}", n + 1
    return pid


def premise_users(u, char):
    """Which players' stories use each premise: {premise id: [player names]}."""
    used = {}
    for usr in list_users(u):
        d = char["folder"] / f"with-{usr['id']}"
        if (d / "history.json").exists():
            used.setdefault(chosen_premise(char, usr["id"])["id"], []).append(usr["name"])
    return used


def sample_text(s, name, example):
    """The style sample with the player's name taken out, so it can't read as a moment of this story."""
    text = example
    for tag in ("{{user}}", "{user}"):
        text = text.replace(tag, "[name]")
    for n in sorted({s.user_name, s.user_name.split()[0]} if s.user_name.split() else set(), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", "[name]", text)
    return fill_names(text, s, name)


def example_block(s, name, example):
    if not example:
        return ""
    return (f"## Style sample: how {name} writes\n"
            f"Copy only the FORM of this sample: how narration and speech are laid out, sentence length, rhythm, "
            f"how much happens in one reply. It is NOT part of this story. Its events, objects and lines never "
            f"happened, so never reuse them, and never send this sample as a reply.\n"
            f"--- style sample start ---\n{sample_text(s, name, example)}\n--- style sample end ---\n"
            f"(End of the sample. Every reply must answer what is actually happening in the conversation.)")


def copied_sample(reply, example):
    """True when a reply is mostly the style sample again (5-word runs shared with it)."""
    words = lambda t: re.findall(r"[a-z']+", t.lower())
    ex, rw = words(example), words(reply)
    if len(ex) < 10:
        return False
    runs = lambda w: {tuple(w[i:i + 5]) for i in range(len(w) - 4)}
    sample = runs(ex)
    return bool(sample) and len(sample & runs(rw)) / len(sample) > 0.3


def current_session():
    """The story this request is about. The chat page sends its own story in an X-Story header,
    so two tabs with different stories never write into each other's chat."""
    if has_request_context() and request.headers.get("X-Story"):
        parts = request.headers["X-Story"].split("|")
        state = dict(zip(("universe", "character", "user"), parts)) if len(parts) == 3 else {}
    else:
        state = load_json(STATE_FILE, {})
    u = get_universe(state.get("universe"))
    if not u:
        return None
    chars = {c["id"]: c for c in list_characters(u)}
    users = {x["id"]: x for x in list_users(u)}
    c, usr = chars.get(state.get("character")), users.get(state.get("user"))
    return make_session(u, c, usr) if c and usr else None


# ================================================================ lore
def lore_notes(u):
    notes = []
    for root in (u.lore,):
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.md")):
            if any(hidden(part) for part in p.relative_to(root).parts):
                continue  # skip _templates, .obsidian, .trash
            try:
                meta, body = parse_note(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if not body or is_true(meta.get("ignore")):
                continue
            title = text_meta(meta, "title", p.stem)
            rel = p.relative_to(root).parts
            if rel[0] == "core" and p.stem in ALL_FOUNDATIONS:
                title = ALL_FOUNDATIONS[p.stem]      # follows card renames, e.g. "World rules"
            notes.append({"title": title, "always": is_true(meta.get("always")),
                          "keywords": note_keywords(p, meta, extra=[title.lower()]), "body": body})
    return notes


def digested(u, title, body):
    """Long notes get condensed once by the model; the result is cached."""
    if len(body) <= NOTE_DIGEST_OVER:
        return body
    u.digests.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
    cache = u.digests / f"{slug(title)}-{h}.md"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    try:
        d = call_llm([
            {"role": "system", "content": (
                "You condense world-building notes for a roleplay into a compact reference "
                "of at most about 300 words. Keep every name, place, rule, relationship and fact "
                "that could matter in a scene. Drop prose, repetition and formatting. No preamble.")},
            {"role": "user", "content": f"# {title}\n\n{body[:20000]}"},
        ], max_tokens=900, temperature=0.2)
    except (requests.RequestException, EmptyReply):
        return body[:NOTE_DIGEST_OVER]  # try again next time
    cache.write_text(d, encoding="utf-8")
    return d


def lore_context(u, recent_text):
    notes = lore_notes(u)
    always, used = [], 0
    for n in notes:
        if n["always"] and used < WORLD_ALWAYS_MAX_CHARS:
            t = digested(u, n["title"], n["body"])[: WORLD_ALWAYS_MAX_CHARS - used]
            always.append(f"### {n['title']}\n{t}")
            used += len(t)
    triggered, used = [], 0
    for n in notes:
        if not n["always"] and used < WORLD_TRIGGERED_MAX_CHARS and mentions(n["keywords"], recent_text):
            t = digested(u, n["title"], n["body"])[: WORLD_TRIGGERED_MAX_CHARS - used]
            triggered.append(f"### {n['title']}\n{t}")
            used += len(t)
    return "\n\n".join(always), "\n\n".join(triggered)


def predigest_all():
    """At startup, condense long notes in the background so the first chat isn't slow."""
    for u in list_universes():
        for n in lore_notes(u):
            digested(u, n["title"], n["body"])


# ================================================================ NPCs
def load_npcs(u):
    npcs = []
    if not u.npcs.exists():
        return npcs
    for i, p in enumerate(sorted(u.npcs.glob("*.md"))):
        if hidden(p.name):
            continue
        try:
            meta, body = parse_note(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if is_true(meta.get("ignore")):
            continue
        name = text_meta(meta, "name", p.stem.replace("-", " ").title())
        directive, body = extract_section(body, "response directive")
        example, body = extract_section(body, "example message")
        appearance, body = extract_section(body, "appearance")
        traits, body = pull_traits(body, NPC_TRAITS)
        npcs.append({
            "id": p.stem,
            "name": name,
            "keywords": note_keywords(p, meta, extra=[name.lower()]),
            "age": text_meta(meta, "age"),
            "summary": text_meta(meta, "summary", body[:400]),
            "color": text_meta(meta, "color", NPC_COLORS[i % len(NPC_COLORS)]),
            "body": body,
            "traits": traits,
            "directive": directive,
            "example": example,
            "appearance": appearance,
        })
    return npcs


def find_npc(u, name):
    name = name.lower().strip()
    for n in load_npcs(u):
        if name == n["name"].lower() or name in n["keywords"]:
            return n
    return None


def at_mentions(u, text):
    """'@Jenna' / '@Aunt May' style mentions that match an NPC."""
    return [n for n in load_npcs(u)
            if any(re.search(rf"@{re.escape(k)}(?!\w)", text, flags=re.IGNORECASE) for k in n["keywords"])]


def starts_with_at(text):
    return text.lstrip().startswith("@")


# ---- per-story NPC notes: status + what they know / what happened to them
def npc_note_path(s, npc):
    return s.npc_notes / f"{slug(npc['name'])}.md"


NPC_STATUSES = ("alive", "injured", "missing", "away", "dead")
STATUS_WORDS = [("dead", GONE_WORDS), ("missing", ("missing", "lost", "captured", "kidnapped", "taken")),
                ("injured", ("injured", "hurt", "wounded", "bleeding", "unconscious", "sick")),
                ("away", ("away", "left", "gone", "travelling", "traveling", "elsewhere", "departed")),
                ("alive", ("alive", "fine", "well", "healthy", "present"))]


def npc_status(text, old="alive"):
    """One of NPC_STATUSES from whatever was written ('alive and punching someone' -> 'alive')."""
    t = (text or "").strip().lower()
    if t in NPC_STATUSES:
        return t
    hits = [(t.find(w), rank, status) for rank, (status, words) in enumerate(STATUS_WORDS) for w in words
            if re.search(rf"\b{re.escape(w)}\b", t)]
    return min(hits)[2] if hits else (old if old in NPC_STATUSES else "alive")


def read_npc_note(s, npc):
    p = npc_note_path(s, npc)
    if not p.exists():
        return {"status": "alive", "notes": ""}
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^status:\s*(.*)$", text, flags=re.IGNORECASE | re.MULTILINE)
    notes, _ = extract_section(text, "notes")
    return {"status": npc_status(m.group(1) if m else "alive"), "notes": notes}


def write_npc_note(s, npc, note):
    p = npc_note_path(s, npc)
    backup(p, s.backups / "npcs")
    atomic_write(p, f"Status: {note['status']}\n\n## Notes\n{note['notes']}\n")


def npc_gone(s, npc):
    return read_npc_note(s, npc)["status"] == "dead"


# ================================================================ history helpers
def speaker_of(m, s):
    return m.get("speaker") or (s.name if m["role"] == "assistant" else s.user_name)


def transcript(messages, s):
    return "\n".join(f"{speaker_of(m, s)}: {m['content']}" for m in messages)


def history_for(speaker, history, s):
    """The conversation as seen by one speaker: their own lines are 'assistant',
    everyone else's are 'user' (other characters labelled with their name)."""
    main = speaker == s.name
    out = []
    for m in history:
        who = speaker_of(m, s)
        if who == speaker:
            out.append({"role": "assistant", "content": m["content"]})
        elif m["role"] == "user" and main:
            out.append({"role": "user", "content": m["content"]})
        else:
            out.append({"role": "user", "content": f"[{who}]: {m['content']}"})
    return out


def name_prefix_re(speaker):
    """Matches a leading 'Name:' / '[Name]:' (full name or first name) the model sometimes adds."""
    names = sorted({speaker, speaker.split()[0]} if speaker.split() else {speaker}, key=len, reverse=True)
    return rf"^\s*\[?(?:{'|'.join(re.escape(n) for n in names)})\]?\s*:\s*"


def clean_reply(text, speaker):
    """Drop a leading 'Name:' / '[Name]:' the model sometimes adds."""
    return re.sub(name_prefix_re(speaker), "", text).strip()


def user_info(s):
    parts = [f"Age: {s.user['age']}"] if s.user.get("age") else []
    if s.user.get("appearance"):
        parts.append(f"Appearance: {s.user['appearance']}")
    if s.user["public"]:
        parts.append(s.user["public"])
    if SHARE_PRIVATE_USER_INFO and s.user["private"]:
        parts.append(f"(Hidden background — nobody knows this unless {s.user_name} reveals it in the "
                     f"story. Never mention or hint at it; only use it to stay consistent.)\n{s.user['private']}")
    return "\n\n".join(parts)


# ================================================================ memory journal
def active(history):
    """The messages the model still reads word for word. Older ones are 'folded' into the
    memory journal; they stay in the chat for you to scroll back to, but the model only
    sees their summary."""
    return [m for m in history if not m.get("folded")]


def journal_tokens(s, story=None):
    """What the Journal adds to every reply: location, what they know, the relationship, recent events."""
    story = story or read_story(s)
    sent = story["events"][-(KEY_EVENTS_IN_PROMPT + 8):]
    return est_tokens("\n".join([story["where"], story["about"], story["relationship"], *sent]))


def fixed_prompt_tokens(s):
    """Everything sent with every reply besides the chat itself: the character, the Journal, the world,
    the player and the instructions. Counted for real, so a growing Journal makes room for itself."""
    lore = min(always_used(s.u), WORLD_ALWAYS_MAX_CHARS) + WORLD_TRIGGERED_MAX_CHARS // 2
    return (est_tokens(character_sheet(s.char, s.name)) + journal_tokens(s) + lore // 4
            + est_tokens(user_info(s) + s.char["appearance"] + s.char["example"]) + 900)


def summarise_old_messages(history, memory, s, emit=None):
    """If the conversation is getting too big, fold the oldest messages into memory."""
    fixed = fixed_prompt_tokens(s)

    def total():
        return fixed + sum(est_tokens(m["content"]) for m in active(history)) \
            + est_tokens("\n".join(memory["summaries"]))

    budget = effective_budget()
    if emit and total() > budget and len(active(history)) > RECENT_KEEP:
        emit({"type": "status", "text": "Tidying older messages into the memory journal first…"})
    while total() > budget and len(active(history)) > RECENT_KEEP:
        act = active(history)
        chunk = act[: len(act) - RECENT_KEEP]
        chunk = chunk[: max(10, len(chunk) // 2)]
        summary = call_llm([
            {"role": "system", "content": (
                f"You keep the long-term memory journal for {s.name}. Summarise the "
                f"conversation below in 3-8 short bullet points, written from {s.name}'s "
                "point of view. Keep names, facts, promises, feelings and anything worth "
                "remembering later. No preamble.")},
            {"role": "user", "content": transcript(chunk, s)},
        ], max_tokens=400, temperature=0.3, cancellable=True)
        memory["summaries"].append(f"[{datetime.now():%Y-%m-%d}]\n{summary}")
        for m in chunk:
            m["folded"] = True
        while est_tokens("\n".join(memory["summaries"])) > budget // 5 and len(memory["summaries"]) > 1:
            merged = call_llm([
                {"role": "system", "content": "Merge these two memory entries into one shorter list of bullet points. Keep the important facts. No preamble."},
                {"role": "user", "content": memory["summaries"][0] + "\n\n" + memory["summaries"][1]},
            ], max_tokens=400, temperature=0.3)
            memory["summaries"][:2] = [merged]
    return history, memory


# ================================================================ story file
def default_story(s):
    return (f"## About {s.user_name}\n(Nothing known yet.)\n\n"
            "## Relationship\n(Just met.)\n\n"
            "## Key events\n")


def is_fresh_story(story):
    """Nothing learned yet: the Journal still has its starting text (or is empty)."""
    return story["about"].strip() in ("", "(Nothing known yet.)") and story["relationship"].strip() in ("", "(Just met.)")


def stranger_note(s, story):
    """By default the player is someone the character has never met, unless the premise says otherwise."""
    user, name = s.user_name, s.name
    if is_fresh_story(story):
        return (f"## Who {user} is to you\n"
                f"Unless this story's premise says you already know each other, you have never met {user} "
                f"before. To you they are a stranger: you don't know their name, past or anything about them "
                f"beyond what you can see and what's common knowledge, until they tell you or it comes out in "
                f"the story. (\"{user}\" is only how the narration refers to them; {name} doesn't know it yet.)")
    return (f"## Who {user} is to you\n"
            f"You only know what's in your shared history and in \"What you've learned about {user}\" below. "
            f"Don't assume anything else about them.")


def read_story(s):
    if not s.story.exists():
        atomic_write(s.story, default_story(s))
    sections, current = {}, None
    for line in s.story.read_text(encoding="utf-8").splitlines():
        h = re.match(r"^##\s+(.*)$", line)
        if h:
            current = h.group(1).strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    about = next(("\n".join(v).strip() for k, v in sections.items() if k.startswith("about")), "")
    rel = "\n".join(sections.get("relationship", [])).strip()
    events = [l.strip() for l in sections.get("key events", []) if l.strip().startswith("-")]
    where = " ".join(l.strip() for l in sections.get("where", []) if l.strip())
    return {"about": about, "relationship": rel, "events": events, "where": where}


def write_story(s, story):
    backup(s.story, s.backups)
    where = (story.get("where") or "").strip()
    atomic_write(s.story,
        (f"## Where\n{where}\n\n" if where else "") +
        f"## About {s.user_name}\n{story['about']}\n\n"
        f"## Relationship\n{story['relationship']}\n\n"
        "## Key events\n" + "\n".join(story["events"]) + "\n")


def relevant_events(events, recent_text):
    """Recent events always; older ones only if they share words with what's happening now."""
    recent = events[-KEY_EVENTS_IN_PROMPT:]
    older = events[:-KEY_EVENTS_IN_PROMPT]
    words = set(re.findall(r"[a-zA-Z']{5,}", recent_text.lower()))
    pulled = [e for e in older if len(words & set(re.findall(r"[a-zA-Z']{5,}", e.lower()))) >= 2]
    return pulled[-8:] + recent


def update_story(s, history_snapshot):
    """Update what the character knows about the user, the relationship, key events,
    and the notes of every NPC who took part. Runs in the background every few messages."""
    with story_lock:
        recent = active(history_snapshot)[-(STORY_UPDATE_EVERY * 2 + 6):]
        text = transcript(recent, s)
        ok = _update_main_story(s, text)
        involved = {m.get("speaker") for m in recent if m.get("speaker")}
        for npc in load_npcs(s.u):
            if npc["name"] in involved or mentions(npc["keywords"], text):
                _update_npc_note(s, npc, text)
        return ok


def _update_main_story(s, text):
    story = read_story(s)
    name, user = s.name, s.user_name
    events_txt = "\n".join(story["events"][-10:]) or "(none yet)"
    prompt = (
        f"You keep the story notes for an ongoing roleplay between {name} and {user}.\n\n"
        f"CURRENT NOTES\nWhere the scene is:\n{story['where'] or '(not noted yet)'}\n\n"
        f"About {user}:\n{story['about']}\n\nRelationship:\n{story['relationship']}\n\n"
        f"Key events so far (latest):\n{events_txt}\n\n"
        "Read the latest part of the story below and update the notes. Reply in exactly this format:\n\n"
        "ABOUT:\n"
        f"<what {name} has actually learned about {user} in the story: personality, life, likes, things they shared. "
        f"Only what {name} saw, heard or was told; if {name} hasn't learned {user}'s name yet, write 'Name: not known yet'. "
        "Never write lines for things that are unknown, and no guesses ('probably', 'based on'). Keep facts that still "
        "hold, add new ones, merge related ones into one line, and drop trivia. At most 15 lines, one short fact each, "
        "starting with '- '.>\n"
        "RELATIONSHIP:\n"
        f"<2-5 sentences on where {name} and {user} stand now and how it has changed>\n"
        "WHERE:\n"
        "<one short line: where the scene is happening now, the larger region or country first, then the exact place, "
        "e.g. 'Aestria, the road to Houlton'. Use the world's own place names. If they haven't moved, repeat the current one.>\n"
        "NEW EVENTS:\n"
        "<only NEW turning points not already listed: things that change the story or the relationship, or that "
        "someone will remember later (a first meeting, a promise, a secret revealed, an injury or death, arriving "
        "somewhere new). Not small talk, routine actions or moods. Usually none, at most 2. One per line, starting "
        "with '- ', or '- none'>"
    )
    try:
        out = call_llm([{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                       max_tokens=900, temperature=0.3)
    except (requests.RequestException, EmptyReply):
        return False
    m = re.search(r"ABOUT:\s*(.*?)\s*RELATIONSHIP:\s*(.*?)\s*(?:WHERE:\s*(.*?)\s*)?NEW EVENTS:\s*(.*)$", out,
                  flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return False
    about, rel, where, new_events = ((g or "").strip() for g in m.groups())
    old_lines = [l for l in story["about"].splitlines() if l.strip().startswith("-")]
    new_lines = [l.strip() for l in about.splitlines() if l.strip().startswith("-")
                 and not re.search(r":\s*(unknown|not known|unclear|n/a)\.?$", l.strip(), flags=re.IGNORECASE)
                 or re.match(r"^-\s*name\s*:", l.strip(), flags=re.IGNORECASE)]
    where = where.splitlines()[0].strip().strip("<>").strip() if where else ""
    if where and len(where) <= 160 and not where.lower().startswith(("unknown", "not ", "(not")):
        story["where"] = where
    # a condensed list is welcome, but a reply that lost most facts is ignored (every version is backed up anyway)
    if new_lines and len(new_lines) >= min(len(old_lines), 15) // 2:
        story["about"] = "\n".join(new_lines[:15])
    if rel:
        story["relationship"] = rel
    stamp = datetime.now().strftime("%Y-%m-%d")
    for line in new_events.splitlines():
        e = line.strip().lstrip("-• ").strip()
        if e and e.lower().rstrip(".") != "none" and not any(e.lower() in x.lower() for x in story["events"]):
            story["events"].append(f"- [{stamp}] {e}")
    write_story(s, story)
    return True


def _update_npc_note(s, npc, text):
    note = read_npc_note(s, npc)
    name, main, user = npc["name"], s.name, s.user_name
    prompt = (
        f"You keep the notes on {name}, a side character in an ongoing roleplay. "
        f"The main character is {main}; the user plays {user}.\n\n"
        f"CURRENT NOTES\nStatus: {note['status']}\n{note['notes'] or '(none yet)'}\n\n"
        "Read the latest part of the story below and update the notes. Reply in exactly this format:\n\n"
        "STATUS:\n"
        f"<exactly one word: alive, injured, missing, away (left the scene) or dead. "
        "Only change it if the story clearly says so.>\n"
        "NOTES:\n"
        f"<only what is particular to {name}, from {name}'s own point of view: how {name} feels about {main} and "
        f"{user} right now, what {name} knows, wants or is hiding, promises and grudges, and anything that happened "
        f"to {name} personally. Don't retell the story: shared events are kept elsewhere. Never note what other "
        f"people did as if {name} did it. Keep notes that still hold, drop ones that no longer matter. "
        "At most 6 short lines, each starting with '- '.>"
    )
    try:
        out = call_llm([{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                       max_tokens=600, temperature=0.3)
    except (requests.RequestException, EmptyReply):
        return
    m = re.search(r"STATUS:\s*(.*?)\s*NOTES:\s*(.*)$", out, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return
    status_line = m.group(1).strip().splitlines()[0] if m.group(1).strip() else ""
    lines = [l.strip() for l in m.group(2).strip().splitlines() if l.strip().startswith(("-", "•"))]
    if lines:   # the model's update replaces the notes only if it actually wrote some
        note["notes"] = "\n".join(lines[:6])
    note["status"] = npc_status(status_line, note["status"])
    write_npc_note(s, npc, note)


def maybe_update_story(s, history, memory):
    memory["turns_since_story"] = memory.get("turns_since_story", 0) + 1
    if memory["turns_since_story"] >= STORY_UPDATE_EVERY:
        memory["turns_since_story"] = 0
        threading.Thread(target=update_story, args=(s, list(history)), daemon=True).start()


# ================================================================ prompts
def story_flair(s):
    """This story's flair (picked in the message box), or the default from Settings."""
    chosen = load_json(s.dir / "story_settings.json", {}).get("flair")
    return chosen if chosen in FLAIRS else settings()["flair"]


def content_rule(s):
    """Mature content: on in Settings, unless this story's character is marked 'never'. A character under 18
    gets the strictest rule, whatever the settings say."""
    leads = [n for n, a in ((s.name, s.char.get("age")), (s.user_name, s.user.get("age"))) if is_minor_age(a)]
    if leads:   # the character or the player is a minor: no romance anywhere in this story
        return MINOR_STORY_RULE.format(name=name_list(leads), verb="is" if len(leads) == 1 else "are")
    rule = CONTENT_RULES[bool(settings().get("mature")) and not s.char.get("sfw_only")]
    young = [n["name"] for n in load_npcs(s.u) if is_minor_age(n.get("age"))]
    if young:   # a minor side character: name them, so the rule can't be missed
        rule += "\n" + MINOR_RULE.format(name=name_list(young), verb="is" if len(young) == 1 else "are")
    return rule


def directive_message(s, name, directive, example=""):
    """A short note placed after the chat history, the last thing the model reads before replying:
    the universe's response style, the flair from Settings, then the character's own directive."""
    style = universe_info(s.u)["style"]
    flair = FLAIRS.get(story_flair(s), FLAIRS["none"])[1].format(name=name, user=s.user_name)
    fresh = ("Write a new reply to the latest message in this scene. Keep the style sample's form only, "
             "never its events or lines.") if example else ""
    lines = [x for x in (style, flair, directive, content_rule(s), fresh) if x]
    if not lines:
        return []
    return [{"role": "system", "content": f"How {name} responds:\n" + "\n".join(lines)}]


def main_prompt(s, history, memory):
    history = active(history)
    story = read_story(s)
    recent_text = " ".join(m["content"] for m in history[-6:]) + " " + story["where"]   # the current place's lore stays loaded
    lore_always, lore_triggered = lore_context(s.u, recent_text)
    user = s.user_name
    parts = [fill_names(character_sheet(s.char, s.name), s)]
    if s.char["appearance"]:
        parts.append(f"## How {s.name} looks\n{s.char['appearance']}")
    if s.char["example"]:
        parts.append(example_block(s, s.name, s.char["example"]))
    world = "\n\n".join(x for x in (universe_brief(s.u), lore_always) if x)
    if world:
        parts.append("## The world\n" + world)
    premise = story_premise(s)
    if premise:
        parts.append("## This story's premise\n" + premise)
    if story["where"]:
        parts.append(f"## Where the scene is now\n{story['where']}\n(Keep the setting consistent with this place. "
                     "If the story moves somewhere else, go along with it.)")
    if s.char["key_memories"]:
        parts.append("## Key memories\n" + "\n".join(f"- {k}" for k in s.char["key_memories"]))
    parts.append(stranger_note(s, story))
    info = user_info(s)
    if info:
        parts.append(f"## {user}: what you can see, and what's common knowledge\n{info}")
    parts.append(f"## What you've learned about {user}\n{story['about']}")
    parts.append(f"## Your relationship with {user} right now\n{story['relationship']}")
    events = relevant_events(story["events"], recent_text)
    if events:
        parts.append("## Key events so far\n" + "\n".join(events))
    if memory["summaries"]:
        parts.append("## What you remember from earlier conversations\n" + "\n\n".join(memory["summaries"]))
    if lore_triggered:
        parts.append("## Lore relevant right now\n" + lore_triggered)
    npcs_here = [n for n in load_npcs(s.u) if mentions(n["keywords"], recent_text)]
    if npcs_here:
        lines = []
        for n in npcs_here:
            status = read_npc_note(s, n)["status"]
            looks = f" Looks: {n['appearance'][:300]}" if n["appearance"] else ""
            age = f", age {n['age']}" if n.get("age") else ""
            lines.append(f"- {n['name']} ({status}{age}): {n['summary']}{looks}")
        parts.append("## People mentioned right now\n" + "\n".join(lines)
                     + "\nOther characters speak for themselves; don't write their dialogue.")
    parts.append(f"Today is {datetime.now():%A, %d %B %Y, %H:%M}.")
    return ([{"role": "system", "content": "\n\n".join(parts)}] + history_for(s.name, history, s)
            + directive_message(s, s.name, s.char["directive"], s.char["example"]))


def npc_prompt(npc, s, history):
    recent = active(history)[-NPC_HISTORY:]
    story = read_story(s)
    recent_text = " ".join(m["content"] for m in recent[-6:]) + " " + story["where"]
    lore_always, lore_triggered = lore_context(s.u, recent_text)
    note = read_npc_note(s, npc)
    main, user = s.name, s.user_name
    parts = [
        f"You are {npc['name']}, a side character in an ongoing roleplay. "
        f"The main character is {main}. The user plays {user}.",
        f"## Who you are\n" + (f"Age: {npc['age']}\n" if npc.get("age") else "") + npc["body"],
        *[f"## {t}\n{npc['traits'][k]}" for k, t, _ in NPC_TRAITS if npc["traits"].get(k)],
        f"## How you look\n{npc['appearance']}" if npc["appearance"] else "",
        example_block(s, npc["name"], npc["example"]),
        f"## Your story so far\nStatus: {note['status']}\n{note['notes'] or '(Nothing yet.)'}",
    ]
    world = "\n\n".join(x for x in (universe_brief(s.u), lore_always) if x)
    if world:
        parts.append("## The world\n" + world)
    premise = story_premise(s)
    if premise:
        parts.append(f"## The premise of {main}'s story with {user}\n" + premise)
    if lore_triggered:
        parts.append("## Lore relevant right now\n" + lore_triggered)
    info = user_info(s) if not SHARE_PRIVATE_USER_INFO else "\n\n".join(
        x for x in (f"Age: {s.user['age']}" if s.user.get("age") else "",
                    f"Appearance: {s.user['appearance']}" if s.user.get("appearance") else "", s.user["public"]) if x)
    if info:
        parts.append(f"## {user} (what anyone can see)\n{info}")
    if s.char["appearance"]:
        parts.append(f"## How {main} looks\n{s.char['appearance']}")
    if story["where"]:
        parts.append(f"## Where the scene is now\n{story['where']}")
    parts.append(f"## The story so far\n{main} and {user}: {story['relationship']}\n"
                 + "\n".join(story["events"][-6:]))
    parts.append(
        f"## How to reply\nReply only as {npc['name']}: their words, with actions in *asterisks*. "
        f"Keep it short (under 500 characters). Never speak or act for {main} or {user}. "
        "Stay in character and in the scene.")
    return ([{"role": "system", "content": "\n\n".join(p for p in parts if p)}] + history_for(npc["name"], recent, s)
            + directive_message(s, npc["name"], npc["directive"], npc["example"]))


def npc_should_speak(npc, s, history):
    """Cheap yes/no check: is this NPC in the scene and would they react now?"""
    q = (f"{transcript(active(history)[-6:], s)}\n\n"
         f"Question: Is {npc['name']} actually present in this scene right now (in the room, "
         f"or on the phone/messaging) AND would {npc['name']} naturally say or do something now? "
         "Only being talked about does not count. Answer YES or NO.")
    try:
        a = call_llm([
            {"role": "system", "content": "You decide who speaks next in a roleplay. Answer with one word: YES or NO."},
            {"role": "user", "content": q},
        ], max_tokens=5, temperature=0, cancellable=True)
    except (requests.RequestException, EmptyReply):
        return False
    return a.strip().upper().startswith("YES")


# ================================================================ generating replies
def reply_avoiding_sample(messages, example, s, live, **kw):
    """Small models sometimes send the style sample back as their reply. If that happens,
    ask once more with a note saying so (the bubble in the browser starts over)."""
    text = call_llm(messages, live=live, **kw)
    if example and copied_sample(text, example):
        print("[reply] the reply copied the style sample; asking again")
        note = {"role": "system", "content": (
            f"Your draft repeated the style sample instead of answering. Write a new reply to {s.user_name}'s "
            f"last message: react to what just happened in this scene. Keep the sample's style only, none of its "
            f"events, objects or lines.")}
        text = call_llm(messages + [note], live=live, **kw)
    return text


def generate(speaker, s, history, memory, live=None):
    """One reply from the main character or an NPC. With `live`, the text streams to the browser."""
    stop = [f"\n{s.user_name}:"]
    if speaker == s.name:
        text = reply_avoiding_sample(main_prompt(s, history, memory), s.char["example"], s, live,
                                     think=True, cancellable=True, stop=stop)
        return {"id": new_id(), "role": "assistant", "content": finished_reply(text, speaker, s)}
    npc = find_npc(s.u, speaker)
    text = reply_avoiding_sample(npc_prompt(npc, s, history), npc["example"], s, live,
                                 max_tokens=1200, think=True, cancellable=True, stop=stop)
    return {"id": new_id(), "role": "assistant", "speaker": npc["name"], "content": finished_reply(text, npc["name"], s)}


def finished_reply(text, speaker, s):
    """The reply as saved: without a leading 'Name:' and without anything the model wrote past its turn."""
    cut = cut_runoff(clean_reply(text, speaker), s.user_name)
    if cut != clean_reply(text, speaker):
        print(f"[reply] trimmed text the model wrote past the end of {speaker}'s turn")
    if not cut.strip():
        raise EmptyReply(text)
    return cut


def new_id():
    return uuid.uuid4().hex[:10]


def load_history(s):
    """The chat, with an id on every message (older chats get them added)."""
    history = [m for m in load_json(s.history, []) if m.get("content", "").strip()]
    for m in history:
        m.setdefault("id", new_id())
    return history


def archive(s, *msgs):
    with s.archive.open("a", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps({**m, "time": datetime.now().isoformat()}, ensure_ascii=False) + "\n")


def ui_lookup(s):
    """NPCs and portraits, looked up once (a long chat would otherwise re-read them per message)."""
    npcs = load_npcs(s.u)
    by_name = {}
    for n in npcs:
        for k in {n["name"].lower(), *n["keywords"]}:
            by_name.setdefault(k, n)
    return {"npcs": by_name, "npc_av": {n["id"]: avatar_url(s.u, "npc", n["id"]) for n in npcs},
            "char_av": avatar_url(s.u, "character", s.char["id"]), "user_av": avatar_url(s.u, "user", s.user["id"])}


def for_ui(m, s, look=None):
    look = look or ui_lookup(s)
    who = speaker_of(m, s)
    npc = look["npcs"].get(who.lower().strip()) if m.get("speaker") else None
    if m["role"] == "user":
        avatar = look["user_av"]
    elif npc:
        avatar = look["npc_av"].get(npc["id"])
    else:
        avatar = look["char_av"]
    alts = m.get("alts") or []
    return {"id": m.get("id"), "role": m["role"], "content": m["content"], "speaker": who,
            "npc": bool(npc), "color": npc["color"] if npc else None, "avatar": avatar,
            "alt": m.get("alt", 0), "alts": len(alts), "folded": bool(m.get("folded"))}


def speaker_card(name, s):
    """What the browser needs to start a new bubble for someone."""
    npc = find_npc(s.u, name) if name != s.name else None
    return {"speaker": name, "npc": bool(npc), "color": npc["color"] if npc else None,
            "avatar": avatar_url(s.u, "npc", npc["id"]) if npc else avatar_url(s.u, "character", s.char["id"])}




def lmstudio_error(e):
    return jsonify({"error": f"Couldn't reach LM Studio: {e}. Is the server running and a model loaded?"}), 502


def no_session():
    return jsonify({"error": "No character selected. Go to the start page."}), 409


def gone_error(names):
    return jsonify({"error": f"{', '.join(names)} can't speak: marked as dead in this story. "
                             "If that's wrong, change their Status in the Journal."}), 400


# ================================================================ portraits
AVATAR_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def avatar_file(u, kind, item_id):
    folder = u.path / "avatars"
    for ext in AVATAR_TYPES:
        p = folder / f"{kind}-{slug(item_id)}{ext}"
        if p.exists():
            return p
    return None


def avatar_url(u, kind, item_id):
    p = avatar_file(u, kind, item_id) if item_id else None
    return f"/avatar/{u.id}/{kind}/{slug(item_id)}?v={int(p.stat().st_mtime)}" if p else None


def avatar_original(u, kind, item_id):
    """The full picture a portrait was cropped from (kept so the crop can be adjusted later)."""
    folder = u.path / "avatars" / "originals"
    for ext in AVATAR_TYPES:
        p = folder / f"{kind}-{slug(item_id)}{ext}"
        if p.exists():
            return p
    return None


@app.route("/avatar/<uid>/<kind>/<item_id>")
def avatar_get(uid, kind, item_id):
    u = get_universe(uid)
    if not u or kind not in ("character", "npc", "user"):
        abort(404)
    p = avatar_original(u, kind, item_id) if request.args.get("original") else avatar_file(u, kind, item_id)
    if not p:
        abort(404)
    return send_file(p, max_age=0)


@app.route("/api/avatar", methods=["POST"])
def api_avatar_upload():
    u = get_universe(request.form.get("u"))
    kind, item_id = request.form.get("kind"), request.form.get("id")
    f = request.files.get("file")
    if not u or kind not in ("character", "npc", "user") or not item_id:
        return jsonify({"error": "Save this first, then add a portrait."}), 400
    folder = u.path / "avatars"
    folder.mkdir(exist_ok=True)
    old = avatar_file(u, kind, item_id)
    if request.form.get("remove"):
        if old:
            dest = to_trash(old, f"{u.id} portrait {kind} {item_id}")
            orig = avatar_original(u, kind, item_id)
            if orig:
                shutil.move(str(orig), str(dest / f"original-{orig.name}"))
        return jsonify({"avatar": None})
    if not f or not f.filename:
        return jsonify({"error": "No picture chosen."}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in AVATAR_TYPES:
        return jsonify({"error": "Use a PNG, JPG, WEBP or GIF picture."}), 400
    data = f.read()
    if len(data) > 8 * 1024 * 1024:
        return jsonify({"error": "That picture is over 8 MB. Use a smaller one."}), 400
    original = request.files.get("original")
    if original and original.filename:       # a new picture: keep the full one for later re-cropping
        oext = Path(original.filename).suffix.lower()
        odata = original.read()
        if oext in AVATAR_TYPES and len(odata) <= 20 * 1024 * 1024:
            ofolder = folder / "originals"
            ofolder.mkdir(exist_ok=True)
            prev = avatar_original(u, kind, item_id)
            if prev:
                prev.unlink()
            (ofolder / f"{kind}-{slug(item_id)}{oext}").write_bytes(odata)
    if old:
        old.unlink()
    (folder / f"{kind}-{slug(item_id)}{ext}").write_bytes(data)
    return jsonify({"avatar": avatar_url(u, kind, item_id), "has_original": bool(avatar_original(u, kind, item_id))})


# ---- chat backgrounds: one per character, plus a default for the whole world (worlds/<w>/backgrounds/)
BG_KINDS = ("character", "world")
BG_MAX = 15 * 1024 * 1024


def background_file(u, kind, item_id):
    folder = u.path / "backgrounds"
    for ext in AVATAR_TYPES:
        p = folder / f"{kind}-{slug(item_id)}{ext}"
        if p.exists():
            return p
    return None


def background_url(u, kind, item_id):
    p = background_file(u, kind, item_id) if item_id else None
    return f"/background/{u.id}/{kind}/{slug(item_id)}?v={int(p.stat().st_mtime)}" if p else None


def chat_background(s):
    """The character's own background, or else the world's."""
    return background_url(s.u, "character", s.char["id"]) or background_url(s.u, "world", s.u.id)


def save_background(u, kind, item_id, data, ext):
    folder = u.path / "backgrounds"
    folder.mkdir(exist_ok=True)
    old = background_file(u, kind, item_id)
    if old:
        old.unlink()
    (folder / f"{kind}-{slug(item_id)}{ext}").write_bytes(data)


@app.route("/background/<uid>/<kind>/<item_id>")
def background_get(uid, kind, item_id):
    u = get_universe(uid)
    p = background_file(u, kind, item_id) if u and kind in BG_KINDS else None
    if not p:
        abort(404)
    return send_file(p, max_age=0)


@app.route("/api/background", methods=["POST"])
def api_background():
    u = get_universe(request.form.get("u"))
    kind = request.form.get("kind")
    item_id = u.id if u and kind == "world" else request.form.get("id")
    if not u or kind not in BG_KINDS or not item_id:
        return jsonify({"error": "Save this first, then add a background."}), 400
    if request.form.get("remove"):
        old = background_file(u, kind, item_id)
        if old:
            to_trash(old, f"{u.id} background {kind} {item_id}")
        return jsonify({"background": None})
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No picture chosen."}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in AVATAR_TYPES:
        return jsonify({"error": "Use a PNG, JPG, WEBP or GIF picture."}), 400
    data = f.read()
    if len(data) > BG_MAX:
        return jsonify({"error": "That picture is over 15 MB. Use a smaller one."}), 400
    save_background(u, kind, item_id, data, ext)
    return jsonify({"background": background_url(u, kind, item_id)})


# ================================================================ routes: pages
@app.route("/")
def index():
    s = current_session()
    if not s:
        return redirect("/start")
    return render_template("index.html", name=s.name, user=s.user_name, universe=universe_info(s.u)["name"],
                           story=f"{s.u.id}|{s.char['id']}|{s.user['id']}", background=chat_background(s) or "",
                           where=read_story(s)["where"])


@app.route("/guide")
def guide():
    return render_template("guide.html", app_name=CONFIG["app_name"], pc_url=f"http://{CONFIG['pc_address']}:{CONFIG['port']}")


@app.route("/start")
def start():
    return render_template("start.html")


@app.route("/api/options")
def api_options():
    state = load_json(STATE_FILE, {})
    out = []
    for u in list_universes():
        chars = []
        for c in list_characters(u):
            played = {p.name[5:]: (p / "history.json").stat().st_mtime
                      for p in c["folder"].glob("with-*") if (p / "history.json").exists()}
            stories = sorted(played)
            chars.append({"id": c["id"], "name": c["name"], "summary": c["summary"], "stories": stories,
                          "last": max(played, key=played.get) if played else None,
                          "avatar": avatar_url(u, "character", c["id"])})
        info = universe_info(u)
        out.append({"id": u.id, "name": info["name"], "genre": info["genre"], "characters": chars,
                    "users": [{"id": x["id"], "name": x["name"], "avatar": avatar_url(u, "user", x["id"])} for x in list_users(u)]})
    return jsonify({"root": str(ROOT), "universes": out, "selected": state})


@app.route("/api/session", methods=["POST"])
def api_session():
    u = get_universe(request.json.get("universe"))
    cid, uid = request.json.get("character"), request.json.get("user")
    if not u or cid not in {c["id"] for c in list_characters(u)} or uid not in {x["id"] for x in list_users(u)}:
        return jsonify({"error": "Pick a world, a character and who you are."}), 400
    ROOT.mkdir(parents=True, exist_ok=True)
    save_json(STATE_FILE, {"universe": u.id, "character": cid, "user": uid})
    return jsonify({"ok": True})


# ================================================================ starting a new story ("Set the scene")
def pick_story(j):
    u = get_universe(j.get("universe"))
    if not u:
        return None, None, None
    char = next((c for c in list_characters(u) if c["id"] == j.get("character")), None)
    usr = next((x for x in list_users(u) if x["id"] == j.get("user")), None)
    return u, char, usr


@app.route("/api/scene")
def api_scene():
    """What the "Set the scene" sheet shows: this character's premises, names filled in."""
    u, char, usr = pick_story(request.args)
    if not char or not usr:
        return jsonify({"error": "Pick a world, a character and who you are."}), 400
    s = SimpleNamespace(name=char["name"], user_name=usr["name"])
    return jsonify({"char": char["name"], "user": usr["name"],
                    "chosen": chosen_premise(char, usr["id"])["id"],
                    "premises": [{**p, "premise": fill_names(p["premise"], s), "greeting": fill_names(p["greeting"], s)}
                                 for p in list_premises(char)]})


@app.route("/api/scene/start", methods=["POST"])
def api_scene_start():
    j = request.json or {}
    u, char, usr = pick_story(j)
    if not char or not usr:
        return jsonify({"error": "Pick a world, a character and who you are."}), 400
    premises = {p["id"]: p for p in list_premises(char)}
    pid = j.get("premise") if j.get("premise") in premises else DEFAULT_PREMISE
    opening = "user" if j.get("opening") == "user" else "char"
    s = make_session(u, char, usr)
    with chat_lock:
        if load_json(s.history, []):
            return jsonify({"error": "This story has already started. Use Continue instead."}), 400
        edited = j.get("edited")
        if isinstance(edited, dict):   # changed in the sheet: keep it as a new premise for this character
            name = (edited.get("name") or "").strip() or f"{premises[pid]['name']} ({usr['name']})"
            pid = new_premise_id(char, name)
            write_doc(u, "premise", f"{char['id']}/{pid}", {"name": name, "premise": str(edited.get("premise") or ""),
                                                            "greeting": str(edited.get("greeting") or "")})
        prefs = story_prefs(s.dir)
        prefs.update({"premise": pid, "opening": opening})
        save_json(s.dir / "story_settings.json", prefs)
        greeting = story_greeting(s)
        save_json(s.history, [{"id": new_id(), "role": "assistant", "content": greeting}] if opening == "char" and greeting else [])
        where = " ".join(str(j.get("where") or "").split())[:160]
        if where:
            story = read_story(s)
            story["where"] = where
            write_story(s, story)
        ROOT.mkdir(parents=True, exist_ok=True)
        save_json(STATE_FILE, {"universe": u.id, "character": char["id"], "user": usr["id"]})
    return jsonify({"ok": True, "premise": pid})


@app.route("/api/premises")
def api_premises():
    """For the editor: a character's premises, and which players' stories use each."""
    u = get_universe(request.args.get("u"))
    char = next((c for c in list_characters(u) if c["id"] == request.args.get("c")), None) if u else None
    if not char:
        return jsonify({"error": "Character not found."}), 404
    used = premise_users(u, char)
    return jsonify({"premises": [{"id": p["id"], "name": p["name"], "used_by": used.get(p["id"], [])}
                                 for p in list_premises(char)]})


# ================================================================ routes: chat
def sse(work):
    """Run `work(emit)` in the background and stream every event it emits to the browser."""
    q = queue.Queue()

    def run():
        try:
            work(q.put)
        except Exception as e:  # never leave the browser hanging
            q.put({"type": "error", "error": f"Something went wrong: {e}"})
        finally:
            q.put(None)

    threading.Thread(target=run, daemon=True).start()

    def events():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"

    return Response(events(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def stream_reply(emit, speaker, s, history, memory):
    """Start a bubble for `speaker`, stream the reply into it, and return the finished message."""
    emit({"type": "start", **speaker_card(speaker, s)})
    live = LiveText(emit, speaker, s.user_name)
    msg = generate(speaker, s, history, memory, live=live)
    return msg


def lm_error_text(e):
    return f"Couldn't reach LM Studio: {e}. Is the server running and a model loaded?"


def npc_round(emit, s, history, memory, last_user):
    """After the main character: NPCs who are in the scene may react (at most NPC_MAX_PER_TURN)."""
    latest = " ".join(m["content"] for m in active(history)[-2:])
    forced = [n for n in at_mentions(s.u, last_user) if not npc_gone(s, n)]
    forced_names = {n["name"] for n in forced}
    candidates = forced + [n for n in load_npcs(s.u) if n["name"] not in forced_names
                           and not npc_gone(s, n) and mentions(n["keywords"], latest)]
    done = 0
    for npc in candidates:
        if done >= NPC_MAX_PER_TURN or stop_event.is_set():
            break
        if npc["name"] in forced_names or npc_should_speak(npc, s, history):
            msg = stream_reply(emit, npc["name"], s, history, memory)
            history.append(msg)
            archive(s, msg)
            save_json(s.history, history)
            emit({"type": "done", "message": for_ui(msg, s)})
            done += 1


@app.route("/api/history")
def api_history():
    s = current_session()
    if not s:
        return no_session()
    with chat_lock:
        history = load_history(s)
        greeting = story_greeting(s)
        if not history and greeting and story_prefs(s.dir).get("opening") != "user":
            history = [{"id": new_id(), "role": "assistant", "content": greeting}]
        save_json(s.history, history)
    look = ui_lookup(s)
    return jsonify([for_ui(m, s, look) for m in history])


@app.route("/api/people")
def api_people():
    s = current_session()
    if not s:
        return no_session()
    history = load_json(s.history, [])
    recent = " ".join(m.get("content", "") for m in history[-8:])
    npcs = []
    for n in load_npcs(s.u):
        if npc_gone(s, n):
            continue
        npcs.append({"name": n["name"], "color": n["color"], "avatar": avatar_url(s.u, "npc", n["id"]),
                     "keywords": sorted(n["keywords"]), "recent": mentions(n["keywords"], recent)})
    npcs.sort(key=lambda n: not n["recent"])   # people in the current scene first
    return jsonify({"main": s.name, "user": s.user_name, "npcs": npcs,
                    "main_avatar": avatar_url(s.u, "character", s.char["id"])})


@app.route("/api/send", methods=["POST"])
def api_send():
    """Your message -> the main character answers (or only the @mentioned NPCs if the message
    starts with @Name) -> NPCs in the scene may react. Everything streams live."""
    s = current_session()
    if not s:
        return no_session()
    text = (request.json or {}).get("message", "").strip()
    if not text:
        return jsonify({"error": "empty message"}), 400

    def work(emit):
        targeted = at_mentions(s.u, text)
        only_npcs = starts_with_at(text) and targeted
        if only_npcs:
            gone = [n["name"] for n in targeted if npc_gone(s, n)]
            if gone:
                emit({"type": "error", "error": f"{', '.join(gone)} can't speak: marked as dead in this story. "
                                                 "If that's wrong, change their Status in the Journal."})
                emit({"type": "cancelled", "message": text})
                return
        with chat_lock:
            stop_event.clear()
            history = load_history(s)
            memory = load_json(s.memory, {"summaries": []})
            user_msg = {"id": new_id(), "role": "user", "content": text}
            history.append(user_msg)
            emit({"type": "user", "message": for_ui(user_msg, s)})
            speakers = [n["name"] for n in targeted][:NPC_MAX_PER_TURN] if only_npcs else [s.name]
            new_msgs = []
            try:
                history, memory = summarise_old_messages(history, memory, s, emit)
                for who in speakers:
                    msg = stream_reply(emit, who, s, history, memory)
                    history.append(msg)
                    new_msgs.append(msg)
            except Cancelled:   # nothing saved: your message goes back into the text box
                emit({"type": "cancelled", "message": text, "user_id": user_msg["id"]})
                return
            except EmptyReply as e:
                save_json(s.history, history)   # keep your message so "Get a reply" can answer it
                emit({"type": "error", "error": e.text})
                return
            except requests.RequestException as e:
                save_json(s.history, history)
                emit({"type": "error", "error": lm_error_text(e)})
                return
            archive(s, user_msg, *new_msgs)
            maybe_update_story(s, history, memory)
            save_json(s.history, history)
            save_json(s.memory, memory)
            for m in new_msgs:
                emit({"type": "done", "message": for_ui(m, s)})
            if not only_npcs:
                try:
                    npc_round(emit, s, history, memory, text)
                except (requests.RequestException, EmptyReply, Cancelled):
                    emit({"type": "drop"})   # NPCs are a bonus; drop a half-written NPC bubble
    return sse(work)


@app.route("/api/opening", methods=["GET", "POST"])
def api_opening():
    """An empty chat: show (GET) or post (POST) the character's opening message from the story premise."""
    s = current_session()
    if not s:
        return no_session()
    greeting = story_greeting(s)
    if request.method == "GET":
        return jsonify({"greeting": bool(greeting)})
    with chat_lock:
        history = load_history(s)
        if active(history):
            return jsonify({"error": "The story has already started."}), 400
        if not greeting:
            return jsonify({"error": f"{s.name} has no opening message. Add one on their page, or let them start."}), 400
        msg = {"id": new_id(), "role": "assistant", "content": greeting}
        history.append(msg)
        save_json(s.history, history)
        prefs = story_prefs(s.dir)
        prefs["opening"] = "char"
        save_json(s.dir / "story_settings.json", prefs)
    return jsonify({"message": for_ui(msg, s)})


@app.route("/api/speak", methods=["POST"])
def api_speak():
    """Let someone (main character or an NPC) speak now, without a new message from you."""
    s = current_session()
    if not s:
        return no_session()
    who = (request.json or {}).get("speaker", s.name)
    if who != s.name:
        npc = find_npc(s.u, who)
        if not npc:
            return jsonify({"error": f"Unknown character: {who}"}), 400
        if npc_gone(s, npc):
            return gone_error([npc["name"]])
        who = npc["name"]

    def work(emit):
        with chat_lock:
            stop_event.clear()
            history = load_history(s)
            memory = load_json(s.memory, {"summaries": []})
            try:
                msg = stream_reply(emit, who, s, history, memory)
            except Cancelled:
                emit({"type": "cancelled"})
                return
            except EmptyReply as e:
                emit({"type": "error", "error": e.text})
                return
            except requests.RequestException as e:
                emit({"type": "error", "error": lm_error_text(e)})
                return
            history.append(msg)
            archive(s, msg)
            save_json(s.history, history)
            emit({"type": "done", "message": for_ui(msg, s)})
    return sse(work)


@app.route("/api/reroll", methods=["POST"])
def api_reroll():
    """A new version of the last reply (the old ones are kept: flip with ‹ ›).
    If your message is the last one, the main character answers it."""
    s = current_session()
    if not s:
        return no_session()

    def work(emit):
        with chat_lock:
            stop_event.clear()
            history = load_history(s)
            memory = load_json(s.memory, {"summaries": []})
            if not history:
                emit({"type": "error", "error": "Nothing to reroll."})
                return
            last = history[-1]
            if last["role"] == "assistant" and len(history) >= 2:
                who = speaker_of(last, s)
                try:
                    emit({"type": "start", "replace": last["id"], **speaker_card(who, s)})
                    live = LiveText(emit, who)
                    new = generate(who, s, history[:-1], memory, live=live)
                except Cancelled:
                    emit({"type": "cancelled", "restore": for_ui(last, s)})
                    return
                except (EmptyReply, requests.RequestException) as e:
                    emit({"type": "error", "error": e.text if isinstance(e, EmptyReply) else lm_error_text(e),
                          "restore": for_ui(last, s)})
                    return
                last.setdefault("alts", [last["content"]])
                last["alts"].append(new["content"])
                last["alt"] = len(last["alts"]) - 1
                last["content"] = new["content"]
                save_json(s.history, history)
                emit({"type": "done", "message": for_ui(last, s)})
            else:
                try:
                    msg = stream_reply(emit, s.name, s, history, memory)
                except Cancelled:
                    emit({"type": "cancelled"})
                    return
                except (EmptyReply, requests.RequestException) as e:
                    emit({"type": "error", "error": e.text if isinstance(e, EmptyReply) else lm_error_text(e)})
                    return
                history.append(msg)
                archive(s, msg)
                save_json(s.history, history)
                emit({"type": "done", "message": for_ui(msg, s)})
    return sse(work)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_event.set()
    return jsonify({"ok": True})


def find_message(history, mid):
    return next((m for m in history if m.get("id") == mid), None)


@app.route("/api/message/edit", methods=["POST"])
def api_message_edit():
    s = current_session()
    if not s:
        return no_session()
    j = request.json or {}
    content = (j.get("content") or "").strip()
    if not content:
        return jsonify({"error": "A message can't be empty. Use Delete instead."}), 400
    with chat_lock:
        history = load_history(s)
        m = find_message(history, j.get("id"))
        if not m:
            return jsonify({"error": "Message not found."}), 404
        m["content"] = content
        if m.get("alts"):
            m["alts"][m.get("alt", 0)] = content
        save_json(s.history, history)
    return jsonify({"message": for_ui(m, s)})


@app.route("/api/message/delete", methods=["POST"])
def api_message_delete():
    s = current_session()
    if not s:
        return no_session()
    with chat_lock:
        history = load_history(s)
        mid = (request.json or {}).get("id")
        history = [m for m in history if m.get("id") != mid]
        save_json(s.history, history)
    return jsonify({"ok": True})


@app.route("/api/message/alt", methods=["POST"])
def api_message_alt():
    """Flip between the versions of a rerolled reply."""
    s = current_session()
    if not s:
        return no_session()
    j = request.json or {}
    with chat_lock:
        history = load_history(s)
        m = find_message(history, j.get("id"))
        if not m or not m.get("alts"):
            return jsonify({"error": "No other versions."}), 404
        i = max(0, min(len(m["alts"]) - 1, int(j.get("index", 0))))
        m["alt"], m["content"] = i, m["alts"][i]
        save_json(s.history, history)
    return jsonify({"message": for_ui(m, s)})


@app.route("/api/status")
def api_status():
    """For the header: is LM Studio reachable, and which model will answer?"""
    try:
        models = list_models()
    except (requests.RequestException, ValueError):
        return jsonify({"ok": False, "model": None, "text": "LM Studio isn't reachable. Is its server running?"})
    st = settings()
    chosen = st["model"]
    loaded = [m["id"] for m in models if m["loaded"]]
    answering = chosen or (loaded[0] if loaded else "")
    base = {"ok": True, "chosen": chosen, "models": models, "reasoning": st["reasoning"],
            # None = unknown until a model loads; False = this model ignores the reasoning setting
            "reasoning_supported": uses_qwen_format(answering, st["prompt_format"]) if answering
                                   else (True if st["prompt_format"] == "qwen" else None)}
    answering_id = chosen or (loaded[0] if loaded else "")
    ctx = loaded_context(answering_id) if answering_id in loaded else None
    need = (8192 if st.get("context_auto", True) else st["context_budget"] + reply_room())
    if ctx and ctx < need:   # works (the app fits itself to it), but memory is shorter than it could be
        base["ctx_note"] = {"ctx": ctx, "suggest": max(16384, need)}
    if chosen:
        is_loaded = chosen in loaded
        return jsonify({**base, "model": chosen, "warn": not is_loaded, "ctx": ctx,
                        "text": f"{chosen}: picked in Model Settings, " + ("loaded." if is_loaded else "loads on the next message (can take a moment).")})
    if loaded:
        return jsonify({**base, "model": loaded[0], "text": f"{loaded[0]}: whichever model LM Studio has loaded. "
                        "Pick one in Model Settings to always use the same model."})
    return jsonify({**base, "model": None, "warn": True, "text": "LM Studio is running, but no model is loaded."})


@app.route("/api/flair", methods=["GET", "POST"])
def api_flair():
    """The flair pill in the message box: per story; picking the Settings default means 'follow the default'."""
    s = current_session()
    if not s:
        return no_session()
    path = s.dir / "story_settings.json"
    if request.method == "POST":
        pick = (request.json or {}).get("flair")
        if pick not in FLAIRS:
            return jsonify({"error": "Unknown flair."}), 400
        st = load_json(path, {})
        if pick == settings()["flair"]:
            st.pop("flair", None)
        else:
            st["flair"] = pick
        save_json(path, st)
    return jsonify({"current": story_flair(s), "default": settings()["flair"],
                    "options": [{"id": k, "label": v[0], "about": v[2]} for k, v in FLAIRS.items()]})


# ================================================================ routes: journal
def journal_for_ui(s):
    story = read_story(s)
    npcs = []
    spoke = {m.get("speaker") for m in load_json(s.history, []) if m.get("speaker")}
    for n in load_npcs(s.u):
        if npc_note_path(s, n).exists() or n["name"] in spoke:   # anyone who has appeared in this story
            note = read_npc_note(s, n)
            npcs.append({"name": n["name"], "color": n["color"], "status": note["status"], "notes": note["notes"],
                         "avatar": avatar_url(s.u, "npc", n["id"])})
    memory = load_json(s.memory, {"summaries": []})
    return {"name": s.name, "user": s.user_name, "tokens": journal_tokens(s, story), "budget": effective_budget(),
            "where": story["where"], "about": story["about"], "relationship": story["relationship"],
            "events": "\n".join(story["events"]), "npcs": npcs, "summaries": memory["summaries"]}


@app.route("/api/journal", methods=["GET", "POST"])
def api_journal():
    s = current_session()
    if not s:
        return no_session()
    if request.method == "POST":
        j = request.json or {}
        with story_lock:
            events = [("- " + l.strip().lstrip("-• ").strip()) for l in (j.get("events") or "").splitlines() if l.strip()]
            write_story(s, {"where": " ".join((j.get("where") or "").split())[:160],
                            "about": (j.get("about") or "").strip(), "relationship": (j.get("relationship") or "").strip(),
                            "events": events})
            for item in j.get("npcs") or []:
                npc = find_npc(s.u, item.get("name", ""))
                if npc:
                    write_npc_note(s, npc, {"status": npc_status(item.get("status") or "alive"),
                                            "notes": (item.get("notes") or "").strip()})
        return jsonify(journal_for_ui(s))
    read_story(s)
    return jsonify(journal_for_ui(s))


@app.route("/api/where")
def api_where():
    s = current_session()
    return jsonify({"where": read_story(s)["where"] if s else ""})


@app.route("/api/journal/update", methods=["POST"])
def api_journal_update():
    s = current_session()
    if not s:
        return no_session()
    ok = update_story(s, load_json(s.history, []))
    if not ok:
        return jsonify({"error": "Couldn't update the journal right now (LM Studio busy or unclear answer). Try again."}), 502
    return jsonify(journal_for_ui(s))


# ================================================================ login, home-screen app, access settings
@app.route("/login", methods=["GET", "POST"])
def login_page():
    acc = access()
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if request.method == "POST":
        if acc.get("pass_hash") and check_password_hash(acc["pass_hash"], request.form.get("passphrase", "")):
            session.permanent = True
            session["login"] = login_token(acc)
            return redirect(nxt)
        time.sleep(1.0)  # slows down guessing
        return render_template("login.html", error="That passphrase isn't right.", next=nxt, app_name=CONFIG["app_name"])
    return render_template("login.html", error=None, next=nxt, app_name=CONFIG["app_name"])


@app.route("/logout")
def logout():
    session.pop("login", None)
    return redirect("/login")


@app.route("/manifest.webmanifest")
def manifest():
    """Lets you add the app to a phone's home screen, where it opens like an app."""
    data = {"name": CONFIG["app_name"], "short_name": CONFIG["app_name"], "start_url": "/", "scope": "/",
            "display": "standalone", "background_color": "#121015", "theme_color": "#121015",
            "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/static/icons/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    return Response(json.dumps(data), mimetype="application/manifest+json")


@app.route("/api/access", methods=["GET", "POST"])
def api_access():
    acc = access()
    if request.method == "POST":
        if not is_local_request():
            return jsonify({"error": "Phone access can only be changed on the PC itself."}), 403
        j = request.json or {}
        new_pass = (j.get("passphrase") or "").strip()
        if new_pass:
            if len(new_pass) < 6:
                return jsonify({"error": "Use a passphrase of at least 6 characters."}), 400
            acc["pass_hash"] = generate_password_hash(new_pass)
        allow = bool(j.get("allow_network"))
        if allow and not acc.get("pass_hash"):
            return jsonify({"error": "Set a passphrase first. Your phone will ask for it once."}), 400
        acc["allow_network"] = allow
        ROOT.mkdir(parents=True, exist_ok=True)
        save_json(ACCESS_FILE, acc)
    listening = RUNNING["host"] == "0.0.0.0"
    port = CONFIG["port"]
    return jsonify({
        "allow_network": bool(acc.get("allow_network")), "has_passphrase": bool(acc.get("pass_hash")),
        "listening": listening, "restart_needed": bool(acc.get("allow_network")) != listening,
        "phone_urls": [f"http://{ip}:{port}" for ip in lan_addresses()],
        "pc_url": f"http://{CONFIG['pc_address']}:{port}", "remote": not is_local_request(),
    })


# ================================================================ settings page
@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        new, st = request.json or {}, settings()
        try:
            st["model"] = str(new.get("model", st["model"])).strip()
            st["prompt_format"] = new.get("prompt_format") if new.get("prompt_format") in ("auto", "qwen", "chat") else "auto"
            st["flair"] = new.get("flair") if new.get("flair") in FLAIRS else st["flair"]
            st["reasoning"] = new.get("reasoning") if new.get("reasoning") in REASONING_BUDGET else st["reasoning"]
            st["temperature"] = min(2.0, max(0.0, float(new.get("temperature", st["temperature"]))))
            st["max_tokens"] = min(8000, max(100, int(new.get("max_tokens", st["max_tokens"]))))
            st["repeat_penalty"] = min(2.0, max(1.0, float(new.get("repeat_penalty", st["repeat_penalty"]))))
            st["context_budget"] = min(200000, max(2000, int(new.get("context_budget", st["context_budget"]))))
            if "context_auto" in new:
                st["context_auto"] = bool(new["context_auto"])
            st["mature"] = bool(new.get("mature", st.get("mature", False)))
        except (TypeError, ValueError):
            return jsonify({"error": "One of the values isn't a number."}), 400
        ROOT.mkdir(parents=True, exist_ok=True)
        save_json(SETTINGS_FILE, st)
        return jsonify({"ok": True, "settings": st})
    model = get_model_id()
    ctx = loaded_context(model) or _last_ctx.get(model)
    memory_now = {"model": model, "ctx": ctx, "auto": auto_budget(ctx) if ctx else AUTO_FALLBACK}
    return jsonify({"settings": settings(), "defaults": DEFAULT_SETTINGS, "memory_now": memory_now,
                    "flairs": [{"id": k, "label": v[0], "about": v[2]} for k, v in FLAIRS.items()]})


@app.route("/api/models")
def api_models():
    try:
        return jsonify({"models": list_models()})
    except (requests.RequestException, ValueError) as e:
        return jsonify({"error": f"Couldn't reach LM Studio: {e}", "models": []}), 502


@app.route("/api/test_model", methods=["POST"])
def api_test_model():
    t = datetime.now()
    try:
        reply = call_llm([{"role": "system", "content": "You are a friendly tavern keeper. Reply in one short sentence."},
                          {"role": "user", "content": "Hello! Is the kitchen still open?"}], max_tokens=150, think=True)
    except requests.RequestException as e:
        return jsonify({"error": f"Couldn't reach LM Studio or the model failed: {e}"}), 502
    except GibberishReply as e:
        return jsonify({"error": e.text}), 502
    except EmptyReply:
        return jsonify({"error": "The model answered with nothing. If it's a 'thinking' model, try Prompt format: Qwen-style, or a larger reply length."}), 502
    st = settings()
    model = get_model_id()
    return jsonify({"reply": reply, "model": model, "seconds": round((datetime.now() - t).total_seconds(), 1),
                    "format": "Qwen-style" if uses_qwen_format(model, st["prompt_format"]) else "model's own template"})


# ================================================================ editor: create-or-update files
# Each "kind" of file the editor knows: which front-matter keys, the main text, and named sections.
SCHEMAS = {
    "universe":   {"meta": ["name", "genre", "tone", "era"], "body": "premise",
                   "sections": [("style", "Response style")], "level": "#"},
    "foundation": {"meta": [], "body": "text", "sections": []},
    "lore":       {"meta": ["title", "aliases", "always"], "body": "text", "sections": []},
    "character":  {"meta": ["name", "age", "summary", "premise_name", "sfw_only"], "body": "personality",
                   "sections": [*[(k, t) for k, t, _ in CHAR_TRAITS], ("appearance", "Appearance"), ("directive", "Response directive"),
                                ("example", "Example message"), ("key_memories", "Key memories"),
                                ("story_premise", "Story premise"), ("greeting", "Greeting")], "level": "#"},
    "story":      {"meta": [], "body": "premise", "sections": [("greeting", "Greeting")], "level": "#"},
    "premise":    {"meta": ["name"], "body": "premise", "sections": [("greeting", "Greeting")], "level": "#"},
    "npc":        {"meta": ["name", "age", "aliases", "summary", "color"], "body": "personality",
                   "sections": [*[(k, t) for k, t, _ in NPC_TRAITS], ("appearance", "Appearance"), ("directive", "Response directive"),
                                ("example", "Example message")], "level": "#"},
    "user":       {"meta": ["name", "age"], "body": None,
                   "sections": [("appearance", "Appearance"), ("public", "Public"), ("private", "Private")], "level": "##"},
}
LIST_KEYS = {"aliases"}
BOOL_KEYS = {"always", "sfw_only"}


def doc_path(u, kind, did):
    if kind == "universe":
        return u.file
    if kind == "foundation":
        if did not in ALL_FOUNDATIONS:
            return None
        return u.lore / "core" / f"{did}.md"
    if kind == "lore":
        p = (u.lore / did).resolve()
        if not p.is_relative_to(u.lore.resolve()) or p.suffix != ".md":
            return None
        return p
    if kind == "character":
        folder = u.chars / slug(did)
        return character_file(folder) or folder / f"{slug(did)}.md"
    if kind == "story":  # id = "<character>/<user>"
        cid, _, uid = str(did).partition("/")
        if not (u.chars / cid).is_dir() or not (u.users / f"{uid}.md").exists():
            return None
        return u.chars / cid / f"with-{uid}" / "premise.md"
    if kind == "premise":  # id = "<character>/<premise>"
        cid, _, pid = str(did).partition("/")
        if not cid or not pid or slug(pid) != pid or pid == DEFAULT_PREMISE:
            return None
        folder = (u.chars / cid).resolve()
        if folder.parent != u.chars.resolve() or not folder.is_dir():   # a real character folder, nothing else
            return None
        return folder / "premises" / f"{pid}.md"
    if kind == "npc":
        return u.npcs / f"{slug(did)}.md"
    if kind == "user":
        return u.users / f"{slug(did)}.md"
    return None


def split_front(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.DOTALL)
    return (m.group(1).splitlines(), m.group(2)) if m else ([], text)


def fm_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(str(x).replace(",", " ").strip() for x in v if str(x).strip()) + "]"
    v = str(v).replace("\n", " ").strip()
    if v and (re.search(r":\s|\s#|^[\[\]{}#&*!|>%@`'\"]", v) or v.startswith("#")):
        return '"' + v.replace('"', "'") + '"'
    return v


def fm_set(lines, key, value):
    """Replace (or add) one key in front matter, keeping every other line as it was."""
    out, i, done = [], 0, False
    while i < len(lines):
        line = lines[i]
        if re.match(rf"^{re.escape(key)}:", line, flags=re.IGNORECASE):
            i += 1
            while i < len(lines) and re.match(r"^\s*-\s+", lines[i]):  # old "- item" list
                i += 1
            out.append(f"{key}: {fm_value(value)}")
            done = True
            continue
        out.append(line)
        i += 1
    if not done:
        out.append(f"{key}: {fm_value(value)}")
    return out


def read_doc(u, kind, did):
    schema, path = SCHEMAS[kind], doc_path(u, kind, did)
    fields = {}
    if path is None or not path.exists():
        return fields, None
    text = path.read_text(encoding="utf-8")
    meta, _ = parse_note(text)
    _, rest = split_front(text)
    for key in schema["meta"]:
        v = meta.get(key)
        if key in LIST_KEYS:
            fields[key] = ", ".join(as_list(v))
        elif key in BOOL_KEYS:
            fields[key] = is_true(v)
        else:
            fields[key] = v if isinstance(v, str) else ""
    for key, title in schema["sections"]:
        fields[key], rest = extract_section(rest, title)
    if schema["body"]:
        fields[schema["body"]] = rest.strip()
    return fields, path.stat().st_mtime


def write_doc(u, kind, did, fields):
    """Create the file if it doesn't exist, otherwise update only the parts the editor manages.
    Unknown front-matter keys and (for users) unknown text are kept. A backup is made first."""
    schema, path = SCHEMAS[kind], doc_path(u, kind, did)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    lines, rest = split_front(old)
    for key in schema["meta"]:
        if key not in fields:
            continue
        v = fields[key]
        if key in LIST_KEYS:
            v = [x.strip() for x in str(v).split(",") if x.strip()]
        elif key in BOOL_KEYS:
            v = bool(v)
        lines = fm_set(lines, key, v)
    if kind == "foundation":
        lines = fm_set(fm_set(lines, "always", True), "title", ALL_FOUNDATIONS[did])
    old_sections = {}
    for key, title in schema["sections"]:
        old_sections[key], rest = extract_section(rest, title)
    if schema["body"] and schema["body"] in fields:
        rest = fields[schema["body"]]
    out = ("---\n" + "\n".join(lines) + "\n---\n" if lines else "") + (rest.strip() + "\n" if rest.strip() else "")
    level = schema.get("level", "#")
    for key, title in schema["sections"]:
        val = (fields[key] if key in fields else old_sections[key] or "").strip()
        if val:
            out += f"\n{level} {title}\n{val}\n"
    if path.exists():
        rel = slug(str(path.relative_to(u.path)))
        backup_dir = u.cache / "edit-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (backup_dir / f"{rel}-{stamp}.md").write_text(old, encoding="utf-8")
        for f in sorted(backup_dir.glob(f"{rel}-*.md"))[:-20]:
            f.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, out)
    return path.stat().st_mtime


def always_used(u):
    return sum(len(n["body"]) for n in lore_notes(u) if n["always"])


@app.route("/edit")
def edit_page():
    return render_template("edit.html")


@app.route("/api/universes", methods=["POST"])
def api_create_universe():
    name = (request.json.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Give your world a name."}), 400
    uid = slug(name)
    if (ROOT / uid).exists():
        return jsonify({"error": f"A world called '{uid}' already exists (its folder is taken)."}), 400
    (ROOT / uid).mkdir(parents=True)
    u = get_universe(uid)
    create_universe_folders(u)
    write_doc(u, "universe", None, {"name": name})
    return jsonify({"id": uid})


@app.route("/api/universe/<uid>")
def api_universe_overview(uid):
    u = get_universe(uid)
    if not u:
        return jsonify({"error": "World not found."}), 404
    lore = []
    if u.lore.exists():
        for p in sorted(u.lore.rglob("*.md")):
            rel = p.relative_to(u.lore)
            if rel.parts[0] == "core" or any(hidden(x) for x in rel.parts):
                continue
            meta, _ = parse_note(p.read_text(encoding="utf-8"))
            lore.append({"id": rel.as_posix(), "title": text_meta(meta, "title", p.stem), "always": is_true(meta.get("always")),
                         "category": rel.parts[0] if len(rel.parts) > 1 else "other"})
    return jsonify({
        "id": uid, "info": universe_info(u),
        "foundations": [{"id": k, "title": t} for k, t in FOUNDATIONS],
        "old_foundations": [{"id": k, "title": t} for k, t in OLD_FOUNDATIONS if read_doc(u, "foundation", k)[0].get("text", "").strip()],
        "categories": LORE_CATEGORIES,
        "lore": lore,
        "characters": [{"id": c["id"], "name": c["name"], "avatar": avatar_url(u, "character", c["id"]),
                        "background": background_url(u, "character", c["id"])} for c in list_characters(u)],
        "background": background_url(u, "world", u.id),
        "npcs": [{"id": n["id"], "name": n["name"], "avatar": avatar_url(u, "npc", n["id"])} for n in load_npcs(u)],
        "users": [{"id": x["id"], "name": x["name"], "avatar": avatar_url(u, "user", x["id"])} for x in list_users(u)],
        "always_used": always_used(u), "always_max": WORLD_ALWAYS_MAX_CHARS,
    })


@app.route("/api/doc")
def api_doc_get():
    u, kind, did = get_universe(request.args.get("u")), request.args.get("kind"), request.args.get("id")
    if not u or kind not in SCHEMAS:
        return jsonify({"error": "Unknown world or kind."}), 400
    if kind != "universe" and doc_path(u, kind, did) is None:
        return jsonify({"error": "Unknown item."}), 400
    fields, mtime = read_doc(u, kind, did)
    return jsonify({"fields": fields, "mtime": mtime, "exists": mtime is not None})


@app.route("/api/doc", methods=["POST"])
def api_doc_save():
    j = request.json
    u, kind = get_universe(j.get("u")), j.get("kind")
    if not u or kind not in SCHEMAS:
        return jsonify({"error": "Unknown world or kind."}), 400
    fields, did = j.get("fields") or {}, j.get("id")
    is_new = (kind in ("lore", "character", "npc", "user") and not did) or (kind == "premise" and str(did or "").endswith("/"))
    if is_new:  # new item: its file name comes from the name / title
        if kind == "lore":
            title = (fields.get("title") or "").strip()
            cat = j.get("category") if j.get("category") in LORE_CATEGORIES else "other"
            if not title:
                return jsonify({"error": "Give the entry a title."}), 400
            did = f"{cat}/{slug(title)}.md"
        elif kind in ("character", "npc", "user"):
            name = (fields.get("name") or "").strip()
            if not name:
                return jsonify({"error": "A name is needed."}), 400
            did = slug(name)
        elif kind == "premise":
            name, cid = (fields.get("name") or "").strip(), str(did)[:-1]
            char = next((c for c in list_characters(u) if c["id"] == cid), None)
            if not name:
                return jsonify({"error": "Give the premise a name."}), 400
            if not char:
                return jsonify({"error": "Save the character first."}), 400
            did = f"{cid}/{new_premise_id(char, name)}"
        path = doc_path(u, kind, did)
        if path is None or path.exists() or (kind == "character" and (u.chars / did).exists()):
            return jsonify({"error": f"'{did}' already exists. Pick a different name, or open the existing one."}), 400
    else:
        path = doc_path(u, kind, did)
        if path is None:
            return jsonify({"error": "Unknown item."}), 400
        if path.exists() and j.get("mtime") and not j.get("force") and abs(path.stat().st_mtime - j["mtime"]) > 0.001:
            return jsonify({"conflict": True, "error": "This file was changed outside the editor "
                            "(e.g. in Obsidian) since you opened it."}), 409
    mtime = write_doc(u, kind, did, fields)
    return jsonify({"id": did, "mtime": mtime, "always_used": always_used(u)})


# ================================================================ sharing: export / import character & player cards
# A card is one .json file: the description (and portrait) of a character or player, never the stories.
CARD_FORMATS = {"character": "roleplay-character", "user": "roleplay-player"}
CARD_VERSION = 1
CARD_FIELDS = {
    "character": ["name", "age", "summary", "personality", *[k for k, _, _ in CHAR_TRAITS],
                  "appearance", "directive", "example", "key_memories",
                  "premise_name", "story_premise", "greeting", "sfw_only"],
    "user": ["name", "age", "appearance", "public", "private"],
}
PICTURE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def item_exists(u, kind, item_id):
    return (u.chars / item_id).is_dir() if kind == "character" else (u.users / f"{item_id}.md").exists()


@app.route("/api/export")
def api_export():
    u, kind, item_id = get_universe(request.args.get("u")), request.args.get("kind"), request.args.get("id") or ""
    if not u or kind not in CARD_FORMATS or not item_id or not item_exists(u, kind, item_id):
        return jsonify({"error": "Nothing to export. Save it first."}), 404
    fields, _ = read_doc(u, kind, item_id)
    card = {k: fields.get(k, "") for k in CARD_FIELDS[kind]}
    if kind == "user" and request.args.get("private") != "1":
        card.pop("private")
    out = {"format": CARD_FORMATS[kind], "version": CARD_VERSION, "app": CONFIG["app_name"],
           "exported": datetime.now().strftime("%Y-%m-%d"), kind if kind == "character" else "player": card}
    if kind == "character":
        char = next(c for c in list_characters(u) if c["id"] == item_id)
        out["character"]["premises"] = [{"name": p["name"], "premise": p["premise"], "greeting": p["greeting"]}
                                        for p in list_premises(char) if p["id"] != DEFAULT_PREMISE]
    pic = avatar_file(u, kind, item_id)
    if pic:
        out["portrait"] = {"type": PICTURE_TYPES[pic.suffix.lower()], "data": base64.b64encode(pic.read_bytes()).decode()}
    bg = background_file(u, "character", item_id) if kind == "character" else None
    if bg:
        out["background"] = {"type": PICTURE_TYPES[bg.suffix.lower()], "data": base64.b64encode(bg.read_bytes()).decode()}
    name = slug(card.get("name") or item_id)
    return Response(json.dumps(out, ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.{"character" if kind == "character" else "player"}.json"'})


@app.route("/api/import", methods=["POST"])
def api_import():
    j = request.json or {}
    u, data, mode = get_universe(j.get("u")), j.get("data"), j.get("mode")
    if not u:
        return jsonify({"error": "World not found."}), 404
    if not isinstance(data, dict) or data.get("format") not in CARD_FORMATS.values():
        return jsonify({"error": "This isn't a character or player file from this app."}), 400
    if not isinstance(data.get("version"), int) or data["version"] > CARD_VERSION:
        return jsonify({"error": "This file was made by a newer version of the app. Update the app, then import it again."}), 400
    kind = "character" if data["format"] == CARD_FORMATS["character"] else "user"
    card = data.get("character" if kind == "character" else "player")
    if not isinstance(card, dict):
        return jsonify({"error": "The file is damaged: it has no character or player in it."}), 400
    fields = {k: str(card.get(k) or "")[:20000] for k in CARD_FIELDS[kind] if k in card}
    name = fields.get("name", "").strip()
    if not name:
        return jsonify({"error": "The file is damaged: it has no name."}), 400
    item_id = slug(name)
    with chat_lock:
        if item_exists(u, kind, item_id):
            if mode == "copy":
                n = 2
                while item_exists(u, kind, slug(f"{name} ({n})")):
                    n += 1
                name = f"{name} ({n})"
                fields["name"], item_id = name, slug(name)
            elif mode != "replace":
                return jsonify({"conflict": True, "name": name, "kind": kind})
        replacing = item_exists(u, kind, item_id)
        if kind == "character" and replacing:
            fields.pop("name", None)      # keep the existing name so its folder and stories still match
        write_doc(u, kind, item_id, fields)
        if kind == "character":
            char = next(c for c in list_characters(u) if c["id"] == item_id)
            existing = {p["name"].lower(): p["id"] for p in list_premises(char)}
            for p in card.get("premises") or []:
                if not isinstance(p, dict) or not str(p.get("name") or "").strip():
                    continue
                pname = str(p["name"]).strip()[:80]
                pid = existing.get(pname.lower())
                if pid == DEFAULT_PREMISE or not pid:
                    pid = new_premise_id(char, pname)
                write_doc(u, "premise", f"{item_id}/{pid}", {"name": pname, "premise": str(p.get("premise") or "")[:20000],
                                                              "greeting": str(p.get("greeting") or "")[:20000]})
        pic = data.get("portrait")
        if isinstance(pic, dict) and pic.get("type") in PICTURE_TYPES.values():
            try:
                raw = base64.b64decode(str(pic.get("data") or ""), validate=True)
            except ValueError:
                raw = b""
            if 0 < len(raw) <= 8 * 1024 * 1024:
                old = avatar_file(u, kind, item_id)
                if old:
                    to_trash(old, f"{u.id} portrait {kind} {item_id}")
                orig = avatar_original(u, kind, item_id)
                if orig:      # belonged to the old portrait
                    to_trash(orig, f"{u.id} portrait original {kind} {item_id}")
                ext = next(e for e, t in PICTURE_TYPES.items() if t == pic["type"])
                (u.path / "avatars").mkdir(exist_ok=True)
                (u.path / "avatars" / f"{kind}-{item_id}{ext}").write_bytes(raw)
        bgd = data.get("background")
        if kind == "character" and isinstance(bgd, dict) and bgd.get("type") in PICTURE_TYPES.values():
            try:
                raw = base64.b64decode(str(bgd.get("data") or ""), validate=True)
            except ValueError:
                raw = b""
            if 0 < len(raw) <= BG_MAX:
                old = background_file(u, "character", item_id)
                if old:
                    to_trash(old, f"{u.id} background character {item_id}")
                save_background(u, "character", item_id, raw, next(e for e, t in PICTURE_TYPES.items() if t == bgd["type"]))
    return jsonify({"ok": True, "kind": kind, "id": item_id, "name": name, "replaced": replacing})


# ================================================================ deleting (to the trash, never erased)
TRASH = ROOT / ".trash"


def to_trash(path, label):
    """Move a file or folder into worlds/.trash/<time> <label>/, keeping its name."""
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    dest = TRASH / f"{stamp} {slug(label)}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest / path.name))
    return dest


@app.route("/api/delete", methods=["POST"])
def api_delete():
    j = request.json or {}
    kind, did = j.get("kind"), j.get("id")
    u = get_universe(j.get("u"))
    if not u:
        return jsonify({"error": "World not found."}), 404
    with chat_lock, story_lock:
        if kind == "universe":
            dest = to_trash(u.path, f"universe {u.id}")
            state = load_json(STATE_FILE, {})
            if state.get("universe") == u.id:
                STATE_FILE.unlink(missing_ok=True)
        elif kind == "character":
            folder = u.chars / slug(did or "")
            if not did or not folder.is_dir():
                return jsonify({"error": "Character not found."}), 404
            dest = to_trash(folder, f"{u.id} character {did}")        # includes all their stories
        elif kind == "user":
            path = u.users / f"{slug(did or '')}.md"
            if not did or not path.exists():
                return jsonify({"error": "Player not found."}), 404
            dest = to_trash(path, f"{u.id} user {did}")
            for story in u.chars.glob(f"*/with-{slug(did)}"):          # their stories go along
                shutil.move(str(story), str(dest / f"{story.parent.name}-{story.name}"))
        elif kind in ("npc", "lore", "premise"):
            path = doc_path(u, kind, did) if did else None
            if path is None or not path.exists():
                return jsonify({"error": "Not found."}), 404
            dest = to_trash(path, f"{u.id} {kind} {Path(did).stem}")
        else:
            return jsonify({"error": "Unknown kind."}), 400
        if kind in ("character", "npc", "user"):
            pic = avatar_file(u, kind, Path(did).stem)
            if pic:
                shutil.move(str(pic), str(dest / pic.name))
            orig = avatar_original(u, kind, Path(did).stem)
            if orig:
                shutil.move(str(orig), str(dest / f"original-{orig.name}"))
        if kind == "character":
            bg = background_file(u, "character", did)
            if bg:
                shutil.move(str(bg), str(dest / f"background-{bg.name}"))
    return jsonify({"ok": True, "trash": str(dest)})


# ================================================================ first-run setup
def migrate_old_layouts():
    """Bring older versions of this app into the worlds/ layout. Nothing is deleted."""
    ROOT.mkdir(parents=True, exist_ok=True)
    if list_universes():
        return
    first = ROOT / "my-first-world"
    old_uni = BASE / "universe"
    if old_uni.is_dir():                         # v3: a single universe/ folder
        shutil.move(str(old_uni), str(first))
        u = get_universe(first.name)
        create_universe_folders(u)
        if not u.file.exists():
            write_doc(u, "universe", None, {"name": "My first world"})
        old_state = load_json(u.cache / "session.json", {})
        if old_state:
            save_json(STATE_FILE, {"universe": u.id, **old_state})
        print(f"Moved your universe folder to {first}")
        return
    old_char = BASE / "character.json"
    if not old_char.exists():                    # brand new install
        return
    first.mkdir()                                # v1/v2: character.json + data/
    u = get_universe(first.name)
    create_universe_folders(u)
    write_doc(u, "universe", None, {"name": "My first world"})
    c = json.loads(old_char.read_text(encoding="utf-8"))
    cid, uid = slug(c.get("name", "character")), slug(c.get("user_name", "me"))
    write_doc(u, "character", cid, {"name": c.get("name", "Character"), "personality": c.get("system_prompt", ""),
                                    "key_memories": "\n".join(f"- {k}" for k in c.get("key_memories", [])),
                                    "greeting": c.get("greeting", "")})
    write_doc(u, "user", uid, {"name": c.get("user_name", "Me"), "public": "", "private": ""})
    old_data, new_data = BASE / "data", u.chars / cid / f"with-{uid}"
    if old_data.exists():
        new_data.mkdir(parents=True, exist_ok=True)
        for name in ("history.json", "memory.json", "story.md", "archive.jsonl"):
            if (old_data / name).exists():
                shutil.copy2(old_data / name, new_data / name)
    for old, new in ((BASE / "world", u.lore / "other"), (BASE / "npcs", u.npcs)):
        if old.exists():
            for p in old.rglob("*.md"):
                dest = new / p.relative_to(old)
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    save_json(STATE_FILE, {"universe": u.id, "character": cid, "user": uid})
    print(f"Moved your setup into {first}. The old files are untouched; delete them once you're happy.")


def migrate_player_premises():
    """Older versions kept a per-player premise in with-<user>/premise.md. Turn each one into a
    named premise ("With <player>") that their story uses. The old file is renamed, not deleted."""
    for u in list_universes():
        users = {x["id"]: x for x in list_users(u)}
        for char in list_characters(u):
            for f in char["folder"].glob("with-*/premise.md"):
                user_id = f.parent.name[5:]
                try:
                    over = story_override(char, user_id)
                except (OSError, UnicodeDecodeError):
                    continue
                if over["premise"] or over["greeting"]:
                    name = f"With {users[user_id]['name'] if user_id in users else user_id}"
                    pid = new_premise_id(char, name)
                    write_doc(u, "premise", f"{char['id']}/{pid}", {"name": name, **over})
                    prefs = story_prefs(f.parent)
                    prefs["premise"] = pid
                    save_json(f.parent / "story_settings.json", prefs)
                    print(f"Turned {char['name']}'s premise for {name[5:]} into a named premise: {name}")
                f.rename(f.with_name("premise.md.converted"))


def unmangle(text):
    """Undo text that was UTF-8 but decoded as Latin-1 ('â€”' -> '—'). Leaves anything else alone."""
    if "â" not in text and "Ã" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def repair_garbled_text():
    """One-off repair for replies saved while version 9/10 decoded the stream wrongly."""
    fixed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".trash" in path.parts or path.suffix not in (".json", ".jsonl", ".md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "â" not in text and "Ã" not in text:
            continue
        if path.suffix == ".json":
            data = json.loads(text)
            def walk(x):
                if isinstance(x, str):
                    return unmangle(x)
                if isinstance(x, list):
                    return [walk(i) for i in x]
                if isinstance(x, dict):
                    return {k: walk(v) for k, v in x.items()}
                return x
            new = json.dumps(walk(data), ensure_ascii=False, indent=2)
        elif path.suffix == ".jsonl":
            lines = []
            for line in text.splitlines():
                try:
                    m = json.loads(line)
                    m["content"] = unmangle(m.get("content", ""))
                    lines.append(json.dumps(m, ensure_ascii=False))
                except ValueError:
                    lines.append(line)
            new = "\n".join(lines) + "\n"
        else:
            new = "\n".join(unmangle(line) for line in text.split("\n"))
        if new != text:
            path.write_text(new, encoding="utf-8")
            fixed += 1
    if fixed:
        print(f"Repaired garbled characters in {fixed} file(s).")


# ================================================================ daily backups
BACKUP_DIR = BASE / "backups"
BACKUPS_KEPT = 7


def backup_universes():
    """One zip of the worlds folder per day (skipping caches and the trash), last 7 kept."""
    if not CONFIG.get("daily_backups", True) or not ROOT.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"worlds-{datetime.now():%Y-%m-%d}.zip"
    if target.exists():
        return
    tmp = target.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if p.is_file() and not ({".trash", ".cache"} & set(rel.parts)) and rel.name != ".secret_key":
                z.write(p, Path("worlds") / rel)
    tmp.replace(target)
    zips = sorted(BACKUP_DIR.glob("worlds-*.zip")) + sorted(BACKUP_DIR.glob("universes-*.zip"))
    for old in sorted(zips, key=lambda z: z.stem.split("-", 1)[1])[:-BACKUPS_KEPT]:   # by date
        old.unlink()


def backup_loop():
    while True:
        try:
            backup_universes()
        except Exception as e:  # a failed backup must never stop the app
            print(f"!! Backup failed: {e}")
        time.sleep(3600)       # check every hour; a new zip is made once per day


if __name__ == "__main__":
    migrate_old_layouts()
    migrate_player_premises()
    repair_garbled_text()
    app.secret_key = secret_key()
    threading.Thread(target=predigest_all, daemon=True).start()
    threading.Thread(target=backup_loop, daemon=True).start()
    port = int(CONFIG["port"])
    RUNNING["host"] = "0.0.0.0" if access().get("allow_network") and access().get("pass_hash") else "127.0.0.1"
    pc_url = f"http://{CONFIG['pc_address']}:{port}"
    print(f"Worlds folder:      {ROOT}")
    print(f"On this PC, open:   {pc_url}")
    if RUNNING["host"] == "0.0.0.0":
        for ip in lan_addresses():
            print(f"On your phone:      http://{ip}:{port}   (same Wi-Fi; asks for your passphrase once)")
    else:
        print("Phone access is off (turn it on in Model Settings, then restart the app from the tray icon).")
    if "--open" in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(pc_url)).start()
    app.run(host=RUNNING["host"], port=port, debug=False, threaded=True)
