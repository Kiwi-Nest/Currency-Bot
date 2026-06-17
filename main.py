import logging

# Linux sandbox before continuing
try:
    from landlock import Ruleset
except ImportError:
    logging.warning("Skipping sandboxing.")  # noqa: LOG015
else:
    rs = Ruleset()
    rs.allow(".")
    rs.allow("/usr/lib64")
    rs.allow("/etc")  # resolve domains
    rs.allow("/usr/share/zoneinfo/")
    rs.allow("/proc/self")
    rs.apply()
    logging.info("Succeeded sandboxing.")  # noqa: LOG015

import discord
from dotenv import load_dotenv

from modules.BotCore import BotCore
from modules.config import BotConfig

# Loads environment variables
load_dotenv()

# Temporary: owner bypasses all local app-command permission checks
_original_check_can_run = discord.app_commands.Command._check_can_run


async def _owner_bypass(self, interaction: discord.Interaction) -> bool:  # noqa: ANN001
    if await interaction.client.is_owner(interaction.user):
        return True
    return await _original_check_can_run(self, interaction)


discord.app_commands.Command._check_can_run = _owner_bypass


# 1. Create and configure your file handler separately.
# Using 'a' for append mode is a good choice.
file_handler = logging.FileHandler(filename="bot.log", encoding="utf-8", mode="a")
dt_fmt = "%Y-%m-%d %H:%M:%S"
formatter = logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{")
file_handler.setFormatter(formatter)

# 2. Call setup_logging WITHOUT the handler kwarg to get the default console logger.
# root=True ensures your cogs' loggers are also configured for the console.
discord.utils.setup_logging(level=logging.INFO, root=True)

# 3. Add your file handler to the root logger.
logging.getLogger().addHandler(file_handler)

# Get the top-level logger for your application
log = logging.getLogger(__name__)

try:
    # Create the config from environment first
    config = BotConfig.from_environment()

    # Pass the config object into the bot's constructor
    bot = BotCore(config=config)

    bot.run(config.token)

except KeyError, ValueError:
    log.exception(
        "A critical configuration error occurred. Please check your environment variables.",
    )
