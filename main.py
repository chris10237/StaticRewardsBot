import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask
import threading
import psycopg2 
import urllib.parse 

from discord import app_commands 
# ... (all your existing imports)

# --- REWARD CHOICES CONSTANT ---
REWARD_CHOICES = [
    discord.app_commands.Choice(name="Free Points Reward", value="free_points_reward_count"),
    discord.app_commands.Choice(name="Free Tier List Slot", value="free_tier_list_count"),
    discord.app_commands.Choice(name="Free Watch Video", value="free_watch_video_count"),
    # Add more rewards here following the 'name': 'database_column_name' structure
]
# --- END REWARD CHOICES CONSTANT ---

# --- 1. Configuration & Bot Setup ---
# Load environment variables. IMPORTANT: These MUST be set in Render's dashboard.
token = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
# Replace with your actual Guild ID
GUILD_ID = 559879519087886356
# For adding and removing rewards
ADMIN_USER_ID = 341072622735327232

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
    """
    Creates the 'users' table if it doesn't already exist and ensures a
    case-insensitive unique index on twitch_username.
    """
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        # 1. Ensure the main 'users' table exists.
        create_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            discord_id BIGINT PRIMARY KEY,
            twitch_username VARCHAR(50) NOT NULL
        );
        """
        cursor.execute(create_table_query)

        # 2. Add a CASE-INSENSITIVE UNIQUE INDEX.
        # This index will cause any INSERT/UPDATE that results in a duplicate 
        # (case-insensitive) twitch_username to throw a UniqueViolation error.
        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS 
                unique_twitch_username_lower 
                ON users (LOWER(twitch_username));
            """)
            print("Successfully created/ensured case-insensitive unique index on twitch_username.")
        
        except psycopg2.errors.ProgrammingError as pe:
            conn.rollback() 
            if 'already exists' in str(pe):
                print("Case-insensitive unique index already exists.")
            else:
                # If any other ProgrammingError (like lacking permissions) occurs, we re-raise.
                raise pe 
        
        except psycopg2.errors.UniqueViolation as uv:
            # This is raised IF the index can't be created because of duplicate data 
            # (e.g., 'name' and 'Name' already exist).
            conn.rollback()
            print("----------------------------------------------------------------------------------")
            print("!!! FATAL DB SETUP ERROR: UNIQUE CONSTRAINT VIOLATION !!!")
            print("The case-insensitive index failed because duplicate Twitch names (e.g., 'name' and 'Name') exist in the table.")
            print("You must manually clean the database using the SQL query below, and then restart the bot.")
            print("SQL to find duplicates: SELECT LOWER(twitch_username), COUNT(*) FROM users GROUP BY 1 HAVING COUNT(*) > 1;")
            print("----------------------------------------------------------------------------------")
            return
            
        # 3. Add Reward Columns (Your existing logic)
        # ... (Your logic for adding reward columns remains here) ...

        # --- REWARD COLUMN LOGIC REMAINS HERE ---
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN free_points_reward_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
            
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN free_tier_list_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN free_watch_video_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
        # --- END REWARD COLUMN LOGIC ---
            
        conn.commit()
        print("Database table 'users' setup and commit complete.")
        
    except Exception as e:
        print(f"FATAL ERROR setting up database table or columns: {e}")
    finally:
        cursor.close()
        conn.close()

def save_user_registration(discord_id: int, twitch_username: str):
    """
    Saves or updates the user's registration data, relying on the UNIQUE INDEX 
    to reject duplicate twitch_usernames across all users (case-insensitively).
    """
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed."

    cursor = conn.cursor()
    try:
        # Use ON CONFLICT to handle both new registration (INSERT) and existing user (UPDATE).
        # discord_id is the PRIMARY KEY. If it conflicts (user exists), we UPDATE the username.
        # If the UPDATE/INSERT fails due to a UNIQUE INDEX violation on LOWER(twitch_username), 
        # it will be caught by the except block below.

        query = """
        INSERT INTO users (discord_id, twitch_username)
        VALUES (%s, %s)
        ON CONFLICT (discord_id) DO UPDATE SET
            twitch_username = EXCLUDED.twitch_username;
        """
        cursor.execute(query, (discord_id, twitch_username))

        # Check if the user was updated or inserted
        action = "updated" if cursor.rowcount == 0 else "registered"
        
        conn.commit()
        return True, f"Registration successful (name {action})."
            
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        # This is the expected and correct error if the twitch_username is already taken 
        # by another discord_id due to the case-insensitive index on LOWER(twitch_username).
        return False, f"The Twitch name **{twitch_username}** is already registered by another user. Please choose a unique name."

    except Exception as e:
        conn.rollback()
        # Log unexpected errors
        print(f"FATAL ERROR saving registration for {discord_id}: {e}")
        return False, f"An unexpected database error occurred during registration. Please alert the bot owner."
            
    finally:
        cursor.close()
        conn.close()

def get_user_registration(discord_id: int):
    # ... (No changes here, function remains the same) ...
    """Retrieves the user's registration data from the database."""
    conn = get_db_connection()
    if not conn:
        return None

    cursor = conn.cursor()
    try:
        # SQL statement to select the twitch_username for the given discord_id
        select_query = """
        SELECT twitch_username FROM users
        WHERE discord_id = %s;
        """
        cursor.execute(select_query, (discord_id,))
        
        # fetchone() returns the next row as a tuple (or None if no row is found)
        result = cursor.fetchone()
        
        # If a result is found, return the username (which is the first element of the tuple)
        if result:
            return result[0]
        else:
            return None # User not found
            
    except Exception as e:
        print(f"Error retrieving registration from database: {e}")
        return None
        
    finally:
        cursor.close()
        conn.close()

