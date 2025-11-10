# bot.py

import discord
from discord.ext import commands
from dotenv import load_dotenv
import json
import os
from translator import TranslatorCascade
import logging.handlers

load_dotenv(verbose=True)

# Setup logging to both console and file
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

# Create handlers
console_handler = logging.StreamHandler()
file_handler = logging.handlers.RotatingFileHandler(
    filename=os.path.join(log_dir, 'glupek.log'),
    maxBytes=10 * 1024 * 1024,  # 10MB per file
    backupCount=50,  # Keep 50 files = 500MB total
    encoding='utf-8'
)

# Format
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Setup root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger(__name__)

# Load config
CONFIG_FILE = "config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "enabled_languages": ["en", "es", "fr", "de", "ru", "pt"],
            "flags": {
                "en": "🇬🇧", "es": "🇪🇸", "fr": "🇫🇷",
                "de": "🇩🇪", "ru": "🇷🇺", "pt": "🇵🇹"
            },
            "priority_order": [
                "en", "es", "fr", "de", "ru", "pt", "it", "pl",
                "ja", "ko", "zh", "ar", "hi", "nl", "sv", "no",
                "da", "fi", "tr", "cs"
            ]
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=2)
        logger.info("Created default config.json")
        return default_config

    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


# Letter emojis for languages without flags
LETTER_EMOJIS = {
    chr(i): chr(0x1F1E6 + i - ord('a')) for i in range(ord('a'), ord('z') + 1)
}


def get_flag_emoji(lang_code: str) -> str:
    """Get flag emoji or letter emoji for language code"""
    config = load_config()
    if lang_code in config["flags"]:
        return config["flags"][lang_code]
    # Fallback to letter emoji (e.g., 'la' -> 🇱🇦)
    if len(lang_code) == 2:
        return LETTER_EMOJIS.get(lang_code[0], '🏳️') + LETTER_EMOJIS.get(lang_code[1], '🏳️')
    return '🏳️'


# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize translator
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
translator = TranslatorCascade(DEEPL_API_KEY)


@bot.event
async def on_ready():
    logger.info(f'Głupek is online as {bot.user}')
    print(f'Głupek is online as {bot.user}')


@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        await bot.process_commands(message)
        return

    logger.info(f"New message from {message.author}: {message.content[:50]}...")

    # Add flag reactions to every message
    config = load_config()
    enabled = config["enabled_languages"]
    priority = config["priority_order"]

    # Sort enabled languages by priority
    sorted_langs = sorted(
            enabled,
            key=lambda x: priority.index(x) if x in priority else 999
    )

    # Limit to 20 reactions (Discord limit)
    langs_to_add = sorted_langs[:20]

    logger.info(f"Adding {len(langs_to_add)} flag reactions")

    for lang in langs_to_add:
        try:
            emoji = get_flag_emoji(lang)
            await message.add_reaction(emoji)
        except Exception as e:
            logger.error(f"Failed to add reaction for {lang}: {e}")

    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload):
    """
    Handles reactions on old messages (even before bot started).
    Gets triggered for ALL reactions, including historical ones if we fetch them.
    """
    # Ignore bot reactions
    if payload.user_id == bot.user.id:
        return

    # Fetch the channel, message, and user
    channel = bot.get_channel(payload.channel_id)
    if not channel:
        logger.warning(f"Could not find channel {payload.channel_id}")
        return

    try:
        message = await channel.fetch_message(payload.message_id)
        user = await bot.fetch_user(payload.user_id)
    except Exception as e:
        logger.error(f"Failed to fetch message or user: {e}")
        return

    # Create a fake reaction object to reuse existing logic
    reaction = discord.utils.get(message.reactions, emoji=payload.emoji.name)
    if not reaction:
        logger.warning(f"Could not find reaction {payload.emoji.name}")
        return

    # Call the same handler as before
    await handle_translation_request(reaction, user, message)


