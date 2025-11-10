# bot.py

import json
import logging.handlers
import os
import random

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database as db
from translator import TranslatorCascade

load_dotenv(verbose=True)

# Setup logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, 'glupek.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=50,
        encoding='utf-8'
)
file_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
logger.info("Głupek logging initialized")

# Global config file (defaults only)
CONFIG_FILE = "config.json"


def load_global_config():
    """Load global defaults from config.json"""
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "default_languages": ["en", "es", "fr", "de", "ru", "pt", "zh"],
            "default_flags": {
                "en": "🇬🇧", "es": "🇪🇸", "fr": "🇫🇷",
                "de": "🇩🇪", "ru": "🇷🇺", "pt": "🇵🇹",
                "zh": "🇨🇳"
            },
            "priority_order": [
                "en", "es", "fr", "de", "ru", "pt", "zh", "it", "pl",
                "ja", "ko", "ar", "hi", "nl", "sv", "no",
                "da", "fi", "tr", "cs"
            ],
            "default_mode": "thread"
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=2)
        logger.info("Created default config.json")
        return default_config

    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)


# Letter emojis for languages without flags
LETTER_EMOJIS = {
    chr(i): chr(0x1F1E6 + i - ord('a')) for i in range(ord('a'), ord('z') + 1)
}


def get_flag_emoji(lang_code: str, server_flags: dict = None) -> str:
    """Get flag emoji for language code"""
    global_config = load_global_config()

    # Check server custom flags first
    if server_flags and lang_code in server_flags:
        return server_flags[lang_code]

    # Check global flags
    if lang_code in global_config["default_flags"]:
        return global_config["default_flags"][lang_code]

    # Fallback to letter emoji
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
    db.init_db()
    logger.info(f'Głupek is online as {bot.user}')
    print(f'Głupek is online as {bot.user}')


@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    # Process commands FIRST - don't add reactions to command messages
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.invoke(ctx)
        # Delete command message to keep chat clean
        try:
            await message.delete()
        except discord.Forbidden:
            logger.warning(f"Cannot delete command message - missing permissions")
        except Exception as e:
            logger.error(f"Failed to delete command message: {e}")
        return

    logger.info(f"New message from {message.author}: {message.content[:50]}...")

    # Get server config
    global_config = load_global_config()
    server_config = db.get_server_config(str(message.guild.id), global_config)

    enabled = server_config["enabled_languages"]
    priority = global_config["priority_order"]
    server_flags = server_config["custom_flags"]

    # Sort by priority
    sorted_langs = sorted(
            enabled,
            key=lambda x: priority.index(x) if x in priority else 999
    )

    langs_to_add = sorted_langs[:20]
    logger.info(f"Adding {len(langs_to_add)} flag reactions")

    for lang in langs_to_add:
        try:
            emoji = get_flag_emoji(lang, server_flags)
            await message.add_reaction(emoji)
        except Exception as e:
            logger.error(f"Failed to add reaction for {lang}: {e}")


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

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

    reaction = discord.utils.get(message.reactions, emoji=payload.emoji.name)
    if not reaction:
        logger.warning(f"Could not find reaction {payload.emoji.name}")
        return

    await handle_translation_request(reaction, user, message)


