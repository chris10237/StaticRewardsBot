import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask
import threading
import psycopg2 
from datetime import datetime
import pytz

from discord import app_commands

REWARD_CHOICES = [
    discord.app_commands.Choice(name="Free Points Reward", value="free_points_reward_count"),
    discord.app_commands.Choice(name="Tier List", value="tier_list_count"),
    discord.app_commands.Choice(name="Watch Video", value="watch_video_count"),
    discord.app_commands.Choice(name="Replay Analysis", value="replay_analysis_count"),
    discord.app_commands.Choice(name="Listen to Album", value="album_count"),
    discord.app_commands.Choice(name="DJ Rest of Stream", value="dj_count"),
    discord.app_commands.Choice(name="Song Request Rest of Stream", value="song_request_count"),
    discord.app_commands.Choice(name="Shuffle Artist of your Choice", value="shuffle_count"),
    discord.app_commands.Choice(name="Play Marbles on Stream", value="marbles_count"),
    discord.app_commands.Choice(name="Play 5 Games of 1v1", value="ones_count"),
    discord.app_commands.Choice(name="Play Jackbox", value="jackbox_count"),
    discord.app_commands.Choice(name="Play 5 games of KBM", value="kbm_count"),
    discord.app_commands.Choice(name="Cast your RL Game", value="cast_count"),
    # Add more rewards here following the 'name': 'database_column_name' structure
]

VALID_REWARD_COLUMNS = [choice.value for choice in REWARD_CHOICES]

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

# --- PostgreSQL Helper Functions ---

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

def log_reward_activity(discord_id: int, log_message: str):
    """
    Performs the log rotation (shifts log 1 to 2, 2 to 3, and writes new log to 1).
    """
    conn = get_db_connection()
    if not conn:
        print(f"Failed to log activity for {discord_id}: DB connection failed.")
        return

    cursor = conn.cursor()

    eastern_time_zone = pytz.timezone('America/New_York')

    now_et = datetime.now(eastern_time_zone)
    
    # 1. Format the new log entry with the current timestamp
    # We use a concise format to save space: M-D H:M
    timestamp = now_et.strftime("%m-%d %H:%M %Z") # %Z gives the timezone name (EST/EDT)
    
    # Prepend the timestamp to the message. The color/sign is already in the message.
    full_log_entry = f"**[{timestamp}]** {log_message}" 
    
    try:
        # The rotation query: Shift 2->3, 1->2, then insert the new entry into 1
        update_query = """
        UPDATE users
        SET
            log_recent_3 = log_recent_2,
            log_recent_2 = log_recent_1,
            log_recent_1 = %s
        WHERE
            discord_id = %s;
        """
        cursor.execute(update_query, (full_log_entry, discord_id))
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"FATAL ERROR logging activity for {discord_id}: {e}")
        
    finally:
        cursor.close()
        conn.close()

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
                # If any other ProgrammingError (like lacking) occurs, we re-raise.
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

        # --- REWARD COLUMN LOGIC (add more rewards here after adding them above)---
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN free_points_reward_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
            
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN tier_list_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN watch_video_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN replay_analysis_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN album_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN dj_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN song_request_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN shuffle_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN marbles_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN ones_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN jackbox_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN kbm_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN cast_count INT DEFAULT 0;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
        # --- END REWARD COLUMN LOGIC ---

        # --- LOG COLUMN LOGIC ---
        try:
            # log_recent_1, log_recent_2, log_recent_3 are TEXT columns (default to NULL)
            cursor.execute("ALTER TABLE users ADD COLUMN log_recent_1 TEXT;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN log_recent_2 TEXT;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN log_recent_3 TEXT;")
        except psycopg2.errors.DuplicateColumn:
            conn.rollback()
        # --- END LOG COLUMN LOGIC ---
            
        conn.commit()
        print("Database table 'users' setup and commit complete.")
        
    except Exception as e:
        print(f"FATAL ERROR setting up database table or columns: {e}")
    finally:
        cursor.close()
        conn.close()

