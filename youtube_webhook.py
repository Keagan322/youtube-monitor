from fastapi import FastAPI, Request, Query
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
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

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

def subscribe_channel(channel_id, retries=5, delay=10):
    for attempt in range(retries):
        try:
            logger.info(f"Subscribing to YouTube channel {channel_id}, attempt {attempt + 1}")
            response = requests.post(
                "https://pubsubhubbub.appspot.com/subscribe",
                data={
                    "hub.mode": "subscribe",
                    "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                    "hub.callback": WEBHOOK_URL
                }
            )
            logger.debug(f"Subscription response: status={response.status_code}, text={response.text}, headers={response.headers}")
            if response.status_code == 202:
                logger.info(f"Successfully subscribed to {channel_id}")
                # Force verification wait
                time.sleep(2)
                return True
            else:
                logger.error(f"Subscription failed for {channel_id}: {response.text}")
                if attempt < retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
        except Exception as e:
            logger.error(f"Subscription error for {channel_id}: {e}", exc_info=True)
            if attempt < retries - 1:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
    return False

@bot.command()
async def monitor(ctx, action: str, platform: str, channel_id: str):
    logger.debug(f"Received command: action={action}, platform={platform}, channel_id={channel_id}")
    if platform.lower() != "youtube":
        await ctx.send("Only YouTube supported for now!")
        return
    if action.lower() == "add":
        if channel_id not in YOUTUBE_CHANNELS:
            YOUTUBE_CHANNELS.append(channel_id)
            save_accounts(YOUTUBE_CHANNELS)
            if subscribe_channel(channel_id):
                await ctx.send(f"Added YouTube channel {channel_id}")
            else:
                await ctx.send(f"Failed to subscribe to {channel_id} after retries")
        else:
            await ctx.send(f"Channel {channel_id} already monitored")
    elif action.lower() == "remove":
        if channel_id in YOUTUBE_CHANNELS:
            YOUTUBE_CHANNELS.remove(channel_id)
            save_accounts(YOUTUBE_CHANNELS)
            try:
                logger.info(f"Unsubscribing from YouTube channel {channel_id}")
                response = requests.post(
                    "https://pubsubhubbub.appspot.com/subscribe",
                    data={
                        "hub.mode": "unsubscribe",
                        "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                        "hub.callback": WEBHOOK_URL
                    }
                )
                logger.debug(f"Unsubscribe response: status={response.status_code}, text={response.text}, headers={response.headers}")
                await ctx.send(f"Removed YouTube channel {channel_id}")
                logger.info(f"Unsubscribed from {channel_id}")
            except Exception as e:
                await ctx.send(f"Error unsubscribing from {channel_id}: {e}")
                logger.error(f"Unsubscribe error for {channel_id}: {e}", exc_info=True)
        else:
            await ctx.send(f"Channel {channel_id} not found")
            logger.debug(f"Channel {channel_id} not found in YOUTUBE_CHANNELS")

@app.get("/webhook")
async def webhook_verify(request: Request, hub_challenge: str = Query(..., alias="hub.challenge")):
    logger.debug(f"GET webhook request: headers={request.headers}, query_params={request.query_params}")
    return hub_challenge

@app.post("/webhook")
async def handle_webhook(request: Request):
    logger.debug(f"POST webhook request: headers={request.headers}")
    xml_data = await request.body()
    logger.debug(f"Webhook XML: {xml_data.decode('utf-8')}")
    try:
        root = ET.fromstring(xml_data)
        video_id = root.find(".//{http://www.youtube.com/xml/schemas/2015}videoId").text
        title = root.find(".//title").text
        logger.info(f"Parsed video: {title} (ID: {video_id})")
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            try:
                message = f"New YouTube video: {title}\nhttps://www.youtube.com/watch?v={video_id}"
                logger.debug(f"Attempting to send message to channel {CHANNEL_ID}: {message}")
                await channel.send(message)
                logger.info(f"Sent notification for video {video_id} to channel {CHANNEL_ID}")
            except Exception as e:
                logger.error(f"Failed to send Discord notification to channel {CHANNEL_ID}: {e}", exc_info=True)
        else:
            logger.error(f"Discord channel {CHANNEL_ID} not found or inaccessible")
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        logger.debug(f"Failed XML payload: {xml_data.decode('utf-8')}")
    return {"status": "ok"}

# Start Discord bot in background
@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting Discord bot")
    asyncio.create_task(bot.start(DISCORD_TOKEN))

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Discord bot")
    await bot.close()