async def handle_translation_request(reaction, user, message):
    logger.info(f"Reaction {reaction.emoji} added by {user.name}")

    # Check if this is a challenge message
    if str(message.id) in active_challenges:
        await handle_challenge_response(reaction, user, message)
        return

    # Get server config
    global_config = load_global_config()
    server_config = db.get_server_config(str(message.guild.id), global_config)

    # Determine requested language
    requested_lang = None
    emoji_str = str(reaction.emoji)

    # Check custom flags first
    for lang, flag in server_config["custom_flags"].items():
        if emoji_str == flag:
            requested_lang = lang
            break

    # Check global flags
    if not requested_lang:
        for lang, flag in global_config["default_flags"].items():
            if emoji_str == flag:
                requested_lang = lang
                break

    # Check letter emojis
    if not requested_lang:
        for lang in server_config["enabled_languages"]:
            if emoji_str == get_flag_emoji(lang, server_config["custom_flags"]):
                requested_lang = lang
                break

    if not requested_lang:
        logger.warning(f"Could not determine language for emoji {reaction.emoji}")
        return

    logger.info(f"Language requested: {requested_lang}")

    # Check if translation exists
    if message.thread:
        logger.info("Checking existing thread for translation")
        async for msg in message.thread.history(limit=100):
            if msg.author == bot.user and msg.content.startswith(f"{reaction.emoji}:"):
                if "Translation failed" not in msg.content and "exhausted" not in msg.content:
                    logger.info("Successful translation already exists, skipping")
                    return

    # Create thread if needed
    thread = message.thread
    if not thread:
        try:
            logger.info("Creating thread for translations")
            thread_name = "🌐 Translations"
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

    # Apply custom dictionary
    text_to_translate = apply_dictionary(original_text, server_config["dictionary"])

    logger.info(f"Translating: '{text_to_translate[:50]}...' to {requested_lang}")
    translated, service = translator.translate(text_to_translate, requested_lang)

    # Log translation attempt
    db.log_translation(
            str(message.guild.id),
            str(message.id),
            None,
            requested_lang,
            service,
            translated is not None
    )

    # Log API usage if successful
    if translated:
        db.log_api_usage(service, len(original_text))

    if translated:
        logger.info(f"Translation successful using {service}")
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


async def handle_challenge_response(reaction, user, message):
    """Handle user response to translation challenge"""
    correct_lang = active_challenges[str(message.id)]

    # Determine which language was guessed
    global_config = load_global_config()
    server_config = db.get_server_config(str(message.guild.id), global_config)

    guessed_lang = None
    emoji_str = str(reaction.emoji)

    # Check custom flags
    for lang, flag in server_config["custom_flags"].items():
        if emoji_str == flag:
            guessed_lang = lang
            break

    # Check global flags
    if not guessed_lang:
        for lang, flag in global_config["default_flags"].items():
            if emoji_str == flag:
                guessed_lang = lang
                break

    # Check letter emojis
    if not guessed_lang:
        for lang in server_config["enabled_languages"]:
            if emoji_str == get_flag_emoji(lang, server_config["custom_flags"]):
                guessed_lang = lang
                break

    if not guessed_lang:
        return

    # Check if correct
    if guessed_lang == correct_lang:
        # Correct answer
        embed = discord.Embed(
                title="✅ Correct!",
                description=f"{user.mention} got it right! The language was **{correct_lang.upper()}**.",
                color=0x57F287
        )
        await message.reply(embed=embed)

        # Remove from active challenges
        del active_challenges[str(message.id)]

        # Clear all reactions
        try:
            await message.clear_reactions()
        except:
            pass
    else:
        # Wrong answer - just remove their reaction
        try:
            await reaction.remove(user)
        except:
            pass


@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    await handle_translation_request(reaction, user, reaction.message)


def apply_dictionary(text: str, dictionary: dict) -> str:
    """Apply custom dictionary replacements"""
    for term, replacement in dictionary.items():
        text = text.replace(term, replacement)
    return text


def split_message(text: str, max_length: int = 2000) -> list:
    """Split message into chunks"""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current_chunk = ""
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


# Command group
@bot.group(name='glupek', invoke_without_command=True)
async def glupek_group(ctx):
    """Głupek translation bot commands"""
    await ctx.send(
            "**Głupek Translation Bot**\n"
            "Use `!glupek help` to see all available commands."
    )


