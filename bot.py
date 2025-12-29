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
import io # Needed for Discord backup feature

# --- Configuration ---
TOKEN = os.environ.get('DISCORD_BOT_TOKEN') 
if TOKEN is None:
    print("ERROR: DISCORD_BOT_TOKEN environment variable not found. Bot cannot start.")
    exit()

PREFIX = '!'

# Cryptocurrency Name
CRYPTO_NAMES = ["Campton Coin"]
CAMPTOM_COIN_NAME = "Campton Coin"

# File for persistent data storage
DATA_FILE = 'stock_market_data.json'

# --- Market Price Configuration ---
MIN_PRICE = 50.00
MAX_PRICE = 230.00
INITIAL_PRICE = 120.00

# --- Market Volatility Levels ---
VOLATILITY_LEVELS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.20, 1.50]

# --- Discord Channel IDs ---
ANNOUNCEMENT_CHANNEL_ID = 1453194843009585326
TICKET_CATEGORY_ID = 1453203314689708072
HELP_DESK_CHANNEL_ID = 1453208931034726410
VERIFY_CHANNEL_ID = 1453236019427283035
BACKUP_CHANNEL_ID = int(os.environ.get('BACKUP_CHANNEL_ID', 0)) # Using 0 as default if not set

# --- Discord Role IDs ---
NEW_ARRIVAL_ROLE_ID = 1453229600594333869
CAMPTON_CITIZEN_ROLE_ID = 1453229088507428874
MARKET_INVESTOR_ROLE_ID = 1453228326033555520

# --- Data Storage Functions ---
def load_data():
    data = {"coins": {}, "users": {}, "tickets": {}, "next_conversion_timestamp": None}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try:
                loaded_data = json.load(f)
                data.update(loaded_data)
                if "coins" not in data: data["coins"] = {}
                if "users" not in data: data["users"] = {}
                if "tickets" not in data: data["tickets"] = {}
                if "next_conversion_timestamp" not in data:
                    data["next_conversion_timestamp"] = (discord.utils.utcnow() + timedelta(days=7)).isoformat()
                for user_id in data["users"]:
                    if "verification" not in data["users"][user_id]: data["users"][user_id]["verification"] = {}
                    if "on_buy_cooldown" not in data["users"][user_id]: data["users"][user_id]["on_buy_cooldown"] = False
            except json.JSONDecodeError:
                print(f"Warning: {DATA_FILE} is corrupted or empty. Starting with fresh data.")
    return data

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- Bot Initialization ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

bot.owner_id = 357681843790675978

market_data = load_data()

if CAMPTOM_COIN_NAME not in market_data["coins"] or len(market_data["coins"]) != len(CRYPTO_NAMES): 
    market_data["coins"] = {}
    for name in CRYPTO_NAMES: 
        market_data["coins"][name] = {"price": INITIAL_PRICE}
    save_data(market_data)
elif market_data["coins"][CAMPTOM_COIN_NAME]["price"] < MIN_PRICE or market_data["coins"][CAMPTOM_COIN_NAME]["price"] > MAX_PRICE:
    print(f"Detected Campton Coin price outside bounds ({market_data['coins'][CAMPTOM_COIN_NAME]['price']:.2f}). Resetting to INITIAL_PRICE.")
    market_data["coins"][CAMPTOM_COIN_NAME]["price"] = INITIAL_PRICE
    save_data(market_data)

# --- Custom Checks & Helpers ---
async def is_bot_owner_slash(interaction: discord.Interaction) -> bool:
    return interaction.user.id == bot.owner_id

def has_more_than_three_decimals(number: float) -> bool:
    s = str(number)
    if '.' in s:
        decimal_part = s.split('.')[1]
        return len(decimal_part) > 3
    return False

# --- Role Assignment Helper ---
def check_and_assign_investor_role(user_id: int, guild: discord.Guild):
    if not MARKET_INVESTOR_ROLE_ID or not guild:
        return
    
    member = guild.get_member(user_id)
    if not member or member.bot:
        return
    
    inv_role = guild.get_role(MARKET_INVESTOR_ROLE_ID)
    if not inv_role:
        return
    
    user_data = get_user_data(user_id)
    balance = user_data.get("balance", 0.0)
    coins = user_data.get("portfolio", {}).get(CAMPTOM_COIN_NAME, 0.0)
    
    if (balance >= 20000.0 or coins >= 70.0) and inv_role not in member.roles:
        try:
            asyncio.create_task(member.add_roles(inv_role))
            print(f"Assigned Market Investor role to {member.display_name}")
        except Exception as e:
            print(f"Cannot assign role: {e}")

# --- Core Market Logic Functions ---
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
    
    save_data(market_data)
    print("Market price updated and buy cooldown cleared for all users.")

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
    save_data(market_data)
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
    save_data(market_data)
    return f"Successfully sold {quantity:.3f} {coin_name}(s) for {revenue:.2f} dollars."