def save_user_registration(discord_id: int, twitch_username: str):
    """
    Saves or updates the user's registration data, ensuring the stored username is lowercase.
    """
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed."

    cursor = conn.cursor()
    try:
        # CHECK FOR DUPLICATE TWITCH NAME (Case-Insensitive Check) ---
        check_query = """
        SELECT discord_id 
        FROM users 
        WHERE LOWER(twitch_username) = %s AND discord_id != %s;
        """
        # Ensure parameters are passed as a tuple in the correct order:
        cursor.execute(check_query, (twitch_username, discord_id))
        
        if cursor.fetchone() is not None:
            conn.rollback()
            return False, f"The Twitch name **{twitch_username}** is already registered by another user. Please choose a unique name."
            
        # --- STEP 2: PERFORM INSERT/UPDATE (Save the lowercase name) ---
        
        query = """
        INSERT INTO users (discord_id, twitch_username)
        VALUES (%s, %s)
        ON CONFLICT (discord_id) DO UPDATE SET
            twitch_username = EXCLUDED.twitch_username;
        """
        cursor.execute(query, (discord_id, twitch_username))

        action = "updated" if cursor.rowcount == 0 else "registered"
        
        conn.commit()
        return True, f"Registration successful (name {action})."
            
    except Exception as e:
        conn.rollback()
        print(f"FATAL ERROR saving registration for {discord_id}: {e}")
        raise 
            
    finally:
        cursor.close()
        conn.close()

def get_user_registration(discord_id: int):
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

def get_user_rewards(discord_id: int) -> dict | None:
    """
    Retrieves the user's reward counts AND log entries, returned as a dictionary.
    Returns None if the user is not found.
    """
    conn = get_db_connection()
    if not conn:
        print("Database connection failed in get_user_rewards.")
        return None

    # Get the list of all reward column names
    reward_columns = VALID_REWARD_COLUMNS
    
    log_columns = ["log_recent_1", "log_recent_2", "log_recent_3"]
    
    # Combine reward and log columns for the SELECT query
    all_columns = reward_columns + log_columns
    
    select_query = f"""
    SELECT discord_id, {', '.join(all_columns)} 
    FROM users
    WHERE discord_id = %s;
    """

    cursor = conn.cursor()
    try:
        cursor.execute(select_query, (discord_id,))
        result = cursor.fetchone()
        
        if not result:
            return None # User not found
            
        # The column names are available via cursor.description
        column_names = [desc[0] for desc in cursor.description]
        
        # Create a dictionary mapping column names to their values
        user_data = dict(zip(column_names, result))
        
        return user_data
            
    except Exception as e:
        print(f"Error retrieving user rewards for {discord_id}: {e}")
        return None
            
    finally:
        cursor.close()
        conn.close()

def increment_user_reward(twitch_username: str, reward_column: str):
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

        if reward_column not in VALID_REWARD_COLUMNS: 
            return False, f"Invalid reward column name: {reward_column}"
        
        update_query = f"""
        UPDATE users 
        SET {reward_column} = {reward_column} + 1 
        WHERE discord_id = %s
        RETURNING {reward_column};
        """

        # We need the user-friendly reward name, so we look it up from the column value
        reward_name = next(c.name for c in REWARD_CHOICES if c.value == reward_column)
        
        cursor.execute(update_query, (discord_id,))
        new_count = cursor.fetchone()[0] # Get the updated count
        conn.commit()

        log_msg = f"🟢 '{reward_name}' added to inventory."
        log_reward_activity(discord_id, log_msg)
        
        return True, f"Reward incremented! New count for '{reward_column}' is **{new_count}**."
        
    except Exception as e:
        print(f"Error incrementing reward for {twitch_username}: {e}")
        return False, f"An unexpected database error occurred: {e}"
        
    finally:
        cursor.close()
        conn.close()

