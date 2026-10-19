# Updated discord_bot.py - Replace your existing file with this

import discord
from discord.ext import commands
import os
import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
WEB_APP_URL = os.environ.get('WEB_APP_URL', 'http://localhost:5000')
DISCORD_BOT_SECRET = os.environ.get('DISCORD_BOT_SECRET', '')
BOT_HEADERS = {"X-Bot-Secret": DISCORD_BOT_SECRET}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# ACCOUNT MANAGEMENT

@bot.tree.command(name="create-account", description="Create a new account")
async def create_account(interaction: discord.Interaction, username: str, password: str):
    """Create new account in web app"""
    try:
        response = requests.post(
            f"{WEB_APP_URL}/discord/create-account",
            json={"username": username, "password": password, "secret": DISCORD_BOT_SECRET},
            timeout=5
        )
        if response.status_code == 200:
            embed = discord.Embed(
                title="✅ Account Created!",
                description=f"Account **{username}** created successfully!\n\nYou can now use `/link-account` to link your Discord.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title="❌ Error", description=response.json().get('error', 'Failed'), color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="link-account", description="Link Discord to your account")
async def link_account(interaction: discord.Interaction, username: str, password: str):
    """Link Discord to existing account"""
    user = interaction.user
    discord_id = str(user.id)
    discord_username = user.name
    
    try:
        response = requests.post(
            f"{WEB_APP_URL}/discord/link-existing",
            json={
                "discord_id": discord_id,
                "discord_username": discord_username,
                "username": username,
                "password": password,
                "secret": DISCORD_BOT_SECRET
            },
            timeout=5
        )
        if response.status_code == 200:
            embed = discord.Embed(
                title="✅ Account Linked!",
                description=f"Your Discord is linked to **{username}**",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title="❌ Error", description=response.json().get('error', 'Failed'), color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

# EQUIPMENT & EVENTS

@bot.tree.command(name="find", description="Search equipment")
async def find_equipment(interaction: discord.Interaction, query: str):
    """Find equipment by name"""
    try:
        response = requests.get(f"{WEB_APP_URL}/discord/search-equipment/{query}", headers=BOT_HEADERS, timeout=5)
        if response.status_code == 200:
            equipment = response.json().get('equipment', [])
            if not equipment:
                embed = discord.Embed(title="❌ Not Found", description=f"No equipment found for '{query}'", color=discord.Color.red())
            else:
                embed = discord.Embed(title=f"🔍 Search Results: {query}", color=discord.Color.blue())
                for item in equipment[:10]:
                    embed.add_field(
                        name=item['name'],
                        value=f"📍 {item['location']}\n📦 {item['category']}\n🏷️ `{item['barcode']}`",
                        inline=False
                    )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="events", description="List all events")
async def list_events(interaction: discord.Interaction):
    """List upcoming events"""
    try:
        response = requests.get(f"{WEB_APP_URL}/discord/list-events", headers=BOT_HEADERS, timeout=5)
        if response.status_code == 200:
            events = response.json().get('events', [])
            if not events:
                embed = discord.Embed(title="📅 Events", description="No upcoming events", color=discord.Color.blue())
            else:
                embed = discord.Embed(title="📅 Upcoming Events", color=discord.Color.blue())
                for event in events[:10]:
                    embed.add_field(
                        name=f"{event['title']} (ID: {event['id']})",
                        value=f"📅 {event['date']}\n📍 {event['location']}\n👥 {event['crew_count']} crew",
                        inline=False
                    )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="crew", description="List crew for an event")
