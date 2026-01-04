import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import io
import random
from datetime import datetime

# =======================
# CONFIG
# =======================

OWNER_ID = 357681843790675978
CO_OWNER_IDS = {244214611400851458}
LOG_RECEIVER_ID = 1321335530364993608

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is not set")

# =======================
# PERMISSIONS
# =======================

def is_owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

def is_co_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID or interaction.user.id in CO_OWNER_IDS

# =======================
# BOT SETUP
# =======================

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =======================
# IN-MEMORY LOG SENDER
# =======================

async def send_json_dm(payload: dict, filename: str, message: str):
    try:
        user = await bot.fetch_user(LOG_RECEIVER_ID)

        json_bytes = io.BytesIO(
            json.dumps(payload, indent=4).encode("utf-8")
        )
        json_bytes.seek(0)

        await user.send(
            content=message,
            file=discord.File(fp=json_bytes, filename=filename)
        )
    except Exception as e:
        print(f"Failed to send DM log: {e}")

# =======================
# COMMAND LOGGING (AUTO)
# =======================

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    payload = {
        "type": "command_execution",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": interaction.command.name,
        "user": {
            "id": interaction.user.id,
            "username": str(interaction.user)
        }
    }

    await send_json_dm(
        payload,
        filename=f"command_{interaction.command.name}.json",
        message="📜 Command executed"
    )

# =======================
# ECONOMY DATA (IN MEMORY)
# =======================

market_data = {
    "price": 1.0,
    "users": {}
}

def get_user(user_id: int):
    uid = str(user_id)
    if uid not in market_data["users"]:
        market_data["users"][uid] = {"cash": 0.0, "coins": 0.0}
    return market_data["users"][uid]

# =======================
# AUTO PRICE UPDATE (3 DAYS)
# =======================

@tasks.loop(hours=72)
async def auto_price_update():
    old_price = market_data["price"]

    # simple random market movement
    change = random.uniform(-0.1, 0.15)
    new_price = round(max(0.01, old_price + change), 4)

    market_data["price"] = new_price

    payload = {
        "type": "auto_price_update",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "old_price": old_price,
        "new_price": new_price,
        "change": round(new_price - old_price, 4),
        "direction": "up" if new_price > old_price else "down" if new_price < old_price else "no change"
    }

    await send_json_dm(
        payload,
        filename="auto_price_update.json",
        message="📈 Automatic 3-day price update"
    )

# =======================
# EVENTS
# =======================

@bot.event
async def on_ready():
    await bot.tree.sync()
    auto_price_update.start()
    print(f"Logged in as {bot.user}")

# =======================
# OWNER ONLY (HIDDEN)
# =======================

@app_commands.check(is_owner_only)
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="setprice", description="Set coin price (OWNER ONLY)")
async def setprice(interaction: discord.Interaction, amount: float):
    market_data["price"] = round(amount, 4)
    await interaction.response.send_message(f"Price set to **${market_data['price']}**")

@app_commands.check(is_owner_only)
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="prices", description="View price (OWNER ONLY)")
async def prices(interaction: discord.Interaction):
    await interaction.response.send_message(f"Current price: **${market_data['price']}**")

# =======================
# ADMIN / CO-OWNER
# =======================

@app_commands.check(is_co_owner)
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="addfunds", description="Add cash to a user")
async def addfunds(interaction: discord.Interaction, member: discord.Member, amount: float):
    user = get_user(member.id)
    user["cash"] += amount
    await interaction.response.send_message(f"Added **${amount}** to {member.mention}")

@app_commands.check(is_co_owner)
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="addcoins", description="Add coins to a user")
async def addcoins(interaction: discord.Interaction, member: discord.Member, amount: float):
    user = get_user(member.id)
    user["coins"] += amount
    await interaction.response.send_message(f"Added **{amount} coins** to {member.mention}")

@app_commands.check(is_co_owner)
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="announce", description="Make an announcement")
async def announce(interaction: discord.Interaction, message: str):
    await interaction.channel.send(f"📢 **Announcement**\n{message}")
    await interaction.response.send_message("Announcement sent.", ephemeral=True)

# =======================
# USER COMMANDS
# =======================

@bot.tree.command(name="balance", description="View balance")
async def balance(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    user = get_user(target.id)

    await interaction.response.send_message(
        f"**{target.display_name}**\n"
        f"Cash: **${user['cash']}**\n"
        f"Coins: **{user['coins']}**"
    )

@bot.tree.command(name="buy", description="Buy coins")
async def buy(interaction: discord.Interaction, amount: float):
    user = get_user(interaction.user.id)
    cost = amount * market_data["price"]

    if user["cash"] < cost:
        return await interaction.response.send_message("Not enough cash.")

    user["cash"] -= cost
    user["coins"] += amount
    await interaction.response.send_message(f"Bought **{amount} coins** for **${cost}**")

@bot.tree.command(name="sell", description="Sell coins")
async def sell(interaction: discord.Interaction, amount: float):
    user = get_user(interaction.user.id)

    if user["coins"] < amount:
        return await interaction.response.send_message("Not enough coins.")

    user["coins"] -= amount
    user["cash"] += amount * market_data["price"]
    await interaction.response.send_message(f"Sold **{amount} coins**")

@bot.tree.command(name="viewprice", description="View current coin price")
async def viewprice(interaction: discord.Interaction):
    await interaction.response.send_message(f"Current price: **${market_data['price']}**")

@bot.tree.command(name="ping", description="Ping the bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong 🏓")

# =======================
# START BOT
# =======================

bot.run(TOKEN)
