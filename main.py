"""StaticRewardsBot - Discord bot that tracks channel point rewards for Static's stream."""

import asyncio
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import NamedTuple

import discord
import psycopg2
import pytz
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
from psycopg2 import errors, sql

# =============================================================================
# Configuration
# =============================================================================

# These MUST be set as environment variables in Render's dashboard.
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

GUILD_ID = 559879519087886356
ADMIN_USER_ID = 341072622735327232  # Only this user may add/remove rewards
GUILD = discord.Object(id=GUILD_ID)

KEEP_ALIVE_HOURS = 12  # How often to ping the DB so Supabase doesn't pause it
EASTERN = pytz.timezone("America/New_York")

# To add a reward: add a Choice here (name shown in Discord -> database column).
# The column is created automatically on startup by setup_db().
REWARD_CHOICES = [
    app_commands.Choice(name="Free Points Reward", value="free_points_reward_count"),
    app_commands.Choice(name="Tier List", value="tier_list_count"),
    app_commands.Choice(name="Watch Video", value="watch_video_count"),
    app_commands.Choice(name="Replay Analysis", value="replay_analysis_count"),
    app_commands.Choice(name="Listen to Album", value="album_count"),
    app_commands.Choice(name="DJ Rest of Stream", value="dj_count"),
    app_commands.Choice(name="Song Request Rest of Stream", value="song_request_count"),
    app_commands.Choice(name="Shuffle Artist of your Choice", value="shuffle_count"),
    app_commands.Choice(name="Play Marbles on Stream", value="marbles_count"),
    app_commands.Choice(name="Play 5 Games of 1v1", value="ones_count"),
    app_commands.Choice(name="Play Jackbox", value="jackbox_count"),
    app_commands.Choice(name="Play 5 games of KBM", value="kbm_count"),
    app_commands.Choice(name="Cast your RL Game", value="cast_count"),
]

REWARD_NAMES = {choice.value: choice.name for choice in REWARD_CHOICES}
VALID_REWARD_COLUMNS = list(REWARD_NAMES)
LOG_COLUMNS = ("log_recent_1", "log_recent_2", "log_recent_3")

# Trade-in rules. Each line says "qty_a of reward_a is worth qty_b of reward_b".
# Every rule works in BOTH directions (e.g. 3 watch videos -> 1 tier list, and 1 tier list ->
# 3 watch videos). Keep the ratios consistent with each other, otherwise users could trade
# in a loop to generate free rewards.
TRADE_EQUIVALENTS = [
    ("watch_video_count", 3, "tier_list_count", 1),
    ("watch_video_count", 6, "replay_analysis_count", 1),
    ("tier_list_count", 2, "replay_analysis_count", 1),
]


class Trade(NamedTuple):
    give: str      # column the user pays with
    give_qty: int
    get: str       # column the user receives
    get_qty: int


def _build_trades() -> dict[str, Trade]:
    trades = {}
    for col_a, qty_a, col_b, qty_b in TRADE_EQUIVALENTS:
        for trade in (Trade(col_a, qty_a, col_b, qty_b), Trade(col_b, qty_b, col_a, qty_a)):
            trades[f"{trade.give}>{trade.get}"] = trade
    return trades


TRADES = _build_trades()  # key like "watch_video_count>tier_list_count" -> Trade
TRADE_CHOICES = [
    app_commands.Choice(
        name=f"{t.give_qty}× {REWARD_NAMES[t.give]} → {t.get_qty}× {REWARD_NAMES[t.get]}",
        value=key,
    )
    for key, t in TRADES.items()
]  # Discord allows at most 25 choices

# =============================================================================
# Bot setup
# =============================================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=None, intents=intents)

# =============================================================================
# Database helpers
# =============================================================================


class DatabaseUnavailable(Exception):
    """Raised when a database connection cannot be established."""


def get_db_connection():
    """Returns a new PostgreSQL connection, or None if it can't be established."""
    if not DATABASE_URL:
        print("FATAL ERROR: DATABASE_URL environment variable is not set. Cannot connect to DB.")
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"FATAL ERROR: Failed to connect to database: {e}")
        return None


