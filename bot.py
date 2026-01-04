import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import random
import json
import os
import math
import asyncio
import datetime
from datetime import timedelta
import io
from pathlib import Path
import sys
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Any

# ────────────────────────── logging ────────────────────────────────
log = logging.getLogger("campton_bot")
log.setLevel(logging.INFO)
if log.handlers:
    for handler in log.handlers:
        log.removeHandler(handler)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", style="{", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
log.addHandler(handler)
discord_logger = logging.getLogger('discord')
if discord_logger.handlers:
    for handler in discord_logger.handlers:
        discord_logger.removeHandler(handler)
discord_logger.addHandler(handler)
discord_logger.setLevel(logging.INFO)

# ────────────────────────── env / config ───────────────────────────
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

def env_int(k: str, default: int | None = None) -> int | None:
    v = os.getenv(k)
    return int(v) if v and v.isdigit() else default

ANNOUNCEMENT_CHANNEL_ID = env_int("ANNOUNCEMENT_CHANNEL_ID")
HELP_DESK_CHANNEL_ID = env_int("HELP_DESK_CHANNEL_ID")
VERIFY_CHANNEL_ID = env_int("VERIFY_CHANNEL_ID")
BACKUP_CHANNEL_ID = env_int("BACKUP_CHANNEL_ID")
NEW_ARRIVAL_ROLE_ID = env_int("NEW_ARRIVAL_ROLE_ID")
CAMPTON_CITIZEN_ROLE_ID = env_int("CAMPTON_CITIZEN_ROLE_ID")
MARKET_INVESTOR_ROLE_ID = env_int("MARKET_INVESTOR_ROLE_ID")

# ────────────────────────── Owner & Co-Owner IDs ───────────────────
OWNER_ID = 357681843790675978          # Main owner (you)
CO_OWNER_ID = 244214611400851458        # Co-owner
LOG_RECEIVER_ID = 1321335530364993608   # Gets all DM logs

if not TOKEN:
    log.critical("DISCORD_BOT_TOKEN environment variable not found. Bot cannot start.")
    raise SystemExit(1)

# ────────────────────────── Permission Helpers ─────────────────────
def is_owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

def is_co_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id in (OWNER_ID, CO_OWNER_ID)

# ────────────────────────── Render-safe DM Logger ───────────────────
async def send_log_dm(payload: dict, filename: str, prefix: str):
    try:
        user = await bot.fetch_user(LOG_RECEIVER_ID)
        json_bytes = io.BytesIO(json.dumps(payload, indent=4).encode('utf-8'))
        json_bytes.seek(0)
        await user.send(
            content=f"{prefix} — {payload.get('user', {}).get('username', 'Unknown')}",
            file=discord.File(fp=json_bytes, filename=filename)
        )
    except Exception as e:
        log.error(f"Log DM failed: {e}")

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    if interaction.command_failed:
        return
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "command": command.name,
        "user": {
            "id": interaction.user.id,
            "username": str(interaction.user)
        }
    }
    await send_log_dm(payload, f"cmd_{command.name}.json", "Command Used")

# ────────────────────────── constants ──────────────────────────────
PREFIX = "!"
DATA_FILE = Path("stock_market_data.json")
CAMPTOM_COIN_NAME = "Campton Coin"
MIN_PRICE, MAX_PRICE = 50.00, 230.00
INITIAL_PRICE = 120.00
VOLATILITY_LEVELS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.20, 1.50]
CRYPTO_NAMES = ["Campton Coin"]

# ────────────────────────── decimal helpers ────────────────────────
def D(x: float|str|Decimal) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.000"), rounding=ROUND_DOWN)

def money(x: Decimal) -> str:
    return f"{x.quantize(Decimal('0.01'))} dollars"

def too_many_decimals(x: Decimal, p: int) -> bool:
    s = str(x)
    if '.' in s:
        decimal_part = s.split('.')[1]
        return len(decimal_part) > p
    return False

# ────────────────────────── data i/o (Discord backup) ──────────────
save_lock = asyncio.Lock()
backup_channel_global: discord.TextChannel | None = None

def _ensure_data_dir_exists():
    if not DATA_FILE.parent.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"Local data directory created: {DATA_FILE.parent}")

def _write_atomic_local_fallback(data: dict[str, Any]):
    _ensure_data_dir_exists()
    tmp = DATA_FILE.with_suffix(".tmp")
    try:
        with open(tmp, 'w') as fp:
            json.dump(data, fp, indent=4, default=str)
        tmp.replace(DATA_FILE)
        log.info(f"Local fallback data saved to {DATA_FILE}")
    except Exception as e:
        log.error(f"Local fallback save failed: {e}")