def decrement_user_reward(twitch_username: str, reward_column: str):
    """
    Decrements the count for a specific reward column for a given user, 
    but ensures the count does not drop below zero.
    """
    # 1. Normalize the input name for lookup (since stored names are lowercase)
    twitch_username = twitch_username.lower()
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed."
    
    cursor = conn.cursor()
    try:
        # --- 1. VALIDATION AND LOOKUP ---
        # 1a. Look up the discord_id first using the twitch_username
        # This uses a case-insensitive lookup since all stored names are lowercase
        cursor.execute("SELECT discord_id, {} FROM users WHERE twitch_username = %s;".format(reward_column), (twitch_username,))
        result = cursor.fetchone()
        
        if not result:
            return False, f"Twitch user '{twitch_username}' not found in the database."
            
        discord_id = result[0]
        current_count = result[1]

        # 1b. Check the reward constraint (must be greater than 0)
        if current_count <= 0:
            return False, f"The user **{twitch_username}** currently has **0** rewards of this type. Cannot remove."

        # 1c. Ensure the column name is safe (CRITICAL SECURITY STEP)
        if reward_column not in VALID_REWARD_COLUMNS: 
            return False, f"Invalid reward column name: {reward_column}"
        
        # --- 2. DECREMENT AND COMMIT ---
    
        # SQL to decrement the column by 1
        update_query = f"""
        UPDATE users 
        SET {reward_column} = {reward_column} - 1 
        WHERE discord_id = %s
        RETURNING {reward_column};
        """

        # We need the user-friendly reward name, so we look it up from the column value
        reward_name = next(c.name for c in REWARD_CHOICES if c.value == reward_column)
        
        cursor.execute(update_query, (discord_id,))
        new_count = cursor.fetchone()[0] # Get the updated count
        conn.commit()

        log_msg = f"🔴 '{reward_name}' removed from inventory."
        log_reward_activity(discord_id, log_msg)
        
        return True, f"Reward decremented! New count for '{reward_column}' is **{new_count}**."
            
    except Exception as e:
        conn.rollback()
        print(f"Error decrementing reward for {twitch_username}: {e}")
        return False, f"An unexpected database error occurred: {e}"
            
    finally:
        cursor.close()
        conn.close()

# --- Discord Modal Implementation ---

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
        await interaction.response.defer(ephemeral=True)
        
        # Get the input value
        twitch_name_raw = self.twitch_username_input.value.strip()
        
        # Convert to lowercase for saving AND checking ***
        twitch_name_for_db = twitch_name_raw.lower() 
        
        discord_id = interaction.user.id
        
        # Save the data (handle the status returned by the DB function)
        # Pass the lowercase version to the saving function
        success, message = save_user_registration(discord_id, twitch_name_for_db) 
        
        # Send confirmation or error based on the result
        if success:
            await interaction.followup.send(
                # Use the original (raw) name for display in the success message
                f"✅ **Success!** Your Twitch username (`{twitch_name_raw}`) has been registered and linked to your Discord account. (Stored as lowercase.)",
                ephemeral=True
            )
        else:
            # The error message from the DB function will use the raw name
            await interaction.followup.send(
                f"❌ **Registration Failed:** {message}",
                ephemeral=True
            )