@contextmanager
def db_cursor():
    """
    Yields a cursor on a fresh connection.
    Commits on success, rolls back on any exception, and always closes the connection.
    Raises DatabaseUnavailable if the connection fails.
    """
    conn = get_db_connection()
    if conn is None:
        raise DatabaseUnavailable()
    try:
        with conn:  # psycopg2: commit on success / rollback on error (does not close)
            with conn.cursor() as cursor:
                yield cursor
    finally:
        conn.close()


def setup_db():
    """
    Creates the 'users' table, the case-insensitive unique index on twitch_username,
    and all reward/log columns if they don't already exist.
    """
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    discord_id BIGINT PRIMARY KEY,
                    twitch_username VARCHAR(50) NOT NULL
                );
            """)

            # Raises UniqueViolation if duplicate names (case-insensitive) already exist.
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS unique_twitch_username_lower
                ON users (LOWER(twitch_username));
            """)

            for column in VALID_REWARD_COLUMNS:
                cursor.execute(
                    sql.SQL("ALTER TABLE users ADD COLUMN IF NOT EXISTS {} INT DEFAULT 0;")
                    .format(sql.Identifier(column))
                )

            for column in LOG_COLUMNS:
                cursor.execute(
                    sql.SQL("ALTER TABLE users ADD COLUMN IF NOT EXISTS {} TEXT;")
                    .format(sql.Identifier(column))
                )

        print("Database table 'users' setup and commit complete.")

    except DatabaseUnavailable:
        return
    except errors.UniqueViolation:
        print("----------------------------------------------------------------------------------")
        print("!!! FATAL DB SETUP ERROR: UNIQUE CONSTRAINT VIOLATION !!!")
        print("The case-insensitive index failed because duplicate Twitch names (e.g., 'name' and 'Name') exist in the table.")
        print("You must manually clean the database using the SQL query below, and then restart the bot.")
        print("SQL to find duplicates: SELECT LOWER(twitch_username), COUNT(*) FROM users GROUP BY 1 HAVING COUNT(*) > 1;")
        print("----------------------------------------------------------------------------------")
    except Exception as e:
        print(f"FATAL ERROR setting up database table or columns: {e}")


def save_user_registration(discord_id: int, twitch_username: str) -> tuple[bool, str]:
    """Saves or updates a user's Twitch name (stored lowercase). Returns (success, message)."""
    twitch_username = twitch_username.lower()
    try:
        with db_cursor() as cursor:
            # Reject names already claimed by a different user.
            cursor.execute(
                "SELECT 1 FROM users WHERE LOWER(twitch_username) = %s AND discord_id != %s;",
                (twitch_username, discord_id),
            )
            if cursor.fetchone() is not None:
                return False, (
                    f"The Twitch name **{twitch_username}** is already registered by "
                    f"another user. Please choose a unique name."
                )

            # (xmax = 0) is true only for freshly inserted rows, so we can tell insert from update.
            cursor.execute(
                """
                INSERT INTO users (discord_id, twitch_username)
                VALUES (%s, %s)
                ON CONFLICT (discord_id) DO UPDATE SET
                    twitch_username = EXCLUDED.twitch_username
                RETURNING (xmax = 0);
                """,
                (discord_id, twitch_username),
            )
            was_inserted = cursor.fetchone()[0]

        action = "registered" if was_inserted else "updated"
        return True, f"Registration successful (name {action})."

    except DatabaseUnavailable:
        return False, "Database connection failed."
    except Exception as e:
        print(f"FATAL ERROR saving registration for {discord_id}: {e}")
        return False, "An unexpected database error occurred. Please try again later."


def get_user_registration(discord_id: int) -> str | None:
    """Returns the user's registered Twitch username, or None if not registered."""
    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT twitch_username FROM users WHERE discord_id = %s;", (discord_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    except DatabaseUnavailable:
        return None
    except Exception as e:
        print(f"Error retrieving registration from database: {e}")
        return None