def _read_json_local_fallback() -> dict[str, Any]:
    _ensure_data_dir_exists()
    if not DATA_FILE.exists():
        log.info(f"Local fallback file {DATA_FILE} does not exist.")
        return {}
    try:
        with open(DATA_FILE, 'r') as f:
            loaded_data = json.load(f)
            log.info(f"Local fallback data loaded from {DATA_FILE}")
            return loaded_data
    except json.JSONDecodeError:
        log.warning(f"Local {DATA_FILE} corrupted. Starting fresh for local fallback.")
        return {}
    except Exception as e:
        log.error(f"Failed to read local fallback data: {e}")
        return {}

async def save_data():
    async with save_lock:
        log.info("SAVE_DATA_CALL: Initiating save process (local & Discord backup).")
        _write_atomic_local_fallback(market_data)
        if not BACKUP_CHANNEL_ID:
            log.warning("SAVE_DATA_CALL: BACKUP_CHANNEL_ID not set in environment. Discord backup skipped.")
            return
        ch = backup_channel_global
        if not ch:
            log.warning(f"SAVE_DATA_CALL: Backup channel object not available (ID: {BACKUP_CHANNEL_ID}). Discord backup skipped.")
            return
        try:
            log.info(f"SAVE_DATA_CALL: Checking for old backup messages in channel {ch.name} ({ch.id}).")
            deleted_old_backup = False
            async for msg in ch.history(limit=10):
                if msg.author == bot.user and msg.attachments:
                    await msg.delete()
                    log.info(f"SAVE_DATA_CALL: Deleted old Discord backup message {msg.id}.")
                    deleted_old_backup = True
                    break
            if not deleted_old_backup:
                log.info("SAVE_DATA_CALL: No old Discord backup message found to delete.")
            json_str = json.dumps(market_data, indent=4, default=str)
            await ch.send(
                content=f"**Automated Data Backup** - {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                file=discord.File(fp=io.BytesIO(json_str.encode()), filename="market_data.json")
            )
            log.info("SAVE_DATA_CALL: Data backed up to Discord successfully.")
        except discord.Forbidden:
            log.error(f"SAVE_DATA_CALL: Discord backup failed due to permissions in channel {ch.name} ({ch.id}).")
        except Exception as e:
            log.error(f"SAVE_DATA_CALL: Discord backup failed with an unexpected error: {e}")

async def load_data_from_discord():
    global market_data
    log.info("LOAD_DATA_CALL: Attempting to load data from Discord backup.")
    if not BACKUP_CHANNEL_ID:
        log.warning("LOAD_DATA_CALL: BACKUP_CHANNEL_ID not set; will use local/default data.")
        return
    ch = backup_channel_global
    if not ch:
        log.warning(f"LOAD_DATA_CALL: Backup channel object not available (ID: {BACKUP_CHANNEL_ID}). Cannot load from Discord.")
        return
    try:
        log.info(f"LOAD_DATA_CALL: Searching for latest backup in channel {ch.name} ({ch.id}).")
        async for msg in ch.history(limit=10):
            if msg.author == bot.user and msg.attachments:
                data = await msg.attachments[0].read()
                loaded = json.loads(data)
                market_data.update(loaded)
                log.info(f"LOAD_DATA_CALL: Loaded data from Discord backup message {msg.id}.")
                return
        log.info("LOAD_DATA_CALL: No Discord backup found; using local/default data.")
    except discord.Forbidden:
        log.error(f"LOAD_DATA_CALL: Discord load failed due to permissions in channel {ch.name} ({ch.id}).")
    except Exception as e:
        log.error(f"LOAD_DATA_CALL: Failed to load Discord backup: {e}")

# Initial market_data (tickets key removed)
market_data: dict[str, Any] = {
    "coins": {CAMPTOM_COIN_NAME: {"price": INITIAL_PRICE}},
    "users": {},
    "next_conversion_timestamp": (discord.utils.utcnow() + timedelta(days=7)).isoformat(),
}
market_data.update(_read_json_local_fallback())

# ────────────────────────── discord objects ────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ────────────────────────── helpers ────────────────────────────────
def guild() -> discord.Guild | None:
    return bot.guilds[0] if bot.guilds else None