# --- Discord Bot Events and Commands ---

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

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="my-rewards", 
    description="View your current inventory of rewards."
)
async def my_rewards_command(interaction: discord.Interaction):
    """Retrieves and displays the user's current reward inventory."""
    
    await interaction.response.defer(ephemeral=True) 
    
    discord_id = interaction.user.id
    user_rewards = get_user_rewards(discord_id)
    
    # 1) Tell them they're not in the database
    if user_rewards is None:
        await interaction.followup.send(
            "🛑 **Not Registered.** You don't appear to be registered yet. Please use `/register` to link your Twitch account and start collecting rewards!",
            ephemeral=True
        )
        return
        
    # Prepare the list of rewards with a quantity > 0
    reward_list = []
    
    # Use the REWARD_CHOICES constant to get the user-friendly name
    for choice in REWARD_CHOICES:
        column_name = choice.value
        display_name = choice.name
        
        # The count will be 0 or more (since we set DEFAULT 0 in setup_db)
        count = user_rewards.get(column_name, 0)
        
        if count > 0:
            reward_list.append(f"• **{display_name}:** {count}")
            
    # 2) Print out a list of rewards
    if reward_list:
        rewards_text = "\n".join(reward_list)
        
        embed = discord.Embed(
            title=f"🎁 {interaction.user.name}'s Reward Inventory",
            description=f"Here are the rewards currently linked to your account:",
            color=discord.Color.gold()
        )
        embed.add_field(name="Available Rewards", value=rewards_text, inline=False)

        log_text = ""
        log1 = user_rewards.get("log_recent_1")
        log2 = user_rewards.get("log_recent_2")
        log3 = user_rewards.get("log_recent_3")
        
        # Build the log message, skipping any null/empty entries.
        # The log entries are already formatted with the timestamp and color.
        log_entries = [log for log in [log1, log2, log3] if log]
            
        if log_entries:
            # Join with a newline to list them clearly
            log_text = "\n".join(log_entries)
            embed.add_field(name="Recent Activity Log (Max 3)", value=log_text.strip(), inline=False)
        else:
            embed.add_field(name="Recent Activity Log", value="No recent activity logged.", inline=False)
        
        embed.set_footer(text="Let Static know when you want to use them!")

        await interaction.followup.send(embed=embed, ephemeral=True)
        
    # 3) Tell them their rewards inventory is empty
    else:
        await interaction.followup.send(
            "📦 **Inventory Empty!** You are registered, but currently have no available rewards to claim.",
            ephemeral=True
        )

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="display-rewards", 
    description="View another user's current inventory of rewards (publicly)."
)
@app_commands.describe(
    member="The Discord user whose rewards list you want to view."
)
async def display_rewards_command(interaction: discord.Interaction, member: discord.Member):
    """Retrieves and publicly displays another user's current reward inventory."""
    
    # 1. Defer the response. Note: We use ephemeral=False (the default) so the response is public.
    await interaction.response.defer(ephemeral=False) 
    
    discord_id = member.id
    user_rewards = get_user_rewards(discord_id)
    
    # 2. Handle User Not Registered
    if user_rewards is None:
        await interaction.followup.send(
            f"🛑 **Not Registered.** **{member.display_name}** does not appear to be registered yet. They need to use `/register` to link their Twitch account.",
            ephemeral=False # Public message
        )
        return
        
    # 3. Prepare the list of rewards with a quantity > 0
    reward_list = []
    
    # Use the REWARD_CHOICES constant to get the user-friendly name
    for choice in REWARD_CHOICES:
        column_name = choice.value
        display_name = choice.name
        
        # The count will be 0 or more
        count = user_rewards.get(column_name, 0)
        
        if count > 0:
            # Note: We display the user-friendly name from the REWARD_CHOICES
            reward_list.append(f"• **{display_name}:** {count}")
            
    # 4. Print out a list of rewards (if any)
    if reward_list:
        rewards_text = "\n".join(reward_list)
        
        embed = discord.Embed(
            title=f"🎁 {member.display_name}'s Public Reward Inventory",
            description=f"Here are the rewards currently linked to **{member.display_name}'s** account:",
            color=discord.Color.blue() # Changed color just for visual distinction
        )
        embed.add_field(name="Available Rewards", value=rewards_text, inline=False)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")

        await interaction.followup.send(embed=embed, ephemeral=False) # Public response
        
    # 5. Tell them their rewards inventory is empty
    else:
        await interaction.followup.send(
            f"📦 **Inventory Empty!** **{member.display_name}** is registered, but currently has no available rewards to claim.",
            ephemeral=False # Public message
        )

# --- ADMIN COMMANDS --- 

