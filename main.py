import discord
from discord.ext import commands
import logging
#from dotenv import load_dotenv
import os
import asyncio
import threading

from flask import Flask
import nest_asyncio
nest_asyncio.apply() # This patches the event loop

app = Flask(__name__)

@app.route('/')
def home():
    # This endpoint will be pinged by UptimeRobot to keep the service awake.
    return "Discord Bot is Online and Healthy!"

def run_web_server():
    # Render provides the port via the environment variable 'PORT'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

#load_dotenv()
token = os.getenv('DISCORD_TOKEN')
GUILD_ID = 559879519087886356

discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.DEBUG)

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))

discord_logger.addHandler(handler)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=None, intents = intents)

@bot.event
async def on_ready():
    print(f"AAAAAAAAAAAAAAAAAA, {bot.user.name}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print("Commands synced successfully!")
    print("---------------------------------------------")
    print("Only slash commands will work now (e.g., /hello).")

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), # Associates this command ONLY with your test server
    name="goodbye", 
    description="Says goodbye back to the user!"
)
async def hello(interaction: discord.Interaction):
    """Says hello back to the user."""
    # When using tree.command, you must respond to the interaction directly.
    await interaction.response.send_message(f"fuk u {interaction.user.name}! AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", ephemeral=False)
  
def run_discord_bot():
    try:
        bot.run(token)
    except RuntimeError as e:
        if "Cannot call write() on a closed stream" in str(e):
            print("Bot stopped successfully despite minor stream error during shutdown.")
        else:
            raise

        
if __name__ == '__main__':
    # 1. Start the Flask web server in a separate background thread
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True # Allows the thread to exit when the main program exits
    web_thread.start()
    
    # 2. Start the Discord bot in the main thread
    # NOTE: Since the web server is running in a thread, the main thread is free
    # to be taken over by Gunicorn/the main process loop.
    run_discord_bot()
        