def price() -> Decimal:
    return Decimal(str(market_data["coins"][CAMPTOM_COIN_NAME]["price"]))

def set_price(p: Decimal):
    market_data["coins"][CAMPTOM_COIN_NAME]["price"] = float(p)

def get_user(uid: int) -> dict[str, Any]:
    s = str(uid)
    if s not in market_data["users"]:
        market_data["users"][s] = {
            "balance": 0.0,
            "portfolio": {},
            "verification": {},
            "on_buy_cooldown": False,
        }
    return market_data["users"][s]

def check_and_assign_investor_role(user_id: int, guild: discord.Guild):
    if not MARKET_INVESTOR_ROLE_ID or not guild:
        return
    member = guild.get_member(user_id)
    if not member or member.bot:
        return
    inv_role = guild.get_role(MARKET_INVESTOR_ROLE_ID)
    if not inv_role:
        return
    user_data = get_user(user_id)
    balance = user_data.get("balance", 0.0)
    coins = user_data.get("portfolio", {}).get(CAMPTOM_COIN_NAME, 0.0)
    if (balance >= 20000.0 or coins >= 70.0) and inv_role not in member.roles:
        try:
            asyncio.create_task(member.add_roles(inv_role))
            log.info(f"ROLE: Queued investor role for {member.display_name}")
        except Exception as e:
            log.warning(f"ROLE: Cannot assign role: {e}")

# ────────────────────────── market logic functions ───────────────────────────
def update_prices():
    for coin_name in market_data["coins"]:
        current_price = market_data["coins"][coin_name]["price"]
        chosen_volatility = random.choice(VOLATILITY_LEVELS)
        change_percent = random.uniform(-chosen_volatility, chosen_volatility)
        new_price = current_price * (1 + change_percent)
        new_price = max(MIN_PRICE, min(MAX_PRICE, new_price))
        market_data["coins"][coin_name]["price"] = round(new_price, 2)
    for user_id_str in market_data["users"]:
        market_data["users"][user_id_str]["on_buy_cooldown"] = False
    log.info("INFO: Market prices updated and buy cooldown cleared.")

def get_user_data(user_id):
    user_id_str = str(user_id)
    if user_id_str not in market_data["users"]:
        market_data["users"][user_id_str] = {"balance": 0.0, "portfolio": {}, "verification": {}, "on_buy_cooldown": False}
    elif "verification" not in market_data["users"][user_id_str]:
        market_data["users"][user_id_str]["verification"] = {}
    if "on_buy_cooldown" not in market_data["users"][user_id_str]:
        market_data["users"][user_id_str]["on_buy_cooldown"] = False
    return market_data["users"][user_id_str]

def buy_coin_logic(user_id, coin_name, quantity_of_coins_to_buy):
    user = get_user_data(user_id)
    if coin_name not in market_data["coins"]:
        return "Coin not found."
    coin_price = market_data["coins"][coin_name]["price"]
    cost = quantity_of_coins_to_buy * coin_price
    if user["balance"] < cost:
        return f"Insufficient funds. You need {cost:.2f} dollars but only have {user['balance']:.2f} dollars."
    if user.get("on_buy_cooldown", False):
        return "You cannot buy Campton Coin until after the next market price update (approximately every 3 days)."
    user["balance"] -= cost
    user["portfolio"][coin_name] = user["portfolio"].get(coin_name, 0.0) + quantity_of_coins_to_buy
    return f"Successfully bought {quantity_of_coins_to_buy:.3f} {coin_name}(s) for {cost:.2f} dollars."

def sell_coin_logic(user_id, coin_name, quantity):
    user = get_user_data(user_id)
    if coin_name not in market_data["coins"]:
        return "Coin not found."
    if coin_name not in user["portfolio"] or user["portfolio"][coin_name] < quantity:
        return f"You don't own {quantity:.3f} {coin_name}(s). You have {user['portfolio'].get(coin_name, 0.0):.3f}."
    coin_price = market_data["coins"][coin_name]["price"]
    revenue = coin_price * quantity
    user["balance"] += revenue
    user["portfolio"][coin_name] -= quantity
    if user["portfolio"][coin_name] <= 0.0001:
        del user["portfolio"][coin_name]
    return f"Successfully sold {quantity:.3f} {coin_name}(s) for {revenue:.2f} dollars."

