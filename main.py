import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask
import threading
import psycopg2 # <--- NEW: Import for PostgreSQL driver
import urllib.parse # <--- NEW: Import for parsing the URL

# --- 1. Configuration & Bot Setup ---
# Load environment variables. IMPORTANT: These MUST be set in Render's dashboard.
token = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL') # <--- NEW: Get the database URL
# Replace with your actual Guild ID
GUILD_ID = 559879519087886356

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=None, intents = intents)

# --- NEW: PostgreSQL Helper Functions ---

def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        print("FATAL ERROR: DATABASE_URL environment variable is not set. Cannot connect to DB.")
        return None
    try:
        # psycopg2 can use the full URL format directly
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"FATAL ERROR: Failed to connect to database: {e}")
        return None

def setup_db():
    """Creates the 'users' table if it doesn't already exist."""
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        # SQL command to create the table. discord_id is BIGINT (Discord IDs are large numbers).
        create_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            discord_id BIGINT PRIMARY KEY,
            twitch_username VARCHAR(50) NOT NULL
        );
        """
        cursor.execute(create_table_query)
        conn.commit()
        print("Database table 'users' ensured to exist.")
    except Exception as e:
        print(f"Error setting up database table: {e}")
    finally:
        cursor.close()
        conn.close()

def save_user_registration(discord_id: int, twitch_username: str):
    """Saves or updates the user's registration data in the database."""
    conn = get_db_connection()
    if not conn:
        return
    
    cursor = conn.cursor()
    try:
        # This SQL statement inserts a new record. If a record with that discord_id 
        # already exists, it updates the twitch_username instead.
        insert_update_query = """
        INSERT INTO users (discord_id, twitch_username) 
        VALUES (%s, %s)
        ON CONFLICT (discord_id) DO UPDATE 
        SET twitch_username = EXCLUDED.twitch_username;
        """
        
        cursor.execute(insert_update_query, (discord_id, twitch_username))
        conn.commit()
        print(f"DB Action: Discord ID {discord_id} registered/updated with Twitch: {twitch_username}")
    except Exception as e:
        print(f"Error saving registration to database: {e}")
    finally:
        cursor.close()
        conn.close()

# --- NEW: Discord Modal Implementation ---

class TwitchRegistrationModal(discord.ui.Modal, title='Register Your Twitch'):
    """A Discord Modal for collecting the user's Twitch username."""
    
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
        
        # Save the data (using the new DB function)
        save_user_registration(discord_id, twitch_name)
        
        # Send confirmation
        await interaction.followup.send(
            f"✅ **Success!** Your Twitch username (`{twitch_name}`) has been registered and linked to your Discord account.",
            ephemeral=True
        )

# --- 2. Discord Bot Events and Commands ---

@bot.event
async def on_ready():
    """Called when the bot connects to Discord."""
    print(f"Bot connected as {bot.user.name} ({bot.user.id})")

    # --- NEW: Setup the database connection and table on startup ---
    setup_db()
    # -----------------------------------------------------------------
    
    # Sync commands to the specified guild (fastest method)
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Commands synced successfully!")
    except Exception as e:
        print(f"failed to sync commands: {e}")
    print("---------------------------------------------")


@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="register", 
    description="Register your Twitch username with the bot."
)
async def register_command(interaction: discord.Interaction):
    """Presents a Modal form to the user to collect their Twitch username."""
    await interaction.response.send_modal(TwitchRegistrationModal())


# --- Existing Commands (No changes needed) ---

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

# --- 3. Flask Web Server Setup (No changes needed) ---
app = Flask(__name__) # The Flask application instance is named 'app'

# --- 4. Discord Bot Runner Function (No changes needed) ---
def start_bot():
    """Starts the Discord bot client in a dedicated thread."""
    print("Starting Discord Bot in a new thread...")
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        print("FATAL ERROR: Bot login failed. Check your DISCORD_TOKEN.")
    except Exception as e:
        print(f"FATAL STARTUP ERROR: {e}")

# --- 5. Flask Bot Integration (No changes needed) ---
@app.before_request
def run_bot_on_start():
    """Launches the bot thread right before the web server begins serving."""
    if not any(t.name == "discord_bot_thread" for t in threading.enumerate()):
        t = threading.Thread(target=start_bot, name="discord_bot_thread")
        t.start()
        print("Discord Bot thread initiated successfully.")

@app.route('/')
def home():
    """Health check endpoint required by Render."""
    return "Discord Bot is Online and Healthy!"