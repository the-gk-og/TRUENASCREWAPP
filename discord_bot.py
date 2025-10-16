import discord
from discord.ext import commands
import os
import requests
from dotenv import load_dotenv
import json

load_dotenv()

# Configuration
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
WEB_APP_URL = os.environ.get('WEB_APP_URL', 'http://localhost:5000')
DISCORD_BOT_SECRET = os.environ.get('DISCORD_BOT_SECRET', 'change-this-secret')

# Create bot
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

# Slash Commands

@bot.tree.command(name="link-account", description="Link your Discord account to Production Crew")
async def link_account(interaction: discord.Interaction):
    """Link Discord account to web app automatically"""
    
    user = interaction.user
    discord_id = str(user.id)
    discord_username = user.name
    
    try:
        # Try to link the account via web app API
        response = requests.post(
            f"{WEB_APP_URL}/discord/auto-link",
            json={
                "discord_id": discord_id,
                "discord_username": discord_username,
                "secret": DISCORD_BOT_SECRET
            },
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('linked_to'):
                # Account was already linked or newly linked
                embed = discord.Embed(
                    title="✅ Account Linked!",
                    description=f"Your Discord account has been linked to: **{result['linked_to']}**",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="What's Next?",
                    value="You can now:\n• React with ✋ to join events\n• Use `/my-events` to see your assignments\n• Get notifications about events you're assigned to",
                    inline=False
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                # New account created (rare case)
                embed = discord.Embed(
                    title="✅ Discord Linked!",
                    description="Your Discord account is now linked to the Production Crew system.",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            error = response.json().get('error', 'Unknown error')
            embed = discord.Embed(
                title="⚠️ Linking Issue",
                description=error,
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    except requests.exceptions.ConnectionError:
        embed = discord.Embed(
            title="❌ Connection Error",
            description=f"Cannot reach the Production Crew web app at {WEB_APP_URL}\n\nMake sure the web app is running!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Error",
            description=f"Failed to link account: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="join-event", description="Join an event by ID")
async def join_event(interaction: discord.Interaction, event_id: int):
    """Join an event via command"""
    
    user = interaction.user
    discord_id = str(user.id)
    
    try:
        response = requests.post(
            f"{WEB_APP_URL}/discord/join-event",
            json={
                "discord_id": discord_id,
                "event_id": event_id,
                "secret": DISCORD_BOT_SECRET
            },
            timeout=5
        )
        
        if response.status_code == 200:
            embed = discord.Embed(
                title="✅ Joined Event!",
                description=f"You've been added to event #{event_id}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            error = response.json().get('error', 'Unknown error')
            embed = discord.Embed(
                title="❌ Error",
                description=error,
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Connection Error",
            description=f"Could not connect to web app: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="my-events", description="See all events you're assigned to")
async def my_events(interaction: discord.Interaction):
    """Show user's assigned events"""
    
    user = interaction.user
    discord_id = str(user.id)
    
    try:
        response = requests.get(
            f"{WEB_APP_URL}/discord/user-events/{discord_id}",
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            events = data.get('events', [])
            
            if not events:
                embed = discord.Embed(
                    title="📅 Your Events",
                    description="You're not assigned to any events yet.",
                    color=discord.Color.blue()
                )
            else:
                embed = discord.Embed(
                    title="📅 Your Events",
                    description=f"You're assigned to {len(events)} event(s)",
                    color=discord.Color.blue()
                )
                
                for event in events:
                    embed.add_field(
                        name=f"🎭 {event['title']}",
                        value=f"📅 {event['date']}\n📍 {event['location']}\n👤 {event['role']}",
                        inline=False
                    )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="❌ Error",
                description="Could not fetch your events",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Connection Error",
            description=f"Could not connect to web app: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Show available commands")
async def help_command(interaction: discord.Interaction):
    """Show help message"""
    
    embed = discord.Embed(
        title="🎭 Production Crew Commands",
        description="Available slash commands:",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="/link-account",
        value="🔗 Link your Discord account automatically (one-time setup)",
        inline=False
    )
    
    embed.add_field(
        name="/join-event [event_id]",
        value="➕ Join an event by ID",
        inline=False
    )
    
    embed.add_field(
        name="/my-events",
        value="📅 See all events you're assigned to",
        inline=False
    )
    
    embed.add_field(
        name="React to Join",
        value="✋ React with ✋ to event messages to join them instantly",
        inline=False
    )
    
    embed.add_field(
        name="/help",
        value="ℹ️ Show this message",
        inline=False
    )
    
    embed.set_footer(text="Start with /link-account to set up your account!")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="status", description="Check if you're linked and see connection status")
async def status(interaction: discord.Interaction):
    """Check link status"""
    
    user = interaction.user
    discord_id = str(user.id)
    
    try:
        response = requests.get(
            f"{WEB_APP_URL}/discord/check-link/{discord_id}",
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('linked'):
                embed = discord.Embed(
                    title="✅ Account Linked",
                    description=f"Your Discord is linked to: **{data['username']}**",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="Assigned Events",
                    value=f"{data.get('event_count', 0)} events",
                    inline=False
                )
            else:
                embed = discord.Embed(
                    title="❌ Not Linked Yet",
                    description="Use `/link-account` to link your Discord account",
                    color=discord.Color.red()
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="ℹ️ Not Linked",
                description="Use `/link-account` to link your Discord account",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Error",
            description=f"Could not check status: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Run the bot
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not found!")
        print("Set the environment variable before running this bot.")
        exit(1)
    
    print("Starting Discord bot...")
    print(f"Web App URL: {WEB_APP_URL}")
    print(f"Bot Token: {'*' * 20}")
    print("Commands: /link-account, /join-event, /my-events, /status, /help")
    print("-" * 50)
    
    bot.run(DISCORD_BOT_TOKEN)