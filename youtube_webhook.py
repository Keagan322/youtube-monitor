from fastapi import FastAPI, Request
import discord
from discord.ext import commands
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv
import json
import requests
import asyncio
from functools import partial
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# Enable necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

def load_accounts():
    try:
        with open("accounts.json", "r") as f:
            return json.load(f).get("youtube", [])
    except FileNotFoundError:
        logger.warning("accounts.json not found, starting with empty list")
        return []

def save_accounts(accounts):
    with open("accounts.json", "w") as f:
        json.dump({"youtube": accounts}, f)
        logger.info("Saved accounts.json")

YOUTUBE_CHANNELS = load_accounts()

@bot.event
async def on_ready():
    logger.info(f"Webhook bot logged in as {bot.user}")

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
                logger.info(f"Subscribing to YouTube channel {channel_id}")
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
                    logger.info(f"Successfully subscribed to {channel_id}")
                else:
                    await ctx.send(f"Error subscribing to {channel_id}: {response.text}")
                    logger.error(f"Subscription failed for {channel_id}: {response.text}")
            except Exception as e:
                await ctx.send(f"Error subscribing to {channel_id}: {e}")
                logger.error(f"Subscription error for {channel_id}: {e}")
        else:
            await ctx.send(f"Channel {channel_id} already monitored")
    elif action.lower() == "remove":
        if channel_id in YOUTUBE_CHANNELS:
            YOUTUBE_CHANNELS.remove(channel_id)
            save_accounts(YOUTUBE_CHANNELS)
            try:
                logger.info(f"Unsubscribing from YouTube channel {channel_id}")
                requests.post(
                    "https://pubsubhubbub.appspot.com/subscribe",
                    data={
                        "hub.mode": "unsubscribe",
                        "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                        "hub.callback": os.getenv("WEBHOOK_URL")
                    }
                )
                await ctx.send(f"Removed YouTube channel {channel_id}")
                logger.info(f"Unsubscribed from {channel_id}")
            except Exception as e:
                await ctx.send(f"Error unsubscribing from {channel_id}: {e}")
                logger.error(f"Unsubscribe error for {channel_id}: {e}")
        else:
            await ctx.send(f"Channel {channel_id} not found")

@app.post("/webhook")
async def handle_webhook(request: Request):
    logger.info("Received webhook request")
    xml_data = await request.body()
    logger.debug(f"Webhook XML: {xml_data}")
    try:
        root = ET.fromstring(xml_data)
        video_id = root.find(".//{http://www.youtube.com/xml/schemas/2015}videoId").text
        title = root.find(".//title").text
        logger.info(f"Parsed video: {title} (ID: {video_id})")
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send(f"New YouTube video: {title}\nhttps://www.youtube.com/watch?v={video_id}")
            logger.info(f"Sent notification for video {video_id}")
        else:
            logger.error(f"Channel {CHANNEL_ID} not found")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return {"status": "ok"}

# Start Discord bot in background
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Discord bot")
    asyncio.create_task(bot.start(DISCORD_TOKEN))

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Discord bot")
    await bot.close()