@glupek_group.command(name='add')
@commands.has_permissions(administrator=True)
async def add_language(ctx, lang_code: str, flag_emoji: str = None):
    """Add a language to translation list"""
    lang_code = lang_code.lower()
    logger.info(f"Admin {ctx.author} adding language: {lang_code} to server {ctx.guild.id}")

    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)

    if lang_code in server_config["enabled_languages"]:
        await ctx.send(f"Language `{lang_code}` is already enabled.")
        return

    # Add language
    server_config["enabled_languages"].append(lang_code)
    db.update_server_languages(str(ctx.guild.id), server_config["enabled_languages"])

    # Add custom flag if provided
    if flag_emoji:
        server_config["custom_flags"][lang_code] = flag_emoji
        db.update_server_flags(str(ctx.guild.id), server_config["custom_flags"])
        flag = flag_emoji
    else:
        flag = get_flag_emoji(lang_code, server_config["custom_flags"])

    await ctx.send(f"🌐 Language `{lang_code.upper()}` added with flag {flag}")
    logger.info(f"Language {lang_code} added to server {ctx.guild.id}")


@glupek_group.command(name='remove')
@commands.has_permissions(administrator=True)
async def remove_language(ctx, lang_code: str):
    """Remove a language from translation list"""
    lang_code = lang_code.lower()
    logger.info(f"Admin {ctx.author} removing language: {lang_code}")

    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)

    if lang_code not in server_config["enabled_languages"]:
        await ctx.send(f"Language `{lang_code}` is not enabled.")
        return

    server_config["enabled_languages"].remove(lang_code)
    db.update_server_languages(str(ctx.guild.id), server_config["enabled_languages"])

    if lang_code in server_config["custom_flags"]:
        del server_config["custom_flags"][lang_code]
        db.update_server_flags(str(ctx.guild.id), server_config["custom_flags"])

    await ctx.send(f"🗑️ Language `{lang_code.upper()}` removed.")
    logger.info(f"Language {lang_code} removed successfully")


@glupek_group.command(name='list')
async def list_languages(ctx):
    """List all enabled languages"""
    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)
    enabled = server_config["enabled_languages"]

    lang_list = ", ".join([
        f"{get_flag_emoji(lang, server_config['custom_flags'])} {lang.upper()}"
        for lang in enabled
    ])

    await ctx.send(f"**Enabled languages ({len(enabled)}):**\n{lang_list}")


@glupek_group.command(name='stats')
async def show_stats(ctx, days: int = 30):
    """Show translation statistics for this server"""
    stats = db.get_server_stats(str(ctx.guild.id), days)

    embed = discord.Embed(
            title=f"📊 Translation Statistics (Last {days} days)",
            color=0x5865F2
    )

    embed.add_field(
            name="Total Translations",
            value=f"{stats['total']}",
            inline=True
    )

    embed.add_field(
            name="Successful",
            value=f"{stats['success']} ({stats['success_rate']:.1f}%)",
            inline=True
    )

    if stats['top_languages']:
        top_langs = "\n".join([
            f"{item['lang'].upper()}: {item['count']}"
            for item in stats['top_languages'][:5]
        ])
        embed.add_field(
                name="Most Translated Languages",
                value=top_langs,
                inline=False
        )

    if stats['api_distribution']:
        api_dist = "\n".join([
            f"{api}: {count}"
            for api, count in stats['api_distribution'].items()
        ])
        embed.add_field(
                name="API Usage",
                value=api_dist,
                inline=False
        )

    await ctx.send(embed=embed)


@glupek_group.command(name='quota')
async def show_quota(ctx):
    """Show API usage quota for today"""
    quota = db.get_api_quota_usage()

    embed = discord.Embed(
            title="📈 API Quota Usage (Today)",
            color=0x5865F2
    )

    if quota:
        for api, chars in quota.items():
            embed.add_field(
                    name=api,
                    value=f"{chars:,} characters",
                    inline=True
            )
    else:
        embed.description = "No API usage recorded today."

    await ctx.send(embed=embed)