async def _perform_crypto_to_cash_conversion():
    log.info("CONVERT: Initiating crypto to cash conversion logic...")
    if CAMPTOM_COIN_NAME not in market_data["coins"]:
        log.warning(f"CONVERT: '{CAMPTOM_COIN_NAME}' not found in market data. Skipping conversion.")
        return 0
    current_coin_price = market_data["coins"][CAMPTOM_COIN_NAME]["price"]
    target_guild = bot.guilds[0] if bot.guilds else None
    if target_guild is None:
        log.warning("CONVERT: Bot is not in any guild. Cannot perform crypto to cash conversion.")
        return 0
    converted_count = 0
    for user_id_str, user_data in list(market_data["users"].items()):
        user_id = int(user_id_str)
        member = target_guild.get_member(user_id)
        if member and not member.bot:
            user_campton_coins = user_data.get("portfolio", {}).get(CAMPTOM_COIN_NAME, 0.0)
            if user_campton_coins > 0.0:
                cash_received = user_campton_coins * current_coin_price
                user_data["balance"] += cash_received
                user_data["portfolio"][CAMPTOM_COIN_NAME] = 0.0
                if CAMPTOM_COIN_NAME in user_data["portfolio"]:
                    del user_data["portfolio"][CAMPTOM_COIN_NAME]
                user_data["on_buy_cooldown"] = True
                converted_count += 1
                log.info(f"CONVERT: Converted {user_campton_coins:.3f} {CAMPTOM_COIN_NAME} for {member.display_name} ({user_id}) to {cash_received:.2f} dollars.")
                try:
                    await member.send(
                        f"🔔 **Automatic Crypto Conversion!** 🔔\n\n"
                        f"Your {user_campton_coins:.3f} {CAMPTOM_COIN_NAME} holdings have been automatically converted to cash.\n"
                        f"You received **{cash_received:.2f} dollars** (at a price of {current_coin_price:.2f} dollars per coin).\n"
                        f"Your new cash balance is: **{user_data['balance']:.2f} dollars**.\n\n"
                        f"**You are now on a temporary buy cooldown and cannot purchase Campton Coin until after the next market price update.**"
                    )
                except discord.Forbidden:
                    log.warning(f"CONVERT: Could not send DM to {member.display_name} about auto-conversion. DMs might be disabled.")
                except Exception as e:
                    log.error(f"CONVERT: Error sending auto-conversion DM to {member.display_name}: {e}")
    market_data["next_conversion_timestamp"] = (discord.utils.utcnow() + timedelta(days=7)).isoformat()
    await save_data()
    log.info(f"CONVERT: Crypto to cash conversion logic complete. {converted_count} users processed.")
    return converted_count

# ────────────────────────── background tasks ───────────────────────
@tasks.loop(hours=72)
async def scheduled_price_update():
    log.info("TASK_PRICE: Running scheduled price update...")
    await bot.change_presence(activity=discord.Game(name="Updating Market Prices..."))
    old_price = market_data["coins"][CAMPTOM_COIN_NAME]["price"]
    update_prices()
    new_price = market_data["coins"][CAMPTOM_COIN_NAME]["price"]
    change = round(new_price - old_price, 2)
    direction = "up" if change > 0 else "down" if change < 0 else "no change"
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "old_price": old_price,
        "new_price": new_price,
        "change": change,
        "direction": direction
    }
    await send_log_dm(payload, "auto_price_update.json", "Auto Price Update")
    await save_data()
    await bot.change_presence(activity=discord.Game(name="Campton Stocks RP"))
    if ANNOUNCEMENT_CHANNEL_ID:
        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="📈 Market Update: Campton Coin 📉",
                description=f"The price of Campton Coin has updated to **{new_price:.2f} dollars**.",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed)
        else:
            log.warning(f"TASK_PRICE: Announcement channel with ID {ANNOUNCEMENT_CHANNEL_ID} not found.")

@scheduled_price_update.before_loop
async def before_scheduled_price_update():
    await bot.wait_until_ready()
    log.info("TASK_PRICE: Scheduled price update task waiting for bot to be ready...")

@tasks.loop(minutes=5)
async def check_investor_roles_task():
    log.info("TASK_INV_ROLE: Running periodic investor role check task.")
    target_guild = bot.guilds[0] if bot.guilds else None
    if target_guild is None:
        return

@check_investor_roles_task.before_loop
async def before_check_investor_roles_task():
    await bot.wait_until_ready()

@tasks.loop(hours=168)
async def auto_convert_crypto_to_cash():
    # (your original code unchanged)

@auto_convert_crypto_to_cash.before_loop
async def before_auto_convert_crypto_to_cash():
    await bot.wait_until_ready()