async def handle_translation_request(reaction, user, message):
    """
    Extracted translation logic so both on_reaction_add and on_raw_reaction_add can use it.
    """
    logger.info(f"Reaction {reaction.emoji} added by {user.name}")

    # Determine which language was requested
    config = load_config()
    requested_lang = None

    for lang, flag in config["flags"].items():
        if str(reaction.emoji) == flag:
            requested_lang = lang
            break

    # Check letter emojis if no flag match
    if not requested_lang:
        emoji_str = str(reaction.emoji)
        for lang in config["enabled_languages"]:
            if emoji_str == get_flag_emoji(lang):
                requested_lang = lang
                break

    if not requested_lang:
        logger.warning(f"Could not determine language for emoji {reaction.emoji}")
        return

    logger.info(f"Language requested: {requested_lang}")

    # Check if SUCCESSFUL translation already exists in thread
    translation_exists = False

    if message.thread:
        logger.info("Checking existing thread for translation")
        async for msg in message.thread.history(limit=100):
            if msg.author == bot.user and msg.content.startswith(f"{reaction.emoji}:"):
                # Check if it's an error message or actual translation
                if "Translation failed" in msg.content or "exhausted" in msg.content:
                    logger.info("Found error message, will retry translation")
                else:
                    logger.info("Successful translation already exists, skipping")
                    return

    # Create thread if doesn't exist
    thread = message.thread
    if not thread:
        try:
            logger.info("Creating thread for translations")

            # Use first 50 chars of message as thread name, or generic name
            thread_name = "🌍 Translations"
            if message.content:
                snippet = message.content[:50].strip()
                if snippet:
                    thread_name = snippet

            thread = await message.create_thread(
                    name=thread_name,
                    auto_archive_duration=60
            )
        except Exception as e:
            logger.error(f"Failed to create thread: {e}")
            return

    # Translate
    original_text = message.content
    if not original_text:
        logger.warning("Message has no content to translate")
        return

    logger.info(f"Translating: '{original_text[:50]}...' to {requested_lang}")
    translated, service = translator.translate(original_text, requested_lang)

    if translated:
        logger.info(f"Translation successful using {service}")
        # Split if necessary (Discord limit: 2000 chars)
        prefix = f"{reaction.emoji}: "
        chunks = split_message(translated, 2000 - len(prefix))

        for i, chunk in enumerate(chunks):
            content = f"{prefix}{chunk}" if i == 0 else chunk
            try:
                await thread.send(content)
                logger.info(f"Sent translation chunk {i + 1}/{len(chunks)}")
            except Exception as e:
                logger.error(f"Failed to send translation: {e}")
    else:
        logger.error(f"Translation failed: {service}")
        try:
            await thread.send(f"{reaction.emoji}: {service}")
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")


@bot.event
async def on_reaction_add(reaction, user):
    """Handles reactions added while bot is running"""
    if user.bot:
        return

    await handle_translation_request(reaction, user, reaction.message)


def split_message(text: str, max_length: int = 2000) -> list:
    """Split message into chunks that fit Discord's limit"""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current_chunk = ""

    # Split by sentences/lines to avoid mid-word breaks
    lines = text.split('\n')

    for line in lines:
        if len(current_chunk) + len(line) + 1 <= max_length:
            current_chunk += line + '\n'
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + '\n'

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


@bot.command(name='glupek')
@commands.has_permissions(administrator=True)
async def add_language(ctx, lang_code: str, flag_emoji: str = None):
    """
    Add a new language to the translation list.
    Usage: !glupek <lang_code> [flag_emoji]
    Example: !glupek ko 🇰🇷
    """
    lang_code = lang_code.lower()
    logger.info(f"Admin {ctx.author} adding language: {lang_code}")

    config = load_config()

    if lang_code in config["enabled_languages"]:
        await ctx.send(f"Language `{lang_code}` is already enabled.")
        return

    # Add to enabled languages
    config["enabled_languages"].append(lang_code)

    # Add flag emoji if provided, otherwise use letter emoji
    if flag_emoji:
        config["flags"][lang_code] = flag_emoji
    else:
        config["flags"][lang_code] = get_flag_emoji(lang_code)

    save_config(config)

    await ctx.send(f"🌍 Language `{lang_code.upper()}` added with flag {config['flags'][lang_code]}")
    logger.info(f"Language {lang_code} added successfully")


@bot.command(name='glupek_remove')
@commands.has_permissions(administrator=True)
async def remove_language(ctx, lang_code: str):
    """
    Remove a language from the translation list.
    Usage: !glupek_remove <lang_code>
    """
    lang_code = lang_code.lower()
    logger.info(f"Admin {ctx.author} removing language: {lang_code}")

    config = load_config()

    if lang_code not in config["enabled_languages"]:
        await ctx.send(f"Language `{lang_code}` is not enabled.")
        return

    config["enabled_languages"].remove(lang_code)
    if lang_code in config["flags"]:
        del config["flags"][lang_code]

    save_config(config)

    await ctx.send(f"🗑️ Language `{lang_code.upper()}` removed.")
    logger.info(f"Language {lang_code} removed successfully")


@bot.command(name='glupek_list')
async def list_languages(ctx):
    """List all enabled languages"""
    config = load_config()
    enabled = config["enabled_languages"]

    lang_list = ", ".join([f"{config['flags'].get(lang, '🏳️')} {lang.upper()}" for lang in enabled])

    await ctx.send(f"**Enabled languages ({len(enabled)}):**\n{lang_list}")


# Run bot
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN environment variable not set")
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        exit(1)

    logger.info("Starting Głupek bot...")
    bot.run(TOKEN)
