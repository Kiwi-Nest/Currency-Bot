import os

from dotenv import load_dotenv

from CurrencyBot import CurrencyBot

# Loads environment variables
load_dotenv()

# Run the bot with your token
bot: CurrencyBot = CurrencyBot()
bot.run(os.getenv('TOKEN'))