import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask
import threading # <-- We use threading to safely run the bot

# --- Configuration & Bot Setup ---
# NOTE: Ensure DISCORD_TOKEN and GUILD_ID are set in Render's environment variables.
token = os.getenv('DISCORD_TOKEN')
GUILD_ID = 559879519087886356 

# Intents
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True

bot = commands.Bot(command_prefix=None, intents = intents)

# --- Discord Bot Events and Commands ---

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
    # Defer the response immediately to beat the 3-second timeout
    await interaction.response.defer(ephemeral=False)
    
    # Simulate a small task delay (ensure it's not the cause of the timeout)
    await asyncio.sleep(0.5) 
    
    # Use followup.send() after deferring
    await interaction.followup.send(f"Hello, {interaction.user.name}! (Successful response!)", ephemeral=False)

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

# --- Flask Web Server Setup ---
app = Flask(__name__) # The Flask application instance is named 'app'

# --- Discord Bot Runner Function ---
def start_bot():
    """Starts the Discord bot client in a dedicated thread."""
    print("Starting Discord Bot in a new thread...")
    try:
        # bot.run() is a blocking call, so it must be run in a separate thread.
        bot.run(token)
    except Exception as e:
        print(f"Error running Discord Bot: {e}")

# --- Flask Bot Integration (The Critical Part) ---
@app.before_request
def run_bot_on_start():
    """Launches the bot thread right before the web server begins serving."""
    # The Gunicorn worker process will execute this once before serving requests.
    t = threading.Thread(target=start_bot)
    t.start()
    print("Discord Bot thread initiated successfully.")

@app.route('/')
def home():
    # This endpoint confirms to Render that the web service is running.
    return "Discord Bot is Online and Healthy!"

# --- No if __name__ == '__main__': block is needed! ---
# Gunicorn handles the startup by importing and running the 'app' instance directly.