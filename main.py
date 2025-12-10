import discord
from discord.ext import commands
import logging
#from dotenv import load_dotenv
import os
import asyncio

from flask import Flask

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

async def start_web_server_async():
    """Runs the Flask server in a separate thread managed by the bot's event loop."""
    print("Starting Flask web server on a background thread...")
    # This runs the blocking run_web_server function in a separate thread.
    # It will not block the bot's main asyncio loop.
    await asyncio.to_thread(run_web_server)
    print("Flask web server stopped.")    

def run_discord_bot():
    """Starts the bot and the web server concurrently."""
    print("Starting Discord Bot...")
    # 1. Prepare to run the web server task
    try:
        # 2. Get the current event loop
        loop = asyncio.get_event_loop()
        
        # 3. Create the task for the web server
        web_server_task = loop.create_task(start_web_server_async())
        
        # 4. Start the bot (bot.run is a blocking call that runs the event loop)
        bot.run(token)
        
    except RuntimeError as e:
        if "Cannot call write() on a closed stream" in str(e):
            print("Bot stopped successfully despite minor stream error during shutdown.")
        else:
            raise

        
if __name__ == '__main__':
    run_discord_bot()
        