async def list_crew(interaction: discord.Interaction, event_id: int):
    """List crew assigned to event"""
    try:
        response = requests.get(f"{WEB_APP_URL}/discord/event-crew/{event_id}", headers=BOT_HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            event_title = data.get('event_title', 'Event')
            crew = data.get('crew', [])
            
            if not crew:
                embed = discord.Embed(title=f"👥 {event_title}", description="No crew assigned yet", color=discord.Color.blue())
            else:
                embed = discord.Embed(title=f"👥 {event_title} - Crew ({len(crew)})", color=discord.Color.blue())
                for member in crew:
                    embed.add_field(name=member['name'], value=f"🎭 {member['role']}", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

# PICK LIST COMMAND - FIXED
@bot.tree.command(name="pick-list", description="View pick list for event")
async def pick_list(interaction: discord.Interaction, event_id: int):
    """View pick list items - FIXED VERSION"""
    try:
        response = requests.get(f"{WEB_APP_URL}/discord/pick-list/{event_id}", headers=BOT_HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            event_title = data.get('event_title', 'Event')
            items = data.get('items', [])
            
            if not items:
                embed = discord.Embed(title=f"📋 {event_title}", description="No items in pick list", color=discord.Color.blue())
            else:
                checked = sum(1 for item in items if item['is_checked'])
                embed = discord.Embed(
                    title=f"📋 {event_title}",
                    description=f"Progress: {checked}/{len(items)} items gathered",
                    color=discord.Color.blue()
                )
                for item in items[:20]:  # Show max 20 items
                    status = "✅" if item['is_checked'] else "⬜"
                    location = item.get('location', 'N/A')
                    category = item.get('category', 'N/A')
                    embed.add_field(
                        name=f"{status} {item['name']}",
                        value=f"Qty: {item['quantity']} | 📍 {location} | 📦 {category}",
                        inline=False
                    )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title="❌ Error", description="Event not found or has no pick list", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

# EVENT MANAGEMENT

@bot.tree.command(name="join-event", description="Join event by ID")
async def join_event(interaction: discord.Interaction, event_id: int):
    """Join an event"""
    discord_id = str(interaction.user.id)
    try:
        response = requests.post(
            f"{WEB_APP_URL}/discord/join-event",
            json={"discord_id": discord_id, "event_id": event_id, "secret": DISCORD_BOT_SECRET},
            timeout=5
        )
        if response.status_code == 200:
            embed = discord.Embed(title="✅ Joined!", description=f"Added to event #{event_id}", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title="❌ Error", description=response.json().get('error', 'Failed'), color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="leave-event", description="Leave event by ID")
async def leave_event(interaction: discord.Interaction, event_id: int):
    """Leave an event"""
    discord_id = str(interaction.user.id)
    try:
        response = requests.post(
            f"{WEB_APP_URL}/discord/leave-event",
            json={"discord_id": discord_id, "event_id": event_id, "secret": DISCORD_BOT_SECRET},
            timeout=5
        )
        if response.status_code == 200:
            embed = discord.Embed(title="✅ Left Event", description=f"Removed from event #{event_id}", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title="❌ Error", description=response.json().get('error', 'Failed'), color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="my-events", description="Your assigned events")
async def my_events(interaction: discord.Interaction):
    """Show your events"""
    discord_id = str(interaction.user.id)
    try:
        response = requests.get(f"{WEB_APP_URL}/discord/user-events/{discord_id}", headers=BOT_HEADERS, timeout=5)
        if response.status_code == 200:
            events = response.json().get('events', [])
            if not events:
                embed = discord.Embed(title="📅 Your Events", description="Not assigned to any events", color=discord.Color.blue())
            else:
                embed = discord.Embed(title=f"📅 Your Events ({len(events)})", color=discord.Color.blue())
                for event in events:
                    embed.add_field(
                        name=f"🎭 {event['title']}",
                        value=f"📅 {event['date']}\n📍 {event['location']}\n👤 {event['role']}",
                        inline=False
                    )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(title="❌ Error", description=str(e), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Show all commands")
async def help_command(interaction: discord.Interaction):
    """Show help"""
    embed = discord.Embed(title="🎭 Production Crew Commands", color=discord.Color.blue())
    
    embed.add_field(name="📝 Account", value="`/create-account` • `/link-account`", inline=False)
    embed.add_field(name="🔍 Search", value="`/find` • `/events` • `/crew`", inline=False)
    embed.add_field(name="📅 Events", value="`/join-event` • `/leave-event` • `/my-events`", inline=False)
    embed.add_field(name="📋 Lists", value="`/pick-list` - View items for event", inline=False)
    #embed.add_field(name="ℹ️ Info", value="React with ✋ to join events from messages", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# REACTION HANDLER
'''
@bot.event
async def on_reaction_add(reaction, user):
    """Handle emoji reactions"""
    if user.bot or str(reaction.emoji) != '✋':
        return
    
    message = reaction.message
    if message.embeds and message.author == bot.user:
        embed = message.embeds[0]
        footer = embed.footer
        if footer and "Event ID:" in footer.text:
            try:
                event_id = int(footer.text.split("Event ID: ")[1])
                response = requests.post(
                    f"{WEB_APP_URL}/discord/join-event",
                    json={
                        "discord_id": str(user.id),
                        "event_id": event_id,
                        "secret": DISCORD_BOT_SECRET
                    },
                    timeout=5
                )
                if response.status_code == 200:
                    try:
                        embed = discord.Embed(title="✅ Added!", description=f"You've joined event #{event_id}", color=discord.Color.green())
                        await user.send(embed=embed)
                    except:
                        pass
            except Exception as e:
                print(f"Reaction error: {e}")
'''

# RUN BOT
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not found!")
        exit(1)
    print(f"Starting bot... Web App: {WEB_APP_URL}")
    bot.run(DISCORD_BOT_TOKEN)