def increment_user_reward(twitch_username: str, reward_column: str):
    # ... (No changes here, function remains the same) ...
    """Increments the count for a specific reward column for a given user."""
    twitch_username = twitch_username.lower()
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed."
    
    cursor = conn.cursor()
    try:
        # IMPORTANT: Column names cannot be parameterized with %s, so we must 
        # validate the input and format the SQL string. We rely on the calling
        # function to provide only valid reward_column names.
        
        # 1. Look up the discord_id first using the twitch_username
        cursor.execute("SELECT discord_id FROM users WHERE twitch_username = %s;", (twitch_username,))
        result = cursor.fetchone()
        
        if not result:
            return False, f"Twitch user '{twitch_username}' not found in the database."
            
        discord_id = result[0]
        
        # 2. Increment the specified column count
        # Ensure the column name is safe and valid before formatting the SQL
        # This is a critical security step for dynamic column names.
        valid_columns = ['free_points_reward_count', 'free_tier_list_count', 'free_watch_video_count']
        if reward_column not in valid_columns:
            return False, f"Invalid reward column name: {reward_column}"
        
        update_query = f"""
        UPDATE users 
        SET {reward_column} = {reward_column} + 1 
        WHERE discord_id = %s
        RETURNING {reward_column};
        """
        
        cursor.execute(update_query, (discord_id,))
        new_count = cursor.fetchone()[0] # Get the updated count
        conn.commit()
        
        return True, f"Reward incremented! New count for '{reward_column}' is **{new_count}**."
        
    except Exception as e:
        print(f"Error incrementing reward for {twitch_username}: {e}")
        return False, f"An unexpected database error occurred: {e}"
        
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
    
    # *** FIX APPLIED: This method is now correctly indented inside the class ***
    async def on_submit(self, interaction: discord.Interaction):
        """Called when the user submits the modal form."""
        await interaction.response.defer(ephemeral=True)
        
        # Get the input value (keep the original casing for storage)
        twitch_name_raw = self.twitch_username_input.value.strip()
        discord_id = interaction.user.id
        
        # Save the data (handle the status returned by the DB function)
        # *** CHANGE: Pass the original, case-sensitive name to the function. ***
        success, message = save_user_registration(discord_id, twitch_name_raw) 
        
        # Send confirmation or error based on the result
        if success:
            await interaction.followup.send(
                # Use the original (raw) name for display
                f"✅ **Success!** Your Twitch username (`{twitch_name_raw}`) has been registered and linked to your Discord account.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ **Registration Failed:** {message}",
                ephemeral=True
            )

# --- 2. Discord Bot Events and Commands ---

@bot.event
async def on_ready():
    """Called when the bot connects to Discord."""
    print(f"Bot connected as {bot.user.name} ({bot.user.id})")

    # --- Setup the database connection and table on startup ---
    setup_db()
    # -----------------------------------------------------------------
    
    # Sync commands to the specified guild (fastest method)
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Commands synced successfully!")
    except Exception as e:
        print(f"failed to sync commands: {e}")
    print("---------------------------------------------")

# --- ADMIN COMMAND --- 

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="add-reward", 
    description="[ADMIN ONLY] Adds a reward count to a registered user."
)
@app_commands.describe(
    twitch_name="The registered Twitch username of the recipient.",
    reward="The specific reward to be added."
)
@app_commands.choices(reward=REWARD_CHOICES)
async def add_reward_command(
    interaction: discord.Interaction, 
    twitch_name: str, 
    reward: app_commands.Choice[str]
):
    # ... (Command logic remains the same) ...
    """Admin command to increment a user's reward count."""
    
    # 1. ADMIN CHECK (Authorization)
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message(
            "🛑 **Authorization Failed.** This command is restricted to the bot owner.", 
            ephemeral=True
        )
        return

    # Defer the response as we are talking to the database
    await interaction.response.defer(ephemeral=True) 
    
    # Get the database column name from the choice value
    reward_column = reward.value 
    reward_name = reward.name
    
    # 2. Call the new synchronous DB function
    success, message = increment_user_reward(twitch_name.strip(), reward_column)

    # 3. Send the response
    if success:
        await interaction.followup.send(
            f"✅ **Reward Added!**\n"
            f"**Recipient:** `{twitch_name}`\n"
            f"**Reward:** `{reward_name}`\n"
            f"**Status:** {message}", # The message contains the new count
            ephemeral=True
        )
    else:
        # This handles Twitch user not found or a database error
        await interaction.followup.send(
            f"❌ **Failed to Add Reward**\n"
            f"**Reason:** {message}",
            ephemeral=True
        )

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="register", 
    description="Register your Twitch username with the bot."
)
async def register_command(interaction: discord.Interaction):
    """Presents a Modal form to the user to collect their Twitch username."""
    await interaction.response.send_modal(TwitchRegistrationModal())

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="my-twitch-name", 
    description="Shows the Twitch username you have registered with the bot."
)
async def get_registration_command(interaction: discord.Interaction):
    # ... (Command logic remains the same) ...
    """Retrieves and displays the user's registered Twitch username."""
    # Defer the response, but keep it ephemeral (only the user sees the output)
    await interaction.response.defer(ephemeral=True) 

    discord_id = interaction.user.id
    
    # 1. Call the new synchronous DB function
    twitch_name = get_user_registration(discord_id) 

    # 2. Construct and send the response
    if twitch_name:
        await interaction.followup.send(
            f"🔎 **Found it!** Your registered Twitch username is: `{twitch_name}`",
            ephemeral=True
        )
    else:
        # User is not registered
        await interaction.followup.send(
            "❌ **Not Found.** You don't appear to be registered yet. Use `/register` to link your account!",
            ephemeral=True
        )

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
