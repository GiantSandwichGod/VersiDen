# VersiDen

A local roleplay companion. Chat with your own characters on your own PC through LM Studio,
in worlds you write, with stories that remember and side characters who live in them.

## First-time setup (once)

The full step-by-step guide is built into the app: open it and click **? Guide** (or go to
`/guide`). The short version:


1. **Install the add-ons.** Open the app's folder in File Explorer, click the address bar, type
   `cmd` and press Enter. In the black window, type this and press Enter:
   ```
   pip install -r requirements.txt
   ```
   Wait until it finishes, then close the black window.
2. **Let LM Studio run in the background.** In LM Studio, open its settings (`Ctrl` + `,`),
   click **Developer**, and turn on **Enable Local LLM Service**. The model server then runs
   whenever you're logged in, even with the LM Studio window closed.
3. **Start the app:** double-click **`start.bat`**. After a few seconds your browser opens the app,
   and a small blue speech-bubble icon appears near the clock. (If you don't see it, click the
   **^** arrow next to the clock; you can drag the icon out onto the taskbar.)
4. **Make it start with Windows:** right-click the icon → tick **Start with Windows**.

From now on the app runs whenever the PC is on. Open it at **http://versiden.localhost:5000**
(bookmark it), or left-click the tray icon.

## The tray icon

Right-click the icon near the clock:

| Menu item | What it does |
|---|---|
| **Open** | Opens the app in your browser (also: left-click the icon) |
| **Phone access…** | Opens Model Settings, where the phone address and passphrase are |
| **Restart** | Restarts the app, e.g. after changing phone access or `config.toml` |
| **Show log** | Opens the app's log in Notepad, which is useful when something goes wrong |
| **Start with Windows** | Tick to start the app automatically when you log in |
| **Quit** | Stops the app |

If the app stops by itself, the tray starts it again (up to three times in a row; after that
the icon's tooltip says "stopped" and **Show log** tells you why).

**Troubleshooting mode:** quit the tray version, then double-click **`start-with-console.bat`**.
It runs the app in a visible window, so you can see everything it prints.

**The address:** `versiden.localhost` works in Chrome, Edge and Firefox on this PC with no setup.
Any name ending in `.localhost` does; change it in `config.toml` (`pc_address`). Plain
`http://localhost:5000` keeps working too.

## Using it on your phone

1. On the PC: **⚙ Model Settings → Access**. Tick **Allow devices on my home network**, set a
   **passphrase** and click **Save access**.
2. Restart the app: right-click its tray icon → **Restart**. The first time, Windows asks
   whether to allow Python on networks: tick **Private networks** and click **Allow**.
3. On your phone, on the **same Wi-Fi**, open the address shown in Model Settings (something like
   `http://192.168.1.23:5000`) and enter the passphrase once.
4. **To make it feel like an app:** in Safari, tap **Share → Add to Home Screen** (Android/Chrome:
   **⋮ → Add to Home screen**). It then opens fullscreen with its own icon.

It works while the PC is on and the app is running. The PC itself never asks for the passphrase.
Changing the passphrase logs all other devices out. Only the PC can change access settings.

## config.toml

Created on first start, next to `app.py`. Restart the app after editing it.

| Setting | What it does |
|---|---|
| `port` | The port (default 5000) |
| `pc_address` | The address opened on this PC (default `versiden.localhost`) |
| `lmstudio_url` | LM Studio's address, ending in `/v1` |
| `worlds_dir` | Where your worlds live (default: the `worlds` folder; a full path is fine, e.g. a folder in your Obsidian vault) |
| `app_name` | The name under the icon on your phone's home screen |
| `daily_backups` | A zip of your worlds once a day in `backups/`; the last 7 are kept |

To restore a backup, stop the app and unzip it over the `worlds` folder (or somewhere else
first, to copy single files back).

## The start screen

Pick a world (its **✎ Edit** button opens the editor), then click **Continue as …** or
**Start as …** on a character. One click and you're in the story.

## The chat

- **Replies appear as they're written.** While a reply is being written, **Send** turns into
  **■ Stop**. Stop makes LM Studio stop, and your message goes back into the text box.
- **Hover over a message** to **Edit** or **Delete** it (on a phone, the buttons are always shown).
- **↻ Reroll** sits under the latest reply. Every version is kept: flip between them with **‹ ›**.
- **Let someone speak:** the chips above the message box. **▸ Kael continues** lets the
  character keep going without you replying, and an NPC chip asks that NPC to say something.
  People mentioned recently come first, and dead NPCs are hidden.
- **Type @** to address an NPC. A list pops up to pick from.
- **The flair pill** (left in the message box: `Roleplay ▾`) sets how replies are written in
  *this* story: Roleplay, Storyteller, Companion, Casual chat or None. Switch it whenever the
  scene changes. It's highlighted when it differs from the default in Model Settings. It applies
  from the next reply; Reroll after switching to see it right away.
- **Long chats:** when a story gets too long for the model's memory, the oldest messages are
  summarised into the memory journal. They stay in the chat for you to scroll back to, below a
  line that says so; the model then remembers them as a summary.
- **Several tabs** can have different stories open at the same time; each tab writes only to
  its own story.
- **Journal** (top right) opens a side panel: what the character knows about you, where you
  stand, key events, and every side character who has appeared (with their status and notes).
- **The model name and status dot** (top right) show which model is answering. The dot is
  green when it's loaded, orange when it needs attention (e.g. a picked model that loads on
  the next message), and red when LM Studio is offline. Click it to switch models right there.