def get_user_rewards(discord_id: int) -> dict | None:
    """
    Returns a dict of the user's reward counts and log entries (keyed by column name),
    or None if the user isn't found.
    """
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in VALID_REWARD_COLUMNS + list(LOG_COLUMNS))
    query = sql.SQL("SELECT discord_id, {} FROM users WHERE discord_id = %s;").format(columns)
    try:
        with db_cursor() as cursor:
            cursor.execute(query, (discord_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(zip([d[0] for d in cursor.description], row))
    except DatabaseUnavailable:
        print("Database connection failed in get_user_rewards.")
        return None
    except Exception as e:
        print(f"Error retrieving user rewards for {discord_id}: {e}")
        return None


def append_reward_log(cursor, discord_id: int, log_message: str):
    """Rotates the 3-entry activity log (1->2, 2->3) and writes the new entry into slot 1."""
    timestamp = datetime.now(EASTERN).strftime("%m-%d %H:%M %Z")  # e.g. 10-12 14:30 EDT
    entry = f"**[{timestamp}]** {log_message}"
    cursor.execute(
        """
        UPDATE users
        SET log_recent_3 = log_recent_2,
            log_recent_2 = log_recent_1,
            log_recent_1 = %s
        WHERE discord_id = %s;
        """,
        (entry, discord_id),
    )


def adjust_user_reward(twitch_username: str, reward_column: str, delta: int) -> tuple[bool, str]:
    """
    Adds (delta=+1) or removes (delta=-1) one of a reward for the user with the given
    Twitch name, and logs the change. Counts can't go below zero.
    Returns (success, message).
    """
    if reward_column not in REWARD_NAMES:
        return False, f"Invalid reward column name: {reward_column}"

    twitch_username = twitch_username.lower()  # Names are stored lowercase
    column = sql.Identifier(reward_column)  # Safe: also validated against REWARD_NAMES above
    reward_name = REWARD_NAMES[reward_column]

    try:
        # Everything below happens in one transaction: the count change and its log entry.
        with db_cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT discord_id, {} FROM users WHERE twitch_username = %s;").format(column),
                (twitch_username,),
            )
            row = cursor.fetchone()
            if not row:
                return False, f"Twitch user '{twitch_username}' not found in the database."

            discord_id, current_count = row

            if delta < 0 and (current_count or 0) <= 0:
                return False, (
                    f"The user **{twitch_username}** currently has **0** rewards of this type. "
                    f"Cannot remove."
                )

            cursor.execute(
                sql.SQL("UPDATE users SET {col} = {col} + %s WHERE discord_id = %s RETURNING {col};")
                .format(col=column),
                (delta, discord_id),
            )
            new_count = cursor.fetchone()[0]

            if delta > 0:
                append_reward_log(cursor, discord_id, f"🟢 '{reward_name}' added to inventory.")
                verb = "incremented"
            else:
                append_reward_log(cursor, discord_id, f"🔴 '{reward_name}' removed from inventory.")
                verb = "decremented"

        return True, f"Reward {verb}! New count for '{reward_column}' is **{new_count}**."

    except DatabaseUnavailable:
        return False, "Database connection failed."
    except Exception as e:
        print(f"Error adjusting reward for {twitch_username}: {e}")
        return False, f"An unexpected database error occurred: {e}"


def trade_in_rewards(discord_id: int, trade: Trade, times: int) -> tuple[bool, str]:
    """
    Trades in rewards from the user's own inventory. Checks the balance, swaps the counts,
    and logs it, all in one transaction (the row is locked so double-clicks can't overspend).
    Returns (success, message).
    """
    cost = trade.give_qty * times
    gain = trade.get_qty * times
    give_name = REWARD_NAMES[trade.give]
    get_name = REWARD_NAMES[trade.get]
    give_col = sql.Identifier(trade.give)
    get_col = sql.Identifier(trade.get)

    try:
        with db_cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT {} FROM users WHERE discord_id = %s FOR UPDATE;").format(give_col),
                (discord_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False, "You aren't registered yet. Use `/register` first."

            have = row[0] or 0
            if have < cost:
                return False, (
                    f"Not enough rewards. This trade needs **{cost}× {give_name}**, "
                    f"but you only have **{have}**."
                )

            cursor.execute(
                sql.SQL(
                    "UPDATE users "
                    "SET {give} = COALESCE({give}, 0) - %s, {get} = COALESCE({get}, 0) + %s "
                    "WHERE discord_id = %s RETURNING {give}, {get};"
                ).format(give=give_col, get=get_col),
                (cost, gain, discord_id),
            )
            new_give, new_get = cursor.fetchone()

            append_reward_log(cursor, discord_id, f"🔄 Traded {cost}× '{give_name}' for {gain}× '{get_name}'.")

        return True, (
            f"You traded **{cost}× {give_name}** for **{gain}× {get_name}**.\n"
            f"You now have **{new_give}× {give_name}** and **{new_get}× {get_name}**."
        )

    except DatabaseUnavailable:
        return False, "Database connection failed."
    except Exception as e:
        print(f"Error trading rewards for {discord_id}: {e}")
        return False, "An unexpected database error occurred. Please try again later."


# --- Keeping the (free-tier) database from pausing ---

def ping_database() -> bool:
    """Runs a tiny real read against the users table so Supabase counts it as activity."""
    try:
        with db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users;")
            cursor.fetchone()
        return True
    except Exception as e:
        print(f"Keep-alive query failed: {e}")
        return False


@tasks.loop(hours=KEEP_ALIVE_HOURS)
async def keep_db_alive():
    # psycopg2 is blocking, so run it in a thread to avoid freezing the bot
    ok = await asyncio.to_thread(ping_database)
    print(f"DB keep-alive ping: {'OK' if ok else 'FAILED'}")


# =============================================================================
# Discord UI
# =============================================================================


class TwitchRegistrationModal(discord.ui.Modal, title="Register Your Twitch"):
    """Modal form that collects the user's Twitch username."""

    twitch_username_input = discord.ui.TextInput(
        label="Your Twitch Username (Case Sensitive)",
        placeholder="e.g., Shroud or Amouranth",
        max_length=50,
        required=True,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        twitch_name_raw = self.twitch_username_input.value.strip()
        success, message = await asyncio.to_thread(
            save_user_registration, interaction.user.id, twitch_name_raw.lower()
        )

        if success:
            await interaction.followup.send(
                f"✅ **Success!** Your Twitch username (`{twitch_name_raw}`) has been registered "
                f"and linked to your Discord account. (Stored as lowercase.)",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(f"❌ **Registration Failed:** {message}", ephemeral=True)


def format_reward_lines(user_rewards: dict) -> list[str]:
    """Bullet lines for every reward the user has at least one of."""
    return [
        f"• **{choice.name}:** {user_rewards[choice.value]}"
        for choice in REWARD_CHOICES
        if (user_rewards.get(choice.value) or 0) > 0
    ]


# =============================================================================
# Events
# =============================================================================


@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user.name} ({bot.user.id})")

    if not keep_db_alive.is_running():  # on_ready can fire again after reconnects
        keep_db_alive.start()

    try:
        await bot.tree.sync(guild=GUILD)
        print("Commands synced successfully!")
    except Exception as e:
        print(f"failed to sync commands: {e}")
    print("---------------------------------------------")


# =============================================================================
# User commands
# =============================================================================


@bot.tree.command(guild=GUILD, name="register", description="Register your Twitch username with the bot.")
async def register_command(interaction: discord.Interaction):
    await interaction.response.send_modal(TwitchRegistrationModal())


@bot.tree.command(
    guild=GUILD,
    name="my-twitch-name",
    description="Shows the Twitch username you have registered with the bot.",
)
async def get_registration_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    twitch_name = await asyncio.to_thread(get_user_registration, interaction.user.id)

    if twitch_name:
        await interaction.followup.send(
            f"🔎 **Found it!** Your registered Twitch username is: `{twitch_name}`",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            "❌ **Not Found.** You don't appear to be registered yet. Use `/register` to link your account!",
            ephemeral=True,
        )


@bot.tree.command(guild=GUILD, name="my-rewards", description="View your current inventory of rewards.")
async def my_rewards_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    user_rewards = await asyncio.to_thread(get_user_rewards, interaction.user.id)

    if user_rewards is None:
        await interaction.followup.send(
            "🛑 **Not Registered.** You don't appear to be registered yet. Please use `/register` "
            "to link your Twitch account and start collecting rewards!",
            ephemeral=True,
        )
        return

    reward_lines = format_reward_lines(user_rewards)
    if not reward_lines:
        await interaction.followup.send(
            "📦 **Inventory Empty!** You are registered, but currently have no available rewards to claim.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"🎁 {interaction.user.name}'s Reward Inventory",
        description="Here are the rewards currently linked to your account:",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Available Rewards", value="\n".join(reward_lines), inline=False)

    # Log entries are pre-formatted with timestamp and color; skip empty slots.
    log_entries = [user_rewards[c] for c in LOG_COLUMNS if user_rewards.get(c)]
    if log_entries:
        embed.add_field(name="Recent Activity Log (Max 3)", value="\n".join(log_entries).strip(), inline=False)
    else:
        embed.add_field(name="Recent Activity Log", value="No recent activity logged.", inline=False)

    embed.set_footer(text="Let Static know when you want to use them!")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    guild=GUILD,
    name="display-rewards",
    description="View another user's current inventory of rewards (publicly).",
)
@app_commands.describe(member="The Discord user whose rewards list you want to view.")
async def display_rewards_command(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=False)  # Public response

    user_rewards = await asyncio.to_thread(get_user_rewards, member.id)

    if user_rewards is None:
        await interaction.followup.send(
            f"🛑 **Not Registered.** **{member.display_name}** does not appear to be registered yet. "
            f"They need to use `/register` to link their Twitch account."
        )
        return

    reward_lines = format_reward_lines(user_rewards)
    if not reward_lines:
        await interaction.followup.send(
            f"📦 **Inventory Empty!** **{member.display_name}** is registered, "
            f"but currently has no available rewards to claim."
        )
        return

    embed = discord.Embed(
        title=f"🎁 {member.display_name}'s Public Reward Inventory",
        description=f"Here are the rewards currently linked to **{member.display_name}'s** account:",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Available Rewards", value="\n".join(reward_lines), inline=False)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)


@bot.tree.command(guild=GUILD, name="help", description="Instructions on how to use the bot")
async def help_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    await asyncio.sleep(0.5)
    # Built from TRADE_EQUIVALENTS so the help text never goes out of date.
    trade_rates = "\n".join(
        f"• {qty_a} {REWARD_NAMES[col_a]} = {qty_b} {REWARD_NAMES[col_b]}"
        for col_a, qty_a, col_b, qty_b in TRADE_EQUIVALENTS
    )

    await interaction.followup.send(
        f"Hello, {interaction.user.name}! This bot keeps track of your channel point rewards in "
        f"Static's stream. If Static hasn't manually entered you into the database yet, you can use "
        f"/register and enter your Twitch name. It doesn't have to be exact, it's just for Static to "
        f"type in when he's adding/removing rewards to your account. After that it's extremely "
        f"straightforward - simply use /my-rewards to view rewards you have in the stream! Or, use "
        f"/display-rewards to view another users rewards!\n\n"
        f"**Trading rewards:** Want a different reward? Use /trade to swap rewards you already have "
        f"for others, as long as you have enough. Pick a trade from the list, and optionally how many "
        f"times to do it. Trades work both ways, and the current rates are:\n"
        f"{trade_rates}",
        ephemeral=False,
    )


@bot.tree.command(guild=GUILD, name="goodbye", description="Says goodbye back to the user!")
async def goodbye_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    await asyncio.sleep(0.5)
    await interaction.followup.send(f"fuk u {interaction.user.name}! (Goodbye message)", ephemeral=False)


@bot.tree.command(guild=GUILD, name="trade", description="Trade in some of your rewards for different ones.")
@app_commands.describe(
    trade="Which trade you want to make.",
    times="How many times to make this trade (default 1).",
)
@app_commands.choices(trade=TRADE_CHOICES)
async def trade_command(
    interaction: discord.Interaction,
    trade: app_commands.Choice[str],
    times: app_commands.Range[int, 1, 25] = 1,
):
    await interaction.response.defer(ephemeral=True)

    success, message = await asyncio.to_thread(
        trade_in_rewards, interaction.user.id, TRADES[trade.value], times
    )

    if success:
        await interaction.followup.send(f"✅ **Trade Complete!**\n{message}", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ **Trade Failed:** {message}", ephemeral=True)


# =============================================================================
# Admin commands
# =============================================================================


async def run_admin_reward_command(
    interaction: discord.Interaction,
    reward: app_commands.Choice[str],
    *,
    adding: bool,
    member: discord.Member | None = None,
    twitch_name: str | None = None,
):
    """
    Shared logic for the four admin commands. Pass either `member` (looked up by Discord
    selection) or `twitch_name` (typed directly).
    """
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message(
            "🛑 **Authorization Failed.** This command is restricted to the bot owner.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    verb, past = ("Add", "Added") if adding else ("Remove", "Removed")
    via = "Discord Selection" if member is not None else "Twitch Name"
    failure_header = f"❌ **Failed to {verb} Reward** (Via {via})\n"

    if member is not None:
        twitch_name = await asyncio.to_thread(get_user_registration, member.id)
        if twitch_name is None:
            await interaction.followup.send(
                f"{failure_header}**Reason:** The user **{member.display_name}** is not registered. "
                f"They must use `/register` first.",
                ephemeral=True,
            )
            return
        recipient = f"`{member.display_name}` (Twitch: `{twitch_name}`)"
    else:
        twitch_name = twitch_name.strip()
        recipient = f"`{twitch_name}`"

    success, message = await asyncio.to_thread(
        adjust_user_reward, twitch_name, reward.value, 1 if adding else -1
    )

    if success:
        await interaction.followup.send(
            f"✅ **Reward {past}!** (Via {via})\n"
            f"**Recipient:** {recipient}\n"
            f"**Reward:** `{reward.name}`\n"
            f"**Status:** {message}",  # The message contains the new count
            ephemeral=True,
        )
    else:
        await interaction.followup.send(f"{failure_header}**Reason:** {message}", ephemeral=True)


@bot.tree.command(
    guild=GUILD,
    name="add-reward",
    description="[ADMIN ONLY] Adds a reward count to a registered user (by Discord selection).",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    member="The Discord user (must be registered) of the recipient.",
    reward="The specific reward to be added.",
)
@app_commands.choices(reward=REWARD_CHOICES)
async def add_reward_discord_command(
    interaction: discord.Interaction, member: discord.Member, reward: app_commands.Choice[str]
):
    await run_admin_reward_command(interaction, reward, adding=True, member=member)


@bot.tree.command(
    guild=GUILD,
    name="remove-reward",
    description="[ADMIN ONLY] Subtracts a reward count from a registered user (by Discord selection).",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    member="The Discord user (must be registered) of the recipient.",
    reward="The specific reward to be removed.",
)
@app_commands.choices(reward=REWARD_CHOICES)
async def remove_reward_discord_command(
    interaction: discord.Interaction, member: discord.Member, reward: app_commands.Choice[str]
):
    await run_admin_reward_command(interaction, reward, adding=False, member=member)


@bot.tree.command(
    guild=GUILD,
    name="add-reward-twitch",
    description="[ADMIN ONLY] Adds a reward count using a Twitch username.",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    twitch_name="The registered Twitch username of the recipient.",
    reward="The specific reward to be added.",
)
@app_commands.choices(reward=REWARD_CHOICES)
async def add_reward_twitch_command(
    interaction: discord.Interaction, twitch_name: str, reward: app_commands.Choice[str]
):
    await run_admin_reward_command(interaction, reward, adding=True, twitch_name=twitch_name)


@bot.tree.command(
    guild=GUILD,
    name="remove-reward-twitch",
    description="[ADMIN ONLY] Subtracts a reward count using a Twitch username.",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    twitch_name="The registered Twitch username of the recipient.",
    reward="The specific reward to be removed.",
)
@app_commands.choices(reward=REWARD_CHOICES)
async def remove_reward_twitch_command(
    interaction: discord.Interaction, twitch_name: str, reward: app_commands.Choice[str]
):
    await run_admin_reward_command(interaction, reward, adding=False, twitch_name=twitch_name)


# =============================================================================
# Web server + startup
# =============================================================================

# Flask keeps the hosting platform happy (it needs something listening on a port).
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is online", 200


def run_everything():
    """Runs in a background thread so it doesn't block Gunicorn."""
    setup_db()
    print("Starting Discord Bot thread... attempting login.")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"DISCORD THREAD ERROR: {e}")


print("Main Process: Launching Background Tasks...")
threading.Thread(target=run_everything, name="discord_bot_thread", daemon=True).start()
