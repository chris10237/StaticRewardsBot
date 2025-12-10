import discord
from discord.ext import commands
import os
import asyncio
import logging

# Removed: nest_asyncio is not strictly needed with this modern asyncio approach.

# --- 1. Flask Web Server Setup ---
# Required for Render to keep the service alive by listening on the assigned port.
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    # This endpoint confirms to Render/Health Checks that the service is running.
    return "Discord Bot is Online and Healthy!"

def run_web_server():
    """Binds the Flask app to the port provided by the environment."""
    port = int(os.environ.get('PORT', 5000))
    # host='0.0.0.0' is necessary for deployment environments.
    app.run(host='0.0.0.0', port=port)

# --- 2. Discord Bot Configuration ---
# NOTE: Ensure DISCORD_TOKEN and GUILD_ID are set in Render's environment variables.

token = os.getenv('DISCORD_TOKEN')
# IMPORTANT: Replace this with your actual test server ID!
GUILD_ID = 559879519087886356 

# Logging setup (Good practice, but can be simplified if preferred)
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.INFO) # Set to INFO for cleaner logs
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
discord_logger.addHandler(handler)

# Intents
intents = discord.Intents.default()
# intents.message_content is needed for text commands, but not strictly for slash commands.
# intents.members is not strictly needed unless you are reading member data.
intents.message_content = True 
intents.members = True

bot = commands.Bot(command_prefix=None, intents = intents)

# --- 3. Discord Bot Events and Commands ---

@bot.event
async def on_ready():
    """Called when the bot connects to Discord."""
    print(f"Bot connected as {bot.user.name} ({bot.user.id})")
    
    # Sync commands to the specified guild (fastest method)
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Commands synced successfully!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print("---------------------------------------------")

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID),
    name="hello", 
    description="Says hello back to the user!"
)
async def hello_command(interaction: discord.Interaction):
    """Says hello back to the user."""
    
    # *** CRITICAL FIX: Defer the response immediately to beat the 3-second timeout ***
    await interaction.response.defer(ephemeral=False)
    
    # Your main logic here. I've added a small sleep to simulate a quick task.
    await asyncio.sleep(0.5) 
    
    # Use followup.send() after deferring
    await interaction.followup.send(f"Hello, {interaction.user.name}! (Slash Command Response)", ephemeral=False)

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="goodbye", 
    description="Says goodbye back to the user!"
)
async def goodbye_command(interaction: discord.Interaction):
    """Says goodbye back to the user."""
    await interaction.response.defer(ephemeral=False)
    await asyncio.sleep(0.5) 
    await interaction.followup.send(f"fuk u {interaction.user.name}! (Goodbye message)", ephemeral=False)
    
# --- 4. Main Entry Point (Concurrent Startup) ---

async def start_web_server_async():
    """Runs the blocking Flask server in a managed background thread."""
    print("Starting Flask web server on a background thread...")
    # asyncio.to_thread runs the blocking function without blocking the main event loop.
    await asyncio.to_thread(run_web_server)
    print("Flask web server stopped.")

def run_discord_bot():
    """Starts the bot and the web server concurrently."""
    try:
        loop = asyncio.get_event_loop()
        
        # Schedule the web server task
        web_server_task = loop.create_task(start_web_server_async())
        
        # Start the bot, which runs the main asyncio loop
        bot.run(token)
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    run_discord_bot()