# --- ADMIN COMMAND: ADD REWARD (DISCORD MEMBER) ---

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="add-reward", 
    description="[ADMIN ONLY] Adds a reward count to a registered user (by Discord selection)."
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    member="The Discord user (must be registered) of the recipient.",
    reward="The specific reward to be added."
)
@app_commands.choices(reward=REWARD_CHOICES)
async def add_reward_discord_command(
    interaction: discord.Interaction, 
    member: discord.Member, 
    reward: app_commands.Choice[str]
):
    """Admin command to increment a user's reward count by Discord selection."""
    
    # 1. ADMIN CHECK (Authorization)
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message(
            "🛑 **Authorization Failed.** This command is restricted to the bot owner.", 
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True) 
    
    # 2. Get the recipient's Twitch username using their Discord ID
    twitch_name = get_user_registration(member.id)
    
    if twitch_name is None:
        await interaction.followup.send(
            f"❌ **Failed to Add Reward** (Via Discord Selection)\n"
            f"**Reason:** The user **{member.display_name}** is not registered. They must use `/register` first.",
            ephemeral=True
        )
        return
        
    # Get the database column name from the choice value
    reward_column = reward.value 
    reward_name = reward.name
    
    # 3. Call the synchronous DB function (Uses the fetched twitch_name)
    success, message = increment_user_reward(twitch_name, reward_column)

    # 4. Send the response
    if success:
        await interaction.followup.send(
            f"✅ **Reward Added!** (Via Discord Selection)\n"
            f"**Recipient:** `{member.display_name}` (Twitch: `{twitch_name}`)\n"
            f"**Reward:** `{reward_name}`\n"
            f"**Status:** {message}", # The message contains the new count
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"❌ **Failed to Add Reward** (Via Discord Selection)\n"
            f"**Reason:** {message}",
            ephemeral=True
        )

# --- ADMIN COMMAND: REMOVE REWARD (DISCORD MEMBER) ---

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="remove-reward", 
    description="[ADMIN ONLY] Subtracts a reward count from a registered user (by Discord selection)."
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    member="The Discord user (must be registered) of the recipient.",
    reward="The specific reward to be removed."
)
@app_commands.choices(reward=REWARD_CHOICES)
async def remove_reward_discord_command(
    interaction: discord.Interaction, 
    member: discord.Member, 
    reward: app_commands.Choice[str]
):
    """Admin command to decrement a user's reward count by Discord selection."""
    
    # 1. ADMIN CHECK (Authorization)
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message(
            "🛑 **Authorization Failed.** This command is restricted to the bot owner.", 
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True) 
    
    # 2. Get the recipient's Twitch username using their Discord ID
    twitch_name = get_user_registration(member.id)
    
    if twitch_name is None:
        await interaction.followup.send(
            f"❌ **Failed to Remove Reward** (Via Discord Selection)\n"
            f"**Reason:** The user **{member.display_name}** is not registered. They must use `/register` first.",
            ephemeral=True
        )
        return
        
    # Get the database column name from the choice value
    reward_column = reward.value 
    reward_name = reward.name
    
    # 3. Call the synchronous DB function (Uses the fetched twitch_name)
    success, message = decrement_user_reward(twitch_name, reward_column)

    # 4. Send the response
    if success:
        await interaction.followup.send(
            f"✅ **Reward Removed!** (Via Discord Selection)\n"
            f"**Recipient:** `{member.display_name}` (Twitch: `{twitch_name}`)\n"
            f"**Reward:** `{reward_name}`\n"
            f"**Status:** {message}",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"❌ **Failed to Remove Reward** (Via Discord Selection)\n"
            f"**Reason:** {message}",
            ephemeral=True
        )
 