async def _perform_crypto_to_cash_conversion():
    print("Initiating crypto to cash conversion logic...")
    
    if CAMPTOM_COIN_NAME not in market_data["coins"]:
        print(f"Warning: '{CAMPTOM_COIN_NAME}' not found in market data. Skipping conversion.")
        return 0 

    current_coin_price = market_data["coins"][CAMPTOM_COIN_NAME]["price"]
    
    target_guild = None
    if bot.guilds:
        target_guild = bot.guilds[0] 
    if target_guild is None:
        print(f"Warning: Bot is not in any guild. Cannot perform crypto to cash conversion.")
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
                del user_data["portfolio"][CAMPTOM_COIN_NAME]

                user_data["on_buy_cooldown"] = True 

                converted_count += 1
                print(f"Converted {user_campton_coins:.3f} {CAMPTOM_COIN_NAME} for {member.display_name} ({user_id}) to {cash_received:.2f} dollars.")

                try:
                    await member.send(
                        f"🔔 **Automatic Crypto Conversion!** 🔔\n\n"
                        f"Your {user_campton_coins:.3f} {CAMPTOM_COIN_NAME} holdings have been automatically converted to cash.\n"
                        f"You received **{cash_received:.2f} dollars** (at a price of {current_coin_price:.2f} dollars per coin).\n"
                        f"Your new cash balance is: **{user_data['balance']:.2f} dollars**.\n\n"
                        f"**You are now on a temporary buy cooldown and cannot purchase Campton Coin until after the next market price update.**"
                    )
                except discord.Forbidden:
                    print(f"Could not send DM to {member.display_name} about auto-conversion. DMs might be disabled.")
                except Exception as e:
                    print(f"Error sending auto-conversion DM to {member.display_name}: {e}")
    
    market_data["next_conversion_timestamp"] = (discord.utils.utcnow() + timedelta(days=7)).isoformat()
    save_data(market_data)
    print(f"Crypto to cash conversion logic complete. {converted_count} users processed.")
    return converted_count

# --- Scheduled Tasks ---
@tasks.loop(hours=72)
async def scheduled_price_update():
    print("Running scheduled price update...")
    await bot.change_presence(activity=discord.Game(name="Updating Market Prices...")) 
    update_prices() 
    await bot.change_presence(activity=discord.Game(name="Campton Stocks RP")) 
    if ANNOUNCEMENT_CHANNEL_ID:
        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            current_price = market_data["coins"][CAMPTOM_COIN_NAME]["price"]
            embed = discord.Embed(
                title="📈 Market Update: Campton Coin 📉",
                description=f"The price of Campton Coin has updated to **{current_price:.2f} dollars**.",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed)
        else:
            print(f"Warning: Announcement channel with ID {ANNOUNCEMENT_CHANNEL_ID} not found.")

@scheduled_price_update.before_loop
async def before_scheduled_price_update():
    await bot.wait_until_ready()
    print("Scheduled price update task is waiting for bot to be ready...")

@tasks.loop(minutes=5)
async def check_investor_roles():
    print("Running scheduled check for Market Investor roles...")
    if MARKET_INVESTOR_ROLE_ID is None:
        print("Warning: MARKET_INVESTOR_ROLE_ID is not configured. Skipping investor role checks.")
        return

    target_guild = None
    if bot.guilds:
        target_guild = bot.guilds[0]

    if target_guild is None:
        print(f"Warning: Bot is not in any guild. Cannot perform investor role checks.")
        return

    investor_role_obj = target_guild.get_role(MARKET_INVESTOR_ROLE_ID)
    if investor_role_obj is None:
        print(f"Warning: Market Investor role with ID {MARKET_INVESTOR_ROLE_ID} not found in guild {target_guild.name}. Skipping investor role checks.")
        return

    for member in target_guild.members:
        if member.bot:
            continue

        user_data = get_user_data(member.id)
        user_balance = user_data.get("balance", 0.0)
        campton_coins = user_data.get("portfolio", {}).get(CAMPTOM_COIN_NAME, 0.0)

        if (user_balance >= 20000.0 or campton_coins >= 70.0):
            if investor_role_obj not in member.roles:
                try:
                    await member.add_roles(investor_role_obj)
                    print(f"Assigned 'Market Investor' role to {member.display_name} ({member.id}).")
                    try:
                        await member.send(f"Congratulations! You've earned the **Market Investor** role in {target_guild.name} "
                                          f"for reaching a balance of {user_balance:.2f} dollars or holding {campton_coins:.3f} Campton Coins!")
                    except discord.Forbidden:
                        print(f"Could not send DM to {member.display_name} about Market Investor role. DMs might be disabled.")
                except discord.Forbidden:
                    print(f"ERROR: Bot lacks permissions to assign 'Market Investor' role to {member.display_name}. "
                          f"Ensure bot's role is higher than 'Market Investor' role and has 'Manage Roles' permission.")
                except Exception as e:
                    print(f"An unexpected error occurred while assigning 'Market Investor' role to {member.display_name}: {e}")

@check_investor_roles.before_loop
async def before_check_investor_roles():
    await bot.wait_until_ready()
    print("Scheduled Market Investor role check task is waiting for bot to be ready...")

@tasks.loop(hours=168)
async def auto_convert_crypto_to_cash():
    print("Running scheduled auto crypto to cash conversion...")
    await _perform_crypto_to_cash_conversion()
    print("Scheduled auto crypto to cash conversion task complete.")

@auto_convert_crypto_to_cash.before_loop
async def before_auto_convert_crypto_to_cash():
    await bot.wait_until_ready()
    print("Scheduled crypto to cash conversion task is waiting for bot to be ready...")

