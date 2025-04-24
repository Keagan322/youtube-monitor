from fastapi import FastAPI, Request
import discord
from discord.ext import commands
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv
import json
import requests

app = FastAPI()
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# Enable necessary intents
intents = discord.Intents.default()
intents.message_content = True  # For reading commands
intents.guilds = True  # For accessing channels
bot = commands.Bot(command_prefix="!", intents=intents)

def load_accounts():
    try:
        with open("accounts.json", "r") as f:
            return json.load(f).get("youtube", [])
    except FileNotFoundError:
        return []

def save_accounts(accounts):
    with open("accounts.json", "w") as f:
        json.dump({"youtube": accounts}, f)

YOUTUBE_CHANNELS = load_accounts()

@bot.event
async def on_ready():
    print(f"Webhook bot logged in as {bot.user}")

@bot.command()
async def monitor(ctx, action: str, platform: str, channel_id: str):
    if platform.lower() != "youtube":
        await ctx.send("Only YouTube supported for now!")
        return
    if action.lower() == "add":
        if channel_id not in YOUTUBE_CHANNELS:
            YOUTUBE_CHANNELS.append(channel_id)
            save_accounts(YOUTUBE_CHANNELS)
            try:
                response = requests.post(
                    "https://pubsubhubbub.appspot.com/subscribe",
                    data={
                        "hub.mode": "subscribe",
                        "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                        "hub.callback": os.getenv("WEBHOOK_URL")
                    }
                )
                if response.status_code == 202:
                    await ctx.send(f"Added YouTube channel {channel_id}")
                else:
                    await ctx.send(f"Error subscribing to {channel_id}: {response.text}")
            except Exception as e:
                await ctx.send(f"Error subscribing to {channel_id}: {e}")
        else:
            await ctx.send(f"Channel {channel_id} already monitored")
    elif action.lower() == "remove":
        if channel_id in YOUTUBE_CHANNELS:
            YOUTUBE_CHANNELS.remove(channel_id)
            save_accounts(YOUTUBE_CHANNELS)
            requests.post(
                "https://pubsubhubbub.appspot.com/subscribe",
                data={
                    "hub.mode": "unsubscribe",
                    "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                    "hub.callback": os.getenv("WEBHOOK_URL")
                }
            )
            await ctx.send(f"Removed YouTube channel {channel_id}")
        else:
            await ctx.send(f"Channel {channel_id} not found")

@app.post("/webhook")
async def handle_webhook(request: Request):
    xml_data = await request.body()
    try:
        root = ET.fromstring(xml_data)
        video_id = root.find(".//{http://www.youtube.com/xml/schemas/2015}videoId").text
        title = root.find(".//title").text
        channel = bot.get_channel(CHANNEL_ID)
        await channel.send(f"New YouTube video: {title}\nhttps://www.youtube.com/watch?v={video_id}")
    except Exception as e:
        print(f"Webhook error: {e}")
    return {"status": "ok"}

bot.run(DISCORD_TOKEN)