@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="add-reward-twitch", 
    description="[ADMIN ONLY] Adds a reward count using a Twitch username."
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    twitch_name="The registered Twitch username of the recipient.",
    reward="The specific reward to be added."
)
@app_commands.choices(reward=REWARD_CHOICES)
async def add_reward_twitch_command(
    interaction: discord.Interaction, 
    twitch_name: str, 
    reward: app_commands.Choice[str]
):
    """Admin command to increment a user's reward count by Twitch name."""
    
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
    
    # 2. Call the synchronous DB function (Uses the input twitch_name)
    success, message = increment_user_reward(twitch_name.strip(), reward_column)

    # 3. Send the response
    if success:
        await interaction.followup.send(
            f"✅ **Reward Added!** (Via Twitch Name)\n"
            f"**Recipient:** `{twitch_name}`\n"
            f"**Reward:** `{reward_name}`\n"
            f"**Status:** {message}", # The message contains the new count
            ephemeral=True
        )
    else:
        # This handles Twitch user not found or a database error
        await interaction.followup.send(
            f"❌ **Failed to Add Reward** (Via Twitch Name)\n"
            f"**Reason:** {message}",
            ephemeral=True
        )

# --- ADMIN COMMAND: REMOVE REWARD --- 

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID), 
    name="remove-reward-twitch", 
    description="[ADMIN ONLY] Subtracts a reward count using a Twitch username."
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    twitch_name="The registered Twitch username of the recipient.",
    reward="The specific reward to be removed."
)
@app_commands.choices(reward=REWARD_CHOICES)
async def remove_reward_twitch_command(
    interaction: discord.Interaction, 
    twitch_name: str, 
    reward: app_commands.Choice[str]
):
    """Admin command to decrement a user's reward count by Twitch name."""
    
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
    
    # 2. Call the synchronous DB function (Uses the input twitch_name)
    success, message = decrement_user_reward(twitch_name.strip(), reward_column)

    # 3. Send the response
    if success:
        await interaction.followup.send(
            f"✅ **Reward Removed!** (Via Twitch Name)\n"
            f"**Recipient:** `{twitch_name}`\n"
            f"**Reward:** `{reward_name}`\n"
            f"**Status:** {message}", # The message contains the new count
            ephemeral=True
        )
    else:
        # This handles Twitch user not found or the zero-count constraint
        await interaction.followup.send(
            f"❌ **Failed to Remove Reward** (Via Twitch Name)\n"
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

@bot.tree.command(
    guild=discord.Object(id=GUILD_ID),
    name="help",
    description="Instructions on how to use the bot"
)
async def hello_command(interaction: discord.Interaction):
    """Says hello back to the user."""
    # Defer the response immediately to beat the 3-second timeout
    await interaction.response.defer(ephemeral=False)

    # Simulate a small task delay
    await asyncio.sleep(0.5)

    # Use followup.send() after deferring
    await interaction.followup.send(f"Hello, {interaction.user.name}! This bot keeps track of your channel point rewards in Static's stream. If Static hasn't manually entered you into the database yet, you can use /register and enter your Twitch name. It doesn't have to be exact, it's just for Static to type in when he's adding/removing rewards to your account. After that it's extremely straightforward - simply use /my-rewards to view rewards you have in the stream! Or, use /display-rewards to view another users rewards!", ephemeral=False)

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
app = Flask(__name__)

def start_bot():
    """Starts the Discord bot with explicit logging to see why it's failing."""
    print("Starting Discord Bot thread... attempting login.")
    try:
        # We re-enable the log_handler to see the Discord errors in Render logs
        bot.run(token) 
    except Exception as e:
        print(f"DISCORD THREAD ERROR: {e}")

# --- 5. Integrated Startup Sequence ---

def run_everything():
    # We move setup_db INSIDE the thread so it doesn't block Gunicorn
    setup_db() 
    start_bot()

# 1. Start the Discord Bot AND DB Setup in the background
print("Main Process: Launching Background Tasks...")
t = threading.Thread(target=run_everything, name="discord_bot_thread", daemon=True)
t.start()

# 2. Define the Flask Routes (This happens instantly now!)
@app.route('/')
def home():
    return "Bot is online", 200