@tasks.loop(hours=36)
async def notify_conversion_countdown():
    print("Running scheduled conversion countdown notification...")
    
    target_guild = None
    if bot.guilds:
        target_guild = bot.guilds[0]
    if target_guild is None:
        print("Warning: Bot is not in any guild. Cannot send conversion countdown notifications.")
        return

    if "next_conversion_timestamp" not in market_data or market_data["next_conversion_timestamp"] is None:
        market_data["next_conversion_timestamp"] = (discord.utils.utcnow() + timedelta(days=7)).isoformat()
        save_data(market_data)
        print("Initialized next_conversion_timestamp as it was missing.")
    
    next_conversion_dt = datetime.datetime.fromisoformat(market_data["next_conversion_timestamp"])
    time_left = next_conversion_dt - discord.utils.utcnow()

    notification_message_base = (
        f"⏰ **Automatic Crypto Conversion Reminder!** ⏰\n\n"
        f"Your remaining Campton Coin holdings will be automatically converted to cash. "
        f"Once converted, you will be on a **temporary buy cooldown** until after the next market price update.\n\n"
    )
    notification_message_time = ""

    if time_left.total_seconds() < 0:
        notification_message_time = (
            f"The conversion is **very soon!** (It may be in progress or just completed)."
        )
    else:
        days_left = time_left.days
        remaining_seconds = time_left.seconds
        hours_left = math.ceil(remaining_seconds / 3600) 

        if days_left > 0:
            notification_message_time = (
                f"Approximately: **{days_left} days and {hours_left} hours**."
            )
        elif hours_left > 1:
            notification_message_time = (
                f"Approximately: **{hours_left} hours**."
            )
        else:
            notification_message_time = (
                f"**Within the next hour!**"
            )

    full_notification_message = notification_message_base + notification_message_time + "\n\nPlan your trades accordingly!"

    for member in target_guild.members:
        if member.bot:
            continue
        if full_notification_message:
            try:
                await member.send(full_notification_message)
                print(f"Sent conversion countdown DM to {member.display_name}.")
            except discord.Forbidden:
                print(f"Could not send conversion countdown DM to {member.display_name}. DMs might be disabled.")
            except Exception as e:
                print(f"Error sending conversion countdown DM to {member.display_name}: {e}")

@notify_conversion_countdown.before_loop
async def before_notify_conversion_countdown():
    await bot.wait_until_ready()
    print("Scheduled conversion countdown notification task is waiting for bot to be ready...")