- **Aa** sets the text size (Small / Medium / Large) and the story font (Serif: Literata, or
  Sans: Inter). Both are remembered in your browser. Long replies wrap at about 75 characters
  per line, which is easier on the eyes.
- **⇔** switches the chat width.
- **⇄** (top left) slides out a panel to switch story: pick a world, then **Continue as …**
  or **Start as …** on any character. Your current story is highlighted. **✎ Edit world**
  and **+ New world** are at the top. Esc or a click outside closes it.

**Portraits:** add a picture for a character, NPC or player in the editor (the Portrait card
at the top of their form). Pictures are saved in `<world>/avatars/`.

## Worlds

Each world is a folder in `worlds/`, with its own
foundations, lore, characters, NPCs and players. A player in one world can only meet the
characters of that world. (Older versions called this folder `universes`; it's renamed
automatically.)

```
worlds/
  harrowgate/
    world.md              ← name, genre, tone, era, world overview, writing format
    characters/
      kael/
        kael.md           ← personality, key memories, default premise + greeting (you write)
        premises/         ← more story premises, e.g. bounty-target.md (name, premise, greeting)
        with-mira/        ← Kael's story with Mira (the app writes)
          story_settings.json  ← which premise and flair this story uses
          story.md        ← what he's learned about you, relationship, key events
          npcs/bram.md  ← Bram's status + memories in THIS story
          history.json, memory.json, archive.jsonl, backups/
    lore/
      core/               ← world foundations (always included)
      places/ maps/ factions/ history/ …
    npcs/
    users/                ← who you play as, in this world only
```

The code can go on GitHub while `worlds/` stays private (it's in `.gitignore`).
To keep your worlds in your Obsidian vault, set `worlds_dir` in `config.toml` to that
folder, e.g. `worlds_dir = 'C:\Users\you\Documents\MyVault\Worlds'` (single quotes).

## The world editor

On the start screen, **+ New world** opens the editor, and **✎ Edit** on a world reopens
it for an existing one. There are 6 steps in two groups. **World:** basics, world foundations,
Places & Lore. **People:** characters, NPCs, players. **Save & Finish** on the last step takes you to the start screen.

- If a file doesn't exist yet, saving creates it. If it exists, the form opens filled in
  and saving updates it.
- Only the parts the editor shows are replaced. Anything extra you added in Obsidian
  (other front-matter keys, notes in a user file) is kept.
- If you changed a file in Obsidian while the editor had it open, you're asked before
  anything is overwritten.
- A backup is made before every save, in `<world>/.cache/edit-backups/`.
- The counters are guides. Going over the limit is allowed, but it uses up space the
  conversation needs.
- The editor never touches the chat, story notes or memories in `with-<user>` folders.

**Response Directive & Writing Format.** A character's (or NPC's) *Response directive* is
their voice in a few words: "sharp, smug, teasing". The world's *Writing format* (end of the
World foundations step; stored as `# Response style` in `world.md`) holds rules that are the
same for everyone in that world: point of view, tense, how actions are shown, reply length. Both are
placed right after the chat (together with the Flair from Model Settings), as the last thing the
model reads before replying, which makes
them much stronger than text buried in the personality. Keep them short.

**Appearance.** Characters, NPCs and players each have an Appearance card: how they look.
Everyone knows their own look, the character sees yours, and when people share a scene they
see each other's. It keeps descriptions consistent (no eye colours changing mid-story).