@glupek_group.command(name='mode')
@commands.has_permissions(administrator=True, manage_channels=True)
async def set_mode(ctx, mode: str):
    """Set translation mode (inline or thread)"""
    mode = mode.lower()
    if mode not in ['inline', 'thread']:
        await ctx.send("❌ Invalid mode. Use `inline` or `thread`.")
        return

    db.update_server_mode(str(ctx.guild.id), mode)
    await ctx.send(f"✅ Translation mode set to `{mode}` for this server.")
    logger.info(f"Server {ctx.guild.id} mode changed to {mode}")


@glupek_group.command(name='bulk')
@commands.has_permissions(administrator=True)
async def bulk_translate(ctx, count: int = 10):
    """Add translation flags to last N messages"""
    if count < 1 or count > 100:
        await ctx.send("❌ Count must be between 1 and 100.")
        return

    await ctx.send(f"🔄 Adding flags to last {count} messages...")

    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)
    enabled = server_config["enabled_languages"]
    priority = global_config["priority_order"]
    server_flags = server_config["custom_flags"]

    sorted_langs = sorted(
            enabled,
            key=lambda x: priority.index(x) if x in priority else 999
    )
    langs_to_add = sorted_langs[:20]

    processed = 0
    async for message in ctx.channel.history(limit=count):
        if message.author.bot:
            continue

        for lang in langs_to_add:
            try:
                emoji = get_flag_emoji(lang, server_flags)
                await message.add_reaction(emoji)
            except:
                pass

        processed += 1

    await ctx.send(f"✅ Added flags to {processed} messages.")


# Store active challenges (message_id -> correct_lang)
active_challenges = {}


@glupek_group.command(name='challenge')
async def start_challenge(ctx):
    """Start a translation guessing game"""
    # Multiple phrases per language to avoid memorization
    phrases = {
        "en": [
            "Hello, how are you?",
            "What a beautiful day!",
            "I love programming.",
            "Where is the library?",
            "Thank you very much!"
        ],
        "fr": [
            "Bonjour, comment allez-vous?",
            "Quelle belle journée!",
            "J'adore la programmation.",
            "Où est la bibliothèque?",
            "Merci beaucoup!"
        ],
        "es": [
            "Hola, ¿cómo estás?",
            "¡Qué día tan hermoso!",
            "Me encanta programar.",
            "¿Dónde está la biblioteca?",
            "¡Muchas gracias!"
        ],
        "de": [
            "Guten Tag, wie geht es Ihnen?",
            "Was für ein schöner Tag!",
            "Ich liebe das Programmieren.",
            "Wo ist die Bibliothek?",
            "Vielen Dank!"
        ],
        "ru": [
            "Привет, как дела?",
            "Какой прекрасный день!",
            "Я люблю программирование.",
            "Где находится библиотека?",
            "Большое спасибо!"
        ],
        "pt": [
            "Olá, como você está?",
            "Que dia lindo!",
            "Eu amo programar.",
            "Onde fica a biblioteca?",
            "Muito obrigado!"
        ],
        "zh": [
            "你好吗？",
            "多么美好的一天！",
            "我喜欢编程。",
            "图书馆在哪里？",
            "非常感谢！"
        ]
    }

    # Pick random language and random phrase
    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)

    # Only use languages that are enabled on this server
    available_langs = [lang for lang in phrases.keys() if lang in server_config["enabled_languages"]]

    if not available_langs:
        await ctx.send("❌ No languages available for challenge. Enable some languages first!")
        return

    correct_lang = random.choice(available_langs)
    phrase = random.choice(phrases[correct_lang])

    embed = discord.Embed(
            title="🎮 Translation Challenge",
            description=f"What language is this?\n\n**{phrase}**",
            color=0x5865F2
    )
    embed.set_footer(text="React with the correct flag!")

    msg = await ctx.send(embed=embed)

    # Store challenge info
    active_challenges[str(msg.id)] = correct_lang

    # Add flag reactions
    for lang in server_config["enabled_languages"]:
        emoji = get_flag_emoji(lang, server_config["custom_flags"])
        try:
            await msg.add_reaction(emoji)
        except Exception as e:
            logger.error(f"Failed to add challenge reaction for {lang}: {e}")


