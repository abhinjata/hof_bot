import os
import json
import logging
from collections import defaultdict
from dotenv import load_dotenv

import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

keep_alive()
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", 0))
HOF_CHANNEL_ID = int(os.getenv("HOF_CHANNEL_ID", 0))
LEADERBOARD_FILE = "leaderboard.json"
STAR_EMOJI = "⭐"
STAR_THRESHOLD = 5

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

leaderboard = defaultdict(int)
hof_message_ids = set()


def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, 'r') as f:
            data = json.load(f)
            return defaultdict(int, {int(k): v for k, v in data.items()})
    return defaultdict(int)


def save_leaderboard():
    with open(LEADERBOARD_FILE, 'w') as f:
        json.dump(leaderboard, f)


leaderboard = load_leaderboard()

async def is_already_in_hof(hof_channel, message_id: int):
    async for msg in hof_channel.history(limit=100):
        if msg.embeds:
            footer = msg.embeds[0].footer
            if footer and footer.text and footer.text.endswith(str(message_id)):
                return True
    return False

@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")
    try:
        await bot.tree.sync()
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        print("Slash commands synced globally and to guild!")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    hof_channel = bot.get_channel(HOF_CHANNEL_ID)
    if not hof_channel:
        print("HoF channel not found on startup.")
        return

    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                async for message in channel.history(limit=100):
                    star_reaction = next((r for r in message.reactions if str(r.emoji) == STAR_EMOJI), None)
                    if star_reaction and star_reaction.count >= STAR_THRESHOLD:
                        already_in_hof = await is_already_in_hof(hof_channel, message.id)
                        if already_in_hof:
                            continue

                        embed = discord.Embed(description=message.content, color=discord.Color.gold())
                        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
                        embed.set_footer(text=f"⭐ {STAR_THRESHOLD} | Message ID: {message.id}")

                        if message.embeds:
                            original_embed = message.embeds[0]
                            if original_embed.thumbnail:
                                embed.set_image(url=original_embed.thumbnail.url)
                            elif original_embed.url:
                                embed.set_image(url=original_embed.url)
                        elif message.attachments:
                            files = [await a.to_file() for a in message.attachments]
                            await hof_channel.send(embed=embed, files=files)
                        else:
                            await hof_channel.send(embed=embed)

                        leaderboard[message.author.id] += STAR_THRESHOLD
                        save_leaderboard()
                        hof_message_ids.add(message.id)

            except discord.Forbidden:
                print(f"Missing permissions to read channel: {channel.name}")
            except Exception as e:
                print(f"Error reading from channel {channel.name}: {e}")



@bot.tree.command(name="help", description="Know about the Hall of Fame bot")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "React to a message with ⭐! If it gets 5, it enters the Hall of Fame! Check out the #⭐・hall-of-fame channel and use /leaderboard to check the current session's leaderboard.",
        ephemeral=False
    )


@bot.tree.command(name="leaderboard", description="Show the Hall of Fame leaderboard")
async def leaderboard_cmd(interaction: discord.Interaction):
    if not leaderboard:
        await interaction.response.send_message("No stars given yet!", ephemeral=True)
        return

    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    embed = discord.Embed(
        title="🏆 Hall of Fame Leaderboard",
        description="Top users based on stars received.",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, stars) in enumerate(sorted_leaderboard[:10]):
        member = interaction.guild.get_member(user_id)
        if not member:
            continue
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        embed.add_field(
            name=f"{medal} {member.display_name}",
            value=f"{stars} ⭐",
            inline=False
        )

    embed.set_footer(text="look at all these cool people")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="addstars", description="Add stars to a user's count")
@app_commands.describe(user="User to add stars to", stars="Number of stars to add")
async def add_stars(interaction: discord.Interaction, user: discord.Member, stars: int):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )
        return
    leaderboard[user.id] += stars
    save_leaderboard()
    await interaction.response.send_message(f"Added {stars}⭐ to {user.display_name}.")


@bot.tree.command(name="removestars", description="Remove stars from a user's count")
@app_commands.describe(user="User to remove stars from", stars="Number of stars to remove")
async def remove_stars(interaction: discord.Interaction, user: discord.Member, stars: int):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )
        return
    leaderboard[user.id] = max(0, leaderboard[user.id] - stars)
    save_leaderboard()
    await interaction.response.send_message(f"Removed {stars}⭐ from {user.display_name}.")


@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.emoji.name) != STAR_EMOJI:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.Forbidden:
        print(f"Bot cannot access channel ID {payload.channel_id}. Possibly private.")
        return
    except Exception as e:
        print(f"Error fetching message: {e}")
        return

    star_reaction = next((r for r in message.reactions if str(r.emoji) == STAR_EMOJI), None)
    if star_reaction and star_reaction.count >= STAR_THRESHOLD:
        hof_channel = bot.get_channel(HOF_CHANNEL_ID)
        if not hof_channel:
            print("Hall of Fame channel not found!")
            return

        async for msg in hof_channel.history(limit=100):
            if msg.embeds:
                footer = msg.embeds[0].footer
                if footer and footer.text and footer.text.endswith(str(message.id)):
                    return

        embed = discord.Embed(description=message.content, color=discord.Color.gold())
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"⭐ {STAR_THRESHOLD} | Message ID: {message.id}")

        if message.embeds:
            original_embed = message.embeds[0]
            if original_embed.thumbnail:
                embed.set_image(url=original_embed.thumbnail.url)
            elif original_embed.url:
                embed.set_image(url=original_embed.url)
        elif message.attachments:
            files = [await a.to_file() for a in message.attachments]
            await hof_channel.send(embed=embed, files=files)
        else:
            await hof_channel.send(embed=embed)

        leaderboard[message.author.id] += STAR_THRESHOLD
        save_leaderboard()
        hof_message_ids.add(message.id)


bot.run(TOKEN)