# --- Ticket System Classes ---
class OpenTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Open New Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket_button")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not TICKET_CATEGORY_ID:
            await interaction.followup.send("Ticket system is not fully configured. Please contact the bot owner.", ephemeral=True)
            return

        for ticket_id, ticket_info in market_data["tickets"].items():
            if ticket_info["user_id"] == interaction.user.id and ticket_info["status"] == "open":
                existing_channel = bot.get_channel(int(ticket_id))
                if existing_channel:
                    await interaction.followup.send(f"You already have an open ticket: {existing_channel.mention}. Please use that ticket or close it first.", ephemeral=True)
                    return

        category = bot.get_channel(TICKET_CATEGORY_ID)
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("The ticket category could not be found or is misconfigured. Please contact the bot owner.", ephemeral=True)
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        owner = await bot.fetch_user(bot.owner_id)
        if owner:
            overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ticket_channel_name = f"ticket-{interaction.user.name.lower().replace(' ', '-')}-{interaction.user.discriminator or interaction.user.id}"
        try:
            new_channel = await category.create_text_channel(ticket_channel_name, overwrites=overwrites)
            
            market_data["tickets"][str(new_channel.id)] = {
                "user_id": interaction.user.id,
                "issue": "No specific issue provided via button.",
                "status": "open",
                "created_at": discord.utils.utcnow().isoformat()
            }
            save_data(market_data)

            ticket_embed = discord.Embed(
                title=f"New Ticket for {interaction.user.display_name}",
                description="A new ticket has been opened. Please describe your issue here.",
                color=discord.Color.orange()
            )
            ticket_embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
            ticket_embed.set_footer(text="A staff member will be with you shortly.")

            await new_channel.send(f"{interaction.user.mention}", embed=ticket_embed)
            await interaction.followup.send(f"Your ticket has been created! Please go to {new_channel.mention} to discuss your issue.", ephemeral=True)

            if owner:
                try:
                    await owner.send(f"A new ticket has been opened by {interaction.user.display_name} in {new_channel.mention}.")
                except discord.Forbidden:
                    print(f"Could not DM owner about new ticket. DMs might be disabled.")

        except discord.Forbidden:
            await interaction.followup.send("I don't have the necessary permissions to create channels. Please check my role permissions.", ephemeral=True)
        except Exception as e:
            print(f"Error creating ticket: {e}")
            await interaction.followup.send(f"An error occurred while creating your ticket: {e}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 
        self.add_item(OpenTicketButton())

class VerificationModal(ui.Modal, title='Project New Campton Verification'):
    roblox_username = ui.TextInput(label='Your Roblox Username', placeholder='e.g., RobloxPlayer123', style=discord.TextStyle.short)
    pnc_full_name = ui.TextInput(label='Project New Campton Full Name (First Last)', placeholder='e.g., John Doe', style=discord.TextStyle.short)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 

        member = interaction.user
        guild = interaction.guild

        if not guild:
            await interaction.followup.send("This verification can only be completed in a server.", ephemeral=True)
            return

        new_arrival_role = guild.get_role(NEW_ARRIVAL_ROLE_ID)
        campton_citizen_role = guild.get_role(CAMPTON_CITIZEN_ROLE_ID)

        if not new_arrival_role or not campton_citizen_role:
            await interaction.followup.send("Verification roles are not correctly configured. Please contact server staff.", ephemeral=True)
            print(f"ERROR: Verification roles not found. New Arrival ID: {NEW_ARRIVAL_ROLE_ID}, Citizen ID: {CAMPTON_CITIZEN_ROLE_ID}")
            return

        if campton_citizen_role in member.roles:
            await interaction.followup.send("You are already a Campton Citizen!", ephemeral=True)
            return

        user_data = get_user_data(member.id) 
        user_data["verification"]["roblox_username"] = str(self.roblox_username)
        user_data["verification"]["pnc_full_name"] = str(self.pnc_full_name)
        user_data["verification"]["verified_at"] = discord.utils.utcnow().isoformat()
        save_data(market_data)

        try:
            if new_arrival_role in member.roles:
                await member.remove_roles(new_arrival_role)
            await member.add_roles(campton_citizen_role)
            print(f"{member.display_name} ({member.id}) successfully verified. Roblox: {self.roblox_username}, PNC Name: {self.pnc_full_name}")
            
            try:
                await member.edit(nick=str(self.pnc_full_name))
                await interaction.followup.send(f"🎉 You have successfully verified and are now a Campton Citizen! Your server nickname has been updated to '{self.pnc_full_name}'. Welcome!", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send(
                    f"🎉 You have successfully verified and are now a Campton Citizen! Welcome! "
                    f"I couldn't change your nickname to '{self.pnc_full_name}'. Please ensure my role is higher than yours and I have 'Manage Nicknames' permission.",
                    ephemeral=True
                )
                print(f"WARNING: Bot lacks 'Manage Nicknames' permission to set nickname for {member.display_name} to '{self.pnc_full_name}'.")
            
        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to manage roles. Please ensure my role is higher than 'New Arrival' and 'Campton Citizen' and I have 'Manage Roles' permission.",
                ephemeral=True
            )
            print(f"ERROR: Bot lacks 'Manage Roles' permission to verify {member.display_name}.")
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred during verification: {e}", ephemeral=True)
            print(f"ERROR during verification for {member.display_name}: {e}")

class VerifyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Verify and Get Citizen Role", style=discord.ButtonStyle.primary, custom_id="verify_button")

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message("This verification can only be completed in a server.", ephemeral=True)
            return
        
        new_arrival_role = guild.get_role(NEW_ARRIVAL_ROLE_ID)
        campton_citizen_role = guild.get_role(CAMPTON_CITIZEN_ROLE_ID)

        if not new_arrival_role or not campton_citizen_role:
            await interaction.response.send_message("Verification roles are not correctly configured. Please contact server staff.", ephemeral=True)
            return

        if campton_citizen_role in member.roles:
            await interaction.response.send_message("You are already a Campton Citizen!", ephemeral=True)
            return
        
        if new_arrival_role not in member.roles:
             await interaction.response.send_message("You don't have the 'New Arrival' role. If you believe this is an error, please contact staff.", ephemeral=True)
             return

        await interaction.response.send_modal(VerificationModal())

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 
        self.add_item(VerifyButton())

# --- Discord Bot Events and Slash Commands ---

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    bot.add_view(TicketView())
    bot.add_view(VerifyView())
    await bot.tree.sync()
    print("Slash commands synced!")
    scheduled_price_update.start()
    check_investor_roles.start() 
    auto_convert_crypto_to_cash.start() 
    notify_conversion_countdown.start() 
    print("Scheduled price update task started.")
    print("Scheduled Market Investor role check task started.")
    print("Scheduled auto crypto to cash conversion task started.")
    print("Scheduled conversion countdown notification task started.")

@bot.event
async def on_member_join(member: discord.Member):
    print(f"Member joined: {member.display_name} ({member.id})")
    if NEW_ARRIVAL_ROLE_ID:
        role = member.guild.get_role(NEW_ARRIVAL_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
                print(f"Assigned 'New Arrival' role to {member.display_name}.")
                try:
                    await member.send(
                        f"Welcome to the Campton Coins server, {member.display_name}!\n\n"
                        f"Please head to the verification channel (<#{VERIFY_CHANNEL_ID}>) to verify your account and get full access.\n"
                        f"Click the 'Verify' button there and enter your Roblox Username and Project New Campton Full Name."
                    )
                    print(f"Sent verification DM to {member.display_name}.")
                except discord.Forbidden:
                    print(f"WARNING: Could not send verification DM to {member.display_name}. DMs might be disabled.")

            except discord.Forbidden:
                print(f"ERROR: Bot lacks permissions to assign 'New Arrival' role to {member.display_name}. "
                      f"Ensure bot's role is higher than 'New Arrival' role and has 'Manage Roles' permission.")
            except Exception as e:
                print(f"An unexpected error occurred while assigning 'New Arrival' role to {member.display_name}: {e}")
        else:
            print(f"Warning: 'New Arrival' role with ID {NEW_ARRIVAL_ROLE_ID} not found in guild {member.guild.name}.")
    else:
        print("Warning: NEW_ARRIVAL_ROLE_ID is not configured, skipping role assignment for new member.")

@bot.tree.command(name='prices', description='Displays the current price of Campton Coin.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.check(is_bot_owner_slash)
async def prices(interaction: discord.Interaction):
    await interaction.response.defer()
    update_prices() 
    embed = discord.Embed(title="Current Crypto Market Prices", color=0x00ff00)
    for coin_name, data in market_data["coins"].items():
        embed.add_field(name=coin_name, value=f"{data['price']:.2f} dollars", inline=True)
    await interaction.followup.send(embed=embed)

@prices.error
async def prices_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='balance', description='Shows your current balance and portfolio, or another member\'s.')
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer(ephemeral=True) 

    target_member = member or interaction.user 

    if target_member.bot:
        await interaction.followup.send(f"{target_member.display_name} is a bot and does not have a market balance.", ephemeral=True)
        return

    user = get_user_data(target_member.id)
    embed = discord.Embed(title=f"{target_member.display_name}'s Portfolio", color=0x0099ff)
    embed.add_field(name="Cash Balance", value=f"{user['balance']:.2f} dollars", inline=False)

    if user["portfolio"]:
        portfolio_str = ""
        total_value = 0
        for coin_name, quantity in user["portfolio"].items():
            current_price = market_data["coins"].get(coin_name, {}).get("price", 0)
            coin_value = current_price * quantity
            total_value += coin_value
            portfolio_str += f"- {coin_name}: **{quantity:.3f}** units (Value: {coin_value:.2f} dollars)\n"
        embed.add_field(name="Holdings", value=portfolio_str, inline=False)
    else:
        embed.add_field(name="Holdings", value="You own no cryptocurrencies." if target_member == interaction.user else f"{target_member.display_name} owns no cryptocurrencies.", inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name='buy', description='Buys Campton Coin with a specified amount of cash (up to 2 decimal places for cash).')
@app_commands.describe(amount_of_cash='The amount of cash you want to spend (e.g., 50.00).')
async def buy(interaction: discord.Interaction, amount_of_cash: float):
    await interaction.response.defer(ephemeral=True)
    coin_name = CAMPTOM_COIN_NAME

    user_data = get_user_data(interaction.user.id)
    if user_data.get("on_buy_cooldown", False):
        await interaction.followup.send("You cannot buy Campton Coin until after the next market price update (approximately every 3 days).", ephemeral=True)
        return

    if amount_of_cash <= 0:
        await interaction.followup.send("You must spend a positive amount of cash.", ephemeral=True)
        return

    s_cash = str(f"{amount_of_cash:.3f}")
    if '.' in s_cash:
        decimal_part_cash = s_cash.split('.')[1]
        if len(decimal_part_cash) > 2 and amount_of_cash * 100 != int(amount_of_cash * 100):
            await interaction.followup.send("You can only spend cash with up to 2 decimal places (e.g., 50.00).", ephemeral=True)
            return
    
    current_coin_price = market_data["coins"][coin_name]["price"]
    if current_coin_price <= 0: 
        await interaction.followup.send("Cannot buy Campton Coin right now, its price is too low or zero.", ephemeral=True)
        return

    quantity_of_coins_to_buy = amount_of_cash / current_coin_price
    quantity_of_coins_to_buy = math.floor(quantity_of_coins_to_buy * 1000) / 1000.0

    result = buy_coin_logic(interaction.user.id, coin_name, quantity_of_coins_to_buy) 
    
    if "Successfully bought" in result:
        await interaction.followup.send(f"Successfully spent {amount_of_cash:.2f} dollars to buy {quantity_of_coins_to_buy:.3f} {coin_name}(s). Your new cash balance is {get_user_data(interaction.user.id)['balance']:.2f} dollars.", ephemeral=True)
        check_and_assign_investor_role(interaction.user.id, interaction.guild)
    else:
        await interaction.followup.send(result, ephemeral=True)

@bot.tree.command(name='sell', description='Sells a specified quantity of Campton Coin (up to 3 decimal places).')
@app_commands.describe(quantity='The number of Campton Coins to sell (e.g., 0.123).')
async def sell(interaction: discord.Interaction, quantity: float):
    await interaction.response.defer(ephemeral=True)
    coin_name = CAMPTOM_COIN_NAME

    if quantity <= 0:
        await interaction.followup.send("You must sell a positive amount.", ephemeral=True)
        return

    if has_more_than_three_decimals(quantity):
        await interaction.followup.send("You can only sell Campton Coin with up to 3 decimal places (e.g., 0.123).", ephemeral=True)
        return

    result = sell_coin_logic(interaction.user.id, coin_name, quantity) 
    await interaction.followup.send(result, ephemeral=True)
    check_and_assign_investor_role(interaction.user.id, interaction.guild)

@bot.tree.command(name='addfunds', description='Adds funds to a specified user\'s balance. (Bot Owner Only)')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(member='The user to add funds to.', amount='The amount of funds to add.')
@app_commands.check(is_bot_owner_slash)
async def add_funds(interaction: discord.Interaction, member: discord.Member, amount: float):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id != bot.owner_id:
        await interaction.followup.send("You must be the bot owner to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.followup.send("Amount must be greater than 0.", ephemeral=True)
        return

    user_data = get_user_data(member.id)
    user_data["balance"] += amount
    save_data(market_data)

    await interaction.followup.send(f"Successfully added {amount:.2f} dollars to {member.display_name}'s balance. Their new balance is {user_data['balance']:.2f} dollars.", ephemeral=True)

@bot.tree.command(name='addcoins', description='(Owner) Add Campton Coin to a member\'s portfolio.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(member='The user to add coins to.', quantity='The number of coins to add.')
@app_commands.check(is_bot_owner_slash)
async def addcoins(interaction: discord.Interaction, member: discord.Member, quantity: float):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id != bot.owner_id:
        await interaction.followup.send("You must be the bot owner to use this command.", ephemeral=True)
        return

    if quantity <= 0:
        await interaction.followup.send("Quantity must be greater than 0.", ephemeral=True)
        return

    if has_more_than_three_decimals(quantity):
        await interaction.followup.send("You can only add coins with up to 3 decimal places (e.g., 0.123).", ephemeral=True)
        return

    user_data = get_user_data(member.id)
    user_data["portfolio"][CAMPTOM_COIN_NAME] = user_data["portfolio"].get(CAMPTOM_COIN_NAME, 0.0) + quantity
    save_data(market_data)

    await interaction.followup.send(f"Successfully added {quantity:.3f} {CAMPTOM_COIN_NAME} to {member.display_name}'s portfolio. They now have {user_data['portfolio'][CAMPTOM_COIN_NAME]:.3f} coins.", ephemeral=True)

@addcoins.error
async def addcoins_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)

@bot.tree.command(name='withdraw', description='Requests a withdrawal of funds from your balance. Funds are deducted upon owner approval.')
@app_commands.describe(amount='The amount of funds to request for withdrawal.')
async def withdraw(interaction: discord.Interaction, amount: float):
    await interaction.response.defer(ephemeral=True)

    if amount <= 0:
        await interaction.followup.send("You must request a positive amount for withdrawal.", ephemeral=True)
        return

    user_data = get_user_data(interaction.user.id)
    if user_data["balance"] < amount:
        await interaction.followup.send(f"Insufficient funds. You only have {user_data['balance']:.2f} dollars.", ephemeral=True)
        return

    owner = await bot.fetch_user(bot.owner_id)
    if owner:
        try:
            withdrawal_embed = discord.Embed(
                title="❗ New Withdrawal Request ❗",
                description=f"**{interaction.user.display_name}** (`{interaction.user.id}`) has requested a withdrawal.",
                color=discord.Color.red()
            )
            withdrawal_embed.add_field(name="Requested Amount", value=f"{amount:.2f} dollars", inline=False)
            withdrawal_embed.add_field(name="User's Current Balance", value=f"{user_data['balance']:.2f} dollars", inline=False)
            withdrawal_embed.set_footer(text=f"To approve, use /approvewithdrawal {interaction.user.id} {amount}")

            await owner.send(embed=withdrawal_embed)
            await interaction.followup.send(f"Your withdrawal request for {amount:.2f} dollars has been sent to the bot owner for approval. Your balance remains {user_data['balance']:.2f} dollars for now.", ephemeral=True)
        except discord.Forbidden:
            print(f"Could not send DM to owner {owner.name} about withdrawal request. DMs might be disabled.")
            await interaction.followup.send("Could not send the withdrawal request to the bot owner. Please ensure the bot can DM the owner.", ephemeral=True)
    else:
        await interaction.followup.send("Could not find the bot owner to send the withdrawal request. Please ensure the bot owner is correctly configured.", ephemeral=True)

@bot.tree.command(name='approvewithdrawal', description='Approves a user\'s withdrawal request and deducts funds. (Bot Owner Only)')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(user_id='The ID of the user whose withdrawal to approve.', amount='The Amount to deduct.')
@app_commands.check(is_bot_owner_slash)
async def approve_withdrawal(interaction: discord.Interaction, user_id: str, amount: float):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id != bot.owner_id:
        await interaction.followup.send("You must be the bot owner to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.followup.send("Amount must be greater than 0.", ephemeral=True)
        return

    try:
        target_user = await bot.fetch_user(int(user_id))
    except ValueError:
        await interaction.followup.send("Invalid user ID provided. Please provide a numerical user ID.", ephemeral=True)
        return
    except discord.NotFound:
        await interaction.followup.send("User not found with the provided ID.", ephemeral=True)
        return

    user_data = get_user_data(target_user.id)

    if user_data["balance"] < amount:
        await interaction.followup.send(f"User {target_user.display_name} only has {user_data['balance']:.2f} dollars, which is less than the requested {amount:.2f} dollars. Cannot approve.", ephemeral=True)
        return

    user_data["balance"] -= amount
    save_data(market_data)

    await interaction.followup.send(f"Successfully approved withdrawal of {amount:.2f} dollars for {target_user.display_name}. Their new balance is {user_data['balance']:.2f} dollars.", ephemeral=True)

    try:
        user_approved_embed = discord.Embed(
            title="✅ Withdrawal Approved! ✅",
            description=f"Your withdrawal request for {amount:.2f} dollars has been approved by the bot owner.",
            color=discord.Color.green()
        )
        await target_user.send(embed=user_approved_embed)
    except discord.Forbidden:
        print(f"Could not send DM to user {target_user.name} about approved withdrawal. DMs might be disabled.")

@bot.tree.command(name='transfer', description='Transfer cash or Campton Coin to another user.')
@app_commands.describe(
    recipient='The user to transfer funds/coins to.',
    amount='The amount to transfer (e.g., 50.00 or 5).',
    currency_type='The type of currency to transfer.'
)
@app_commands.choices(currency_type=[
    app_commands.Choice(name='Cash', value='cash'),
    app_commands.Choice(name='Campton Coin', value='campton_coin')
])
async def transfer(interaction: discord.Interaction, recipient: discord.Member, amount: float, currency_type: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)

    if amount <= 0:
        await interaction.followup.send("You must transfer a positive amount.", ephemeral=True)
        return

    if currency_type.value == 'campton_coin' and has_more_than_three_decimals(amount):
        await interaction.followup.send("You can only transfer Campton Coin with up to 3 decimal places (e.g., 0.123).", ephemeral=True)
        return

    if interaction.user.id == recipient.id:
        await interaction.followup.send("You cannot transfer to yourself.", ephemeral=True)
        return

    sender_data = get_user_data(interaction.user.id)
    recipient_data = get_user_data(recipient.id)
    currency_value = currency_type.value
    currency_name = currency_type.name

    transfer_successful = False
    feedback_message = ""
    recipient_dm_message = ""

    if currency_value == 'cash':
        if sender_data["balance"] < amount:
            feedback_message = f"Insufficient funds. You only have {sender_data['balance']:.2f} dollars."
        else:
            sender_data["balance"] -= amount
            recipient_data["balance"] += amount
            transfer_successful = True
            feedback_message = f"Successfully transferred {amount:.2f} dollars to {recipient.display_name}. Your new balance is {sender_data['balance']:.2f} dollars."
            recipient_dm_message = f"You received {amount:.2f} dollars from {interaction.user.display_name}. Your new balance is {recipient_data['balance']:.2f} dollars."
    elif currency_value == 'campton_coin':
        coin_name = CAMPTOM_COIN_NAME
        if coin_name not in sender_data["portfolio"] or sender_data["portfolio"][coin_name] < amount:
            feedback_message = f"Insufficient Campton Coins. You only have {sender_data['portfolio'].get(coin_name, 0.0):.3f} {coin_name}(s)."
        else:
            sender_data["portfolio"][coin_name] -= amount
            recipient_data["portfolio"][coin_name] = recipient_data["portfolio"].get(coin_name, 0.0) + amount
            if sender_data["portfolio"][coin_name] <= 0.0001:
                del sender_data["portfolio"][coin_name]
            transfer_successful = True
            feedback_message = f"Successfully transferred {amount:.3f} {coin_name}(s) to {recipient.display_name}. You now have {sender_data['portfolio'].get(coin_name, 0.0):.3f} {coin_name}(s)."
            recipient_dm_message = f"You received {amount:.3f} {coin_name}(s) from {interaction.user.display_name}. You now have {recipient_data['portfolio'].get(coin_name, 0.0):.3f} {coin_name}(s)."
    else:
        feedback_message = "Invalid currency type specified."

    if transfer_successful:
        save_data(market_data)
        await interaction.followup.send(feedback_message, ephemeral=True)
        if recipient_dm_message:
            try:
                recipient_embed = discord.Embed(
                    title=f"💰 {currency_name} Transfer Received! 💰",
                    description=recipient_dm_message,
                    color=discord.Color.green()
                )
                await recipient.send(embed=recipient_embed)
            except discord.Forbidden:
                print(f"Could not send DM to {recipient.name}. DMs might be disabled.")
                await interaction.followup.send(f"Note: Could not DM {recipient.display_name} about the transfer. They might have DMs disabled.", ephemeral=True)
    else:
        await interaction.followup.send(feedback_message, ephemeral=True)

@bot.tree.command(name='sendticketbutton', description='(Owner Only) Sends the "Open Ticket" button to the current channel.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.check(is_bot_owner_slash)
async def send_ticket_button(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    if interaction.channel.id != HELP_DESK_CHANNEL_ID:
        await interaction.followup.send(f"This command should ideally be used in the designated help desk channel (<#{HELP_DESK_CHANNEL_ID}>).", ephemeral=True)

    embed = discord.Embed(
        title="Need Help? Open a Support Ticket!",
        description="Click the button below to open a private support ticket with the staff. Please describe your issue clearly once the ticket channel is created.",
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=embed, view=TicketView())
    await interaction.followup.send("The 'Open Ticket' button has been sent to this channel.", ephemeral=True)

@send_ticket_button.error
async def send_ticket_button_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='sendverifybutton', description='(Owner Only) Sends the "Verify" button to the current channel.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.check(is_bot_owner_slash)
async def send_verify_button(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if interaction.channel.id != VERIFY_CHANNEL_ID:
        await interaction.followup.send(f"This command should ideally be used in the designated verify channel (<#{VERIFY_CHANNEL_ID}>).", ephemeral=True)

    embed = discord.Embed(
        title="Welcome, New Arrival! Please Verify.",
        description="Click the button below to verify your account and gain full access to the server as a Campton Citizen!\n\n**You will be asked for your Roblox Username and Project New Campton Full Name.**",
        color=discord.Color.purple()
    )
    await interaction.channel.send(embed=embed, view=VerifyView())
    await interaction.followup.send("The 'Verify' button has been sent to this channel.", ephemeral=True)

@send_verify_button.error
async def send_verify_button_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='close', description='Close the current support ticket. (Can only be used in a ticket channel)')
async def close(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not TICKET_CATEGORY_ID:
        await interaction.followup.send("Ticket system is not fully configured. Please contact the bot owner.", ephemeral=True)
        return

    if str(interaction.channel.id) not in market_data["tickets"]:
        await interaction.followup.send("This command can only be used in a ticket channel.", ephemeral=True)
        return

    ticket_info = market_data["tickets"][str(interaction.channel.id)]
    
    if interaction.user.id != ticket_info["user_id"] and interaction.user.id != bot.owner_id:
        await interaction.followup.send("You must be the ticket creator or bot owner to close this ticket.", ephemeral=True)
        return

    confirm_view = discord.ui.View(timeout=300)
    confirm_button = discord.ui.Button(label="Confirm Close", style=discord.ButtonStyle.red)

    async def confirm_callback(button_interaction: discord.Interaction):
        await button_interaction.response.defer(ephemeral=True)

        if button_interaction.user.id != interaction.user.id and button_interaction.user.id != bot.owner_id:
            await button_interaction.followup.send("Only the person who initiated the close can confirm.", ephemeral=True)
            return

        ticket_info["status"] = "closed"
        ticket_info["closed_at"] = discord.utils.utcnow().isoformat()
        save_data(market_data)

        await interaction.channel.send("Ticket closed. This channel will be deleted shortly.")
        
        await asyncio.sleep(5)
        
        try:
            await interaction.channel.delete()
        except discord.Forbidden:
            await button_interaction.followup.send(
                "I do not have permission to delete channels. Please ensure I have 'Manage Channels' permission in this category.",
                ephemeral=True
            )
            print(f"ERROR: Bot lacks 'Manage Channels' permission to delete ticket {interaction.channel.name} ({interaction.channel.id}).")
        except Exception as e:
            await button_interaction.followup.send(f"An unexpected error occurred while deleting the channel: {e}", ephemeral=True)
            print(f"ERROR deleting ticket channel {interaction.channel.name} ({interaction.channel.id}): {e}")

    confirm_button.callback = confirm_callback
    confirm_view.add_item(confirm_button)

    await interaction.followup.send("Are you sure you want to close this ticket?", view=confirm_view, ephemeral=True)

@bot.tree.command(name='clearmessages', description='(Owner Only) Clears a specified number of messages from the current channel.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(amount='The number of messages to clear (1-100).')
@app_commands.check(is_bot_owner_slash)
async def clearmessages(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)

    if not (1 <= amount <= 100):
        await interaction.followup.send("You can only clear between 1 and 100 messages.", ephemeral=True)
        return

    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Successfully cleared {len(deleted)} messages.", ephemeral=True)
        print(f"Cleared {len(deleted)} messages in #{interaction.channel.name} by {interaction.user.display_name}.")
    except discord.Forbidden:
        await interaction.followup.send(
            "I do not have permission to manage messages in this channel. Please ensure I have 'Manage Messages' permission.",
            ephemeral=True
        )
        print(f"ERROR: Bot lacks 'Manage Messages' permission in #{interaction.channel.name} for clearmessages.")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)
        print(f"ERROR clearing messages in #{interaction.channel.name}: {e}")

@clearmessages.error
async def clearmessages_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.MissingRequiredArgument):
        await interaction.response.send_message("Missing arguments. Usage: `/clearmessages <amount>`", ephemeral=True)
    elif isinstance(error, app_commands.BadArgument):
        await interaction.response.send_message("Invalid amount. Please provide a number.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='lockdown', description='(Owner Only) Locks down the current channel or a specified channel.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(channel='The channel to lock down (defaults to current channel).')
@app_commands.check(is_bot_owner_slash)
async def lockdown(interaction: discord.Interaction, channel: discord.TextChannel = None):
    await interaction.response.defer(ephemeral=True)
    target_channel = channel or interaction.channel

    current_overwrites = target_channel.overwrites_for(interaction.guild.default_role)
    if current_overwrites.send_messages is False:
        await interaction.followup.send(f"{target_channel.mention} is already locked down.", ephemeral=True)
        return

    try:
        await target_channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await target_channel.send(f"🔒 This channel has been locked down by {interaction.user.mention}. Only staff can send messages.")
        await interaction.followup.send(f"Successfully locked down {target_channel.mention}.", ephemeral=True)
        print(f"Locked down #{target_channel.name} by {interaction.user.display_name}.")
    except discord.Forbidden:
        await interaction.followup.send(
            "I do not have permission to manage channels. Please ensure I have 'Manage Channels' permission and my role is higher than `@everyone`.",
            ephemeral=True
        )
        print(f"ERROR: Bot lacks 'Manage Channels' permission to lockdown #{target_channel.name}.")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)
        print(f"ERROR locking down #{target_channel.name}: {e}")

@lockdown.error
async def lockdown_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.BadArgument):
        await interaction.response.send_message("Invalid channel provided. Please mention a valid text channel.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='unlock', description='(Owner Only) Unlocks the current channel or a specified channel.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(channel='The channel to unlock (defaults to current channel).')
@app_commands.check(is_bot_owner_slash)
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    await interaction.response.defer(ephemeral=True)
    target_channel = channel or interaction.channel

    current_overwrites = target_channel.overwrites_for(interaction.guild.default_role)
    if current_overwrites.send_messages is not False: 
        await interaction.followup.send(f"{target_channel.mention} is not currently locked down.", ephemeral=True)
        return

    try:
        await target_channel.set_permissions(interaction.guild.default_role, send_messages=None)
        await target_channel.send(f"🔓 This channel has been unlocked by {interaction.user.mention}. Members can now send messages.")
        await interaction.followup.send(f"Successfully unlocked {target_channel.mention}.", ephemeral=True)
        print(f"Unlocked #{target_channel.name} by {interaction.user.display_name}.")
    except discord.Forbidden:
        await interaction.followup.send(
            "I do not have permission to manage channels. Please ensure I have 'Manage Channels' permission and my role is higher than `@everyone`.",
            ephemeral=True
        )
        print(f"ERROR: Bot lacks 'Manage Channels' permission to unlock #{target_channel.name}.")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)
        print(f"ERROR unlocking #{target_channel.name}: {e}")

@unlock.error
async def unlock_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.BadArgument):
        await interaction.response.send_message("Invalid channel provided. Please mention a valid text channel.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='manualconvert', description='(Owner Only) Manually triggers the crypto to cash conversion for all users.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.check(is_bot_owner_slash)
async def manual_convert(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    print(f"Manual crypto to cash conversion triggered by {interaction.user.display_name} ({interaction.user.id}).")
    
    converted_count = await _perform_crypto_to_cash_conversion()
    
    await interaction.followup.send(f"Manual crypto to cash conversion initiated. {converted_count} users had their Campton Coin converted. All affected users are now on a buy cooldown until the next price update.", ephemeral=True)

@manual_convert.error
async def manual_convert_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='setprice', description='(Owner) Manually set the price of Campton Coin.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(amount='The new price for Campton Coin (e.g., 150.75).')
@app_commands.check(is_bot_owner_slash)
async def set_price_cmd(interaction: discord.Interaction, amount: float):
    await interaction.response.defer(ephemeral=True)

    if amount <= 0:
        await interaction.followup.send("The price must be a positive number.", ephemeral=True)
        return

    if amount < MIN_PRICE or amount > MAX_PRICE:
        await interaction.followup.send(f"The price must be between {MIN_PRICE:.2f} and {MAX_PRICE:.2f} dollars.", ephemeral=True)
        return
    
    new_price = round(amount, 2)

    market_data["coins"][CAMPTOM_COIN_NAME]["price"] = new_price
    save_data(market_data)

    await interaction.followup.send(f"✅ Campton Coin price has been manually set to **{new_price:.2f} dollars**.", ephemeral=True)
    print(f"Campton Coin price manually set to {new_price:.2f} by {interaction.user.display_name}.")

@set_price_cmd.error
async def set_price_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

@bot.tree.command(name='save', description='(Owner) Manually save all market data.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.check(is_bot_owner_slash)
async def save_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        save_data(market_data)
        await interaction.followup.send("✅ Market data saved successfully.", ephemeral=True)
        print(f"Manual save triggered by {interaction.user.display_name}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error saving data: {e}", ephemeral=True)
        print(f"Save failed: {e}")

@save_cmd.error
async def save_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("Only the bot owner can use this.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)

@bot.tree.command(name='announce', description='(Owner) Make the bot announce something to the channel.')
@app_commands.default_permissions(manage_guild=False) # <--- ADDED: Hide from non-admins
@app_commands.describe(message='The message for the bot to announce.')
@app_commands.check(is_bot_owner_slash)
async def announce(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await interaction.channel.send(message)
        await interaction.followup.send("✅ Announcement sent.", ephemeral=True)
        print(f"Announcement sent by {interaction.user.display_name}: {message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error sending announcement: {e}", ephemeral=True)
        print(f"Error sending announcement: {e}")

@announce.error
async def announce_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("Only the bot owner can use this.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)


@bot.tree.command(name='ping', description='Checks the bot\'s latency to Discord.')
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! Latency: {round(bot.latency * 1000)}ms", ephemeral=True)


# This bot.py file is designed to be run via main.py, which starts the bot.
bot.run(TOKEN)
