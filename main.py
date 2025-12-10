import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask

# --- Flask Web Server Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is Online and Healthy!"

def run_web_server():
    """Binds the Flask app to the port provided by the environment."""
    port = int(os.environ.get('PORT', 5000))
    print(f"Flask running on 0.0.0.0:{port}")
    # We are using app.run for simplicity, relying on asyncio.to_thread
    app.run(host='0.0.0.0', port=port)

# --- Discord Bot Configuration & Commands (Same as last time) ---
token = os.getenv('DISCORD_TOKEN')
GUILD_ID = 559879519087886356 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=None, intents = intents)

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user.name} ({bot.user.id})")
    try:
        # Use guild sync (since it worked locally, this should work)
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Commands synced successfully!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="hello", 
    description="Says hello back to the user!"
)
async def hello_command(interaction: discord.Interaction):
    # Defer is the safety net
    await interaction.response.defer(ephemeral=False)
    await asyncio.sleep(0.5) 
    await interaction.followup.send(f"Hello, {interaction.user.name}! (Successful response!)", ephemeral=False)

# --- Main Entry Point (Concurrent Startup) ---

async def start_web_server_async():
    """Runs the blocking Flask server in a managed background thread."""
    await asyncio.to_thread(run_web_server)

def run_discord_bot():
    """Starts the bot and the web server concurrently."""
    try:
        loop = asyncio.get_event_loop()
        
        # Schedule the web server task
        loop.create_task(start_web_server_async())
        
        # Start the bot, which runs the main asyncio loop
        bot.run(token)
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    run_discord_bot()