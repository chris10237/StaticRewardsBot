import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask
import threading
import json

# --- 1. Configuration & Bot Setup ---
# Load environment variables. IMPORTANT: These MUST be set in Render's dashboard.
token = os.getenv('DISCORD_TOKEN')
# Replace with your actual Guild ID
GUILD_ID = 559879519087886356 
USERS_FILE = 'registered_users.json'

# Intents
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True

bot = commands.Bot(command_prefix=None, intents = intents)

# --- 2. Discord Bot Events and Commands ---

def save_user_registration(discord_id: str, twitch_username: str):
    """Loads, updates, and saves the user data to the JSON file."""
    # Ensure this runs synchronously to manage file access
    discord_id_str = str(discord_id)
    try:
        # 1. Load existing data
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Start with an empty dictionary if file doesn't exist or is empty/corrupted
        data = {}

    # 2. Update the data (Discord ID is the key)
    data[discord_id_str] = twitch_username

    # 3. Save the updated data
    with open(USERS_FILE, 'w') as f:
        # Use indent=4 for human-readable JSON
        json.dump(data, f, indent=4)

class TwitchRegistrationModal(discord.ui.Modal, title='Register Your Twitch'):
    """A Discord Modal for collecting the user's Twitch username."""
    
    # This is the required text input component for the form
    twitch_username_input = discord.ui.TextInput(
        label='Your Twitch Username (Case Sensitive)',
        placeholder='e.g., Shroud or Amouranth',
        max_length=50,
        required=True,
        style=discord.TextStyle.short
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """Called when the user submits the modal form."""
        await interaction.response.defer(ephemeral=True) # Defer the response immediately
        
        # Get the input value
        twitch_name = self.twitch_username_input.value.strip()
        discord_id = interaction.user.id
        
        # Save the data (using our helper function)
        save_user_registration(discord_id, twitch_name)
        
        # Send confirmation
        await interaction.followup.send(
            f"✅ **Success!** Your Twitch username (`{twitch_name}`) has been registered and linked to your Discord account.",
            ephemeral=True
        )

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
    name="register", 
    description="Register your Twitch username with the bot."
)
async def register_command(interaction: discord.Interaction):
    """Presents a Modal form to the user to collect their Twitch username."""
    # Instantiates the modal and sends it to the user
    await interaction.response.send_modal(TwitchRegistrationModal())

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="hello", 
    description="Says hello back to the user!"
)
async def hello_command(interaction: discord.Interaction):
    """Says hello back to the user."""
    # Defer the response immediately to beat the 3-second timeout
    await interaction.response.defer(ephemeral=False)
    
    # Simulate a small task delay
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

# --- 3. Flask Web Server Setup ---
app = Flask(__name__) # The Flask application instance is named 'app'

# --- 4. Discord Bot Runner Function (Revised for Stability) ---
def start_bot():
    """Starts the Discord bot client in a dedicated thread."""
    print("Starting Discord Bot in a new thread...")
    try:
        # bot.run() is a blocking call, so it must be run in a separate thread.
        # log_handler=None helps prevent the 'was never awaited' warning on shutdown.
        bot.run(token, log_handler=None) 
    except discord.LoginFailure:
        print("FATAL ERROR: Bot login failed. Check your DISCORD_TOKEN.")
    except Exception as e:
        # Catching startup errors, letting benign shutdown errors (like the RuntimeWarning) pass silently.
        print(f"FATAL STARTUP ERROR: {e}")

# --- 5. Flask Bot Integration (The Critical Launch Point) ---
@app.before_request
def run_bot_on_start():
    """Launches the bot thread right before the web server begins serving."""
    # We check if the thread is already running to avoid launching it multiple times
    # in environments where before_request might be hit prematurely.
    if not any(t.name == "discord_bot_thread" for t in threading.enumerate()):
        t = threading.Thread(target=start_bot, name="discord_bot_thread")
        t.start()
        print("Discord Bot thread initiated successfully.")

@app.route('/')
def home():
    """Health check endpoint required by Render."""
    return "Discord Bot is Online and Healthy!"

# --- Final Instructions for Deployment ---
# 1. Save this code as 'main.py'.
# 2. Set the Render Start Command to: 
#    gunicorn --worker-class gevent --bind 0.0.0.0:$PORT main:app