**Example message.** A sample reply showing how a character writes. The model copies the
style, and it's labelled so it's never treated as something that happened in the story.

**Name placeholders.** In example messages, greetings and story premises, `{user}` becomes the
name of whoever is playing, and `{char}` the character's name. Handy when a character has
several players.

**World overview vs. story premise.** The *world overview* (World foundations step) is shared
by every character: what the world is and what's going on in it. Each character also has a
*story premise* (Characters step): where their story starts, their situation, how they meet
you. Under **More story premises** you can add other ways a story can begin, each with its own
greeting. For example, Kael meets Mira as a bounty target but Tobin as a client.

**Starting a new story.** Clicking **Start as …** opens **Set the scene**: pick one of the
character's premises, tweak the text if you like, and choose whether the character speaks
first or you open the scene. If you change the text, it's saved as a new premise (the original
stays as it is). Each story remembers its premise; editing a premise later changes it for every
story using it. Older per-player premises (`with-<user>/premise.md`) are turned into named
premises automatically the first time this version starts.

You can still edit any file directly. It's all plain Markdown.

**Deleting.** Every character, NPC, player and lore entry has a **Delete** button at the bottom
of its form. The whole world has one in step 1 (you type its name to confirm). Nothing is
erased: it all moves to `worlds/.trash/`, in a folder named with the date and what it was.
To undo, stop the app and move the folder back where it came from. Deleting a character takes
their stories with them, and deleting a player takes that player's stories with them. Empty the
trash folder yourself when you're sure.

## Characters

Easiest: the editor's **Characters** step. Or by hand: create `characters/mira/mira.md`:

```
---
name: Mira
---
The system prompt: personality, background, how she talks, reply rules…

# Response directive
Her voice in a few words (optional, max ~250 characters)

# Example message
A sample reply in her style (optional). Used as a style sample, never as a memory.

# Key memories
- Facts she must never forget (optional)

# Story premise
Where her story starts, her situation, how she meets you (optional)

# Greeting
*The first message of a new story.*
```

The character file stays as you wrote it. Everything the character learns goes into their
`with-<user>/` folder. Every character + user pair has its own story, so Kael's story
with Mira and Kael's story with Tobin never mix.

## Users

Easiest: **+ New player** on the start screen, or the editor's **Players** step. Or by hand, `users/rowan.md`:

```
---
name: Rowan
---
## Public
Appearance, how you come across, your role in the world. Characters and NPCs get this.

## Private
Your background and secrets. NOT sent to the model.
```

Characters learn the rest by playing. To send the private part (as "hidden background,
don't reveal"), set `SHARE_PRIVATE_USER_INFO = True`. Small models do tend to blurt
secrets out, though.

## Editing characters and players, Import & Export

You don't need the world editor for characters and players:

- **Start screen:** ✎ Edit on a character's card, the **Players** row (click a player to edit,
  **+ New player**), and **+ New character**. Each character card has a **Play as** dropdown:
  pick a player, then **Continue** (existing story) or **Start new story**.
- **⇄ drawer** (in the chat): world actions at the top (✎ Edit world, + New world), then each
  character with ✎ and the same **Play as** dropdown, and + New character / + New player /
  ⇪ Import at the bottom.
- **Chat page:** click the character's name or portrait in the header to edit them, or the
  player's name ("with …") to edit your player. **Back** returns you to the chat.

**Export** (at the bottom of a character's or player's page) saves a `.json` card: the
description, premises and portrait, never your stories. For players it asks whether to include
the Private section; leave it out when sharing.

**Import** (⇪ on the start screen, or in the wizard's Characters and Players steps, or ⇪ Import in the ⇄ drawer) adds a card to
the current world. If the name already exists, choose **Add as a copy** ("Kael (2)") or
**Replace** (swaps in the imported description and premises; your stories with them are kept).

## Mature content

**Model Settings → Content → Mature content** is off by default. Off: romance and tension are fine,
but sexual scenes fade to black. On: mature content between consenting adults is allowed when
the story leads there. A character can opt out on their page (**Never mature content**), which
keeps their stories non-explicit either way. Anyone under 18 is always off-limits.

The switch only changes the instructions. Whether a model actually writes mature content
depends on the model: many official models (Qwen included) refuse or fade to black anyway.
Community roleplay fine-tunes on Hugging Face (searchable in LM Studio) are usually willing.

## Lore

Easiest: the editor's **World foundations** and **Places & Lore** steps. Or `.md` files
anywhere in `lore/` (subfolders are fine):

- `always: true` at the top means every character gets the note on every message ("always
  on"), like the World foundations cards (World overview, World rules, Peoples & Species,
  Politics & Current Affairs). Use it only for what's always true. Keep these focused.
- Otherwise a note is added when its **file name** or an **alias** is mentioned:
  ```
  ---
  aliases: [the coven, Hollow Sisters]
  ---
  ```
- Long notes are condensed once by the model and cached (`<world>/.cache/digests`).
- Obsidian syntax is fine: `[[links]]` become text, and Dataview queries and `%%comments%%`
  are removed. Add `ignore: true` to leave a note out.
- The model reads text only. Describe maps in words (regions, distances, borders).

## NPCs

Easiest: the editor's **NPCs** step. Or one file per side character in `npcs/`:

```
---
name: Bram
aliases: [Jen]
summary: Rowan's friend, just finished her doctorate.
color: "#2f9e44"
---
Personality, how she talks, relationships, what she knows…
```

**How they join in:**
- When an NPC is mentioned, the model is asked whether they're *in the scene*. If yes,
  they reply after the main character.
- Start a message with `@Bram` to talk only to her.
- Use `@Bram` mid-message to get the main character first, then Bram.
- The **Let… speak** menu lets anyone talk.

**NPCs remember.** In each story, every NPC has a notes file with a **Status** line and what
they know and feel about you and the main character. It updates together with the story.
If the status says *dead* (or deceased, killed…), they can't be summoned in that story,
and the main character knows they're gone. Edit their Status in the **Journal** to
bring them back. NPC notes are per story: Bram dying in Kael's story doesn't affect
anyone else's.

## The Journal

Shows and lets you edit:
- `story.md`: about you, the relationship, key events
- each NPC's notes in this story
- a summary of the earlier conversation

These update by themselves every `STORY_UPDATE_EVERY` messages. **Update from chat now**
forces it. Every version is backed up in `with-<user>/backups/`.

## Model Settings

**⚙ Model Settings** (on the start screen, in the chat header's ⚙ menu and in the editor) controls the model:

| Setting | What it does |
|---|---|
| Model | Any model downloaded in LM Studio. One that isn't loaded is loaded on the next message |
| Prompt format | Auto: Qwen models get the "thinking off" format, other models use their own template |
| Default flair | The flair new stories start with (each story can switch it from the message box) |
| Reasoning effort | Off / Light / Deep: the model thinks (hidden) before replying. Slower but more attentive. Qwen-style format only. If it runs out of room, the reply comes without thinking |
| Creativity | Temperature: focused to wild |
| Repetition penalty | Raise it if a character keeps repeating phrases |
| Reply length cap | Safety cap per reply. Ask for short replies in the Writing format instead |
| Memory size | **Automatic** by default: about 75% of the Context Length the model is loaded with in LM Studio. Untick to set a fixed number |

**Test model** sends a one-line test message and shows the reply, the model and the time
taken. Settings are saved in `worlds/.settings.json`. With 12 GB of VRAM, unload the
old model in LM Studio when switching (or turn on Auto-Evict).

A few things stay at the top of `app.py`: `STORY_UPDATE_EVERY`, `SHARE_PRIVATE_USER_INFO`, the lore space limits and `NPC_MAX_PER_TURN`.

## Troubleshooting

- **"WARNING: This is a development server"** in the app's window: that's normal and fine for
  home use (you and your phone). It's Flask's standard notice.
- **The phone can't connect:** check it's on the same Wi-Fi (not mobile data or a guest network),
  that phone access is on and the app was restarted, and that you allowed the app through the
  Windows firewall (Windows Security → Firewall → Allow an app). If Model Settings lists more than one
  address, try the next one.
- **`versiden.localhost` doesn't open:** use Chrome, Edge or Firefox, and type the full
  `http://versiden.localhost:5000`. `http://localhost:5000` always works too.

- **"Couldn't reach LM Studio"**: the server isn't running or no model is loaded.
- **Empty replies**: click Reroll.
- **A character forgets something**: add it in the Journal and Save.
- **A character added by hand doesn't show up**: the `.md` file has to be directly inside
  its own folder in `characters/`, and the folder can't start with `_`.

## Fonts

The app bundles **Inter** (interface) and **Literata** (story text) in `static/fonts/`, so it
works offline and never contacts Google. Both are free under the SIL Open Font License 1.1.
Their licence files are next to the fonts.