@glupek_group.group(name='dict')
async def dictionary_group(ctx):
    """Manage custom translation dictionary"""
    if ctx.invoked_subcommand is None:
        await ctx.send("Use `!glupek dict add`, `!glupek dict remove`, or `!glupek dict list`")


@dictionary_group.command(name='add')
@commands.has_permissions(administrator=True)
async def dict_add(ctx, term: str, *, translation: str):
    """Add custom translation for slang/terms"""
    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)

    server_config["dictionary"][term] = translation
    db.update_server_dictionary(str(ctx.guild.id), server_config["dictionary"])

    await ctx.send(f"📖 Added: `{term}` → `{translation}`")
    logger.info(f"Dictionary entry added for server {ctx.guild.id}: {term} -> {translation}")


@dictionary_group.command(name='remove')
@commands.has_permissions(administrator=True)
async def dict_remove(ctx, term: str):
    """Remove custom translation"""
    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)

    if term not in server_config["dictionary"]:
        await ctx.send(f"❌ Term `{term}` not found in dictionary.")
        return

    del server_config["dictionary"][term]
    db.update_server_dictionary(str(ctx.guild.id), server_config["dictionary"])

    await ctx.send(f"🗑️ Removed: `{term}`")
    logger.info(f"Dictionary entry removed for server {ctx.guild.id}: {term}")


@dictionary_group.command(name='list')
async def dict_list(ctx):
    """List all custom translations"""
    global_config = load_global_config()
    server_config = db.get_server_config(str(ctx.guild.id), global_config)

    if not server_config["dictionary"]:
        await ctx.send("📖 Custom dictionary is empty.")
        return

    embed = discord.Embed(
            title="📖 Custom Dictionary",
            color=0x5865F2
    )

    for term, translation in server_config["dictionary"].items():
        embed.add_field(
                name=term,
                value=translation,
                inline=False
        )

    await ctx.send(embed=embed)


@glupek_group.command(name='help')
async def show_help(ctx):
    """Show all available commands"""
    embed = discord.Embed(
            title="🌐 Głupek Translation Bot",
            description="Automatic translation bot for multilingual Discord servers",
            color=0x5865F2
    )

    embed.add_field(
            name="📋 Basic Commands",
            value=(
                "`!glupek list` - List enabled languages\n"
                "`!glupek stats [days]` - Show statistics\n"
                "`!glupek quota` - Show API usage\n"
                "`!glupek help` - Show this help"
            ),
            inline=False
    )

    embed.add_field(
            name="⚙️ Admin Commands",
            value=(
                "`!glupek add <lang> [flag]` - Add language\n"
                "`!glupek remove <lang>` - Remove language\n"
                "`!glupek mode <inline|thread>` - Set mode\n"
                "`!glupek bulk <count>` - Add flags to messages\n"
                "`!glupek dict add <term> <translation>` - Add slang\n"
                "`!glupek dict remove <term>` - Remove slang\n"
                "`!glupek dict list` - List custom terms"
            ),
            inline=False
    )

    embed.add_field(
            name="🎮 Fun",
            value="`!glupek challenge` - Translation game",
            inline=False
    )

    embed.add_field(
            name="❓ How It Works",
            value=(
                "1. Bot adds flag reactions to messages\n"
                "2. Click a flag for translation\n"
                "3. Translation appears in thread\n"
                "4. Click again to retry if failed"
            ),
            inline=False
    )

    embed.set_footer(text="Made for multilingual gaming communities")

    await ctx.send(embed=embed)


# Run bot
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN environment variable not set")
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        exit(1)

    logger.info("Starting Głupek bot...")
    bot.run(TOKEN)