@tasks.loop(hours=36)
async def notify_conversion_countdown():
    # (your original code unchanged)

@notify_conversion_countdown.before_loop
async def before_notify_conversion_countdown():
    await bot.wait_until_ready()

# ────────────────────────── UI: Verification Only (tickets removed) ───────────────────
class VerificationModal(ui.Modal, title='Project New Campton Verification'):
    roblox_username = ui.TextInput(label='Your Roblox Username', placeholder='e.g., RobloxPlayer123', style=discord.TextStyle.short)
    pnc_full_name = ui.TextInput(label='Project New Campton Full Name (First Last)', placeholder='e.g., John Doe', style=discord.TextStyle.short)

    async def on_submit(self, interaction: discord.Interaction):
        # (your original code unchanged)

class VerifyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Verify and Get Citizen Role", style=discord.ButtonStyle.primary, custom_id="verify_button")

    async def callback(self, interaction: discord.Interaction):
        # (your original code unchanged)

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VerifyButton())

# ────────────────────────── Events ────────────────────────────────
@bot.event
async def on_ready():
    global backup_channel_global
    log.info(f'BOT_READY: {bot.user.name} has connected to Discord!')
    if BACKUP_CHANNEL_ID:
        # (your original fetch loop unchanged)
        pass
    await load_data_from_discord()
    if CAMPTOM_COIN_NAME not in market_data["coins"] or len(market_data["coins"]) != len(CRYPTO_NAMES):
        market_data["coins"] = {}
        for name in CRYPTO_NAMES:
            market_data["coins"][name] = {"price": INITIAL_PRICE}
        await save_data()
    elif market_data["coins"][CAMPTOM_COIN_NAME]["price"] < MIN_PRICE or market_data["coins"][CAMPTOM_COIN_NAME]["price"] > MAX_PRICE:
        market_data["coins"][CAMPTOM_COIN_NAME]["price"] = INITIAL_PRICE
        await save_data()
    bot.add_view(VerifyView())  # TicketView removed
    await bot.tree.sync()
    log.info("BOT_READY: Slash commands synced!")
    scheduled_price_update.start()
    check_investor_roles_task.start()
    auto_convert_crypto_to_cash.start()
    notify_conversion_countdown.start()
    log.info("BOT_READY: All scheduled tasks started.")

@bot.event
async def on_member_join(member: discord.Member):
    # (your original code unchanged)

# ────────────────────────── Commands (patched permissions) ───────────────────
# Owner-only commands (hidden from co-owner)
@bot.tree.command(name='prices', description='Displays the current price of Campton Coin.')
@app_commands.default_permissions(administrator=True)
@app_commands.check(is_owner_only)
async def prices(interaction: discord.Interaction):
    # (your original body unchanged)

@bot.tree.command(name='setprice', description='(Owner) Manually set the price of Campton Coin.')
@app_commands.default_permissions(administrator=True)
@app_commands.check(is_owner_only)
async def set_price_cmd(interaction: discord.Interaction, amount: float):
    # (your original body unchanged)

# Co-owner allowed admin commands (changed from is_bot_owner_slash to is_co_owner)
@bot.tree.command(name='addfunds', description='Adds funds to a specified user\'s balance. (Bot Owner Only)')
@app_commands.default_permissions(manage_guild=False)
@app_commands.describe(member='The user to add funds to.', amount='The amount of funds to add.')
@app_commands.check(is_co_owner)
async def add_funds(interaction: discord.Interaction, member: discord.Member, amount: float):
    # (your original body unchanged)

# Repeat the same @app_commands.check(is_co_owner) change for:
# addcoins, approvewithdrawal, clearmessages, lockdown, unlock, manualconvert, save, announce, datedannounce

# Public commands remain unchanged
@bot.tree.command(name='balance', description='Shows your current balance and portfolio, or another member\'s.')
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    # (your original body unchanged)

# ... all other public commands (buy, sell, transfer, withdraw, ping, viewprice) unchanged

# Ticket commands completely removed (sendticketbutton, close)

@bot.tree.command(name='sendverifybutton', description='(Owner Only) Sends the "Verify" button to the current channel.')
@app_commands.default_permissions(manage_guild=False)
@app_commands.check(is_co_owner)  # Now co-owner can use
async def send_verify_button(interaction: discord.Interaction):
    # (your original body unchanged)

# ────────────────────────── Start bot ──────────────────────────────
bot.run(TOKEN)
