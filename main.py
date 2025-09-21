import logging
import os

from dotenv import load_dotenv

from modules.CurrencyBot import CurrencyBot

# Loads environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)

# Run the bot with your token
bot: CurrencyBot = CurrencyBot()
bot.run(os.getenv("TOKEN"))
