from fastapi import FastAPI, Request, Query
import discord
from discord.ext import commands
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv
import json
import requests
import asyncio
import logging
import time
import secrets
import string

# Configure logging with detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Validate environment variables
if not DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN is not set in .env")
if not CHANNEL_ID:
    logger.error("CHANNEL_ID is not set in .env")
if not WEBHOOK_URL:
    logger.error("WEBHOOK_URL is not set in .env")

# Enable necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

def load_accounts():
    try:
        with open("accounts.json", "r") as f:
            data = json.load(f)
            accounts = data.get("youtube", [])
            logger.info(f"Loaded {len(accounts)} YouTube channels from accounts.json")
            return accounts
    except FileNotFoundError:
        logger.warning("accounts.json not found, starting with empty list")
        return []
    except Exception as e:
        logger.error(f"Error loading accounts.json: {e}")
        return []

def save_accounts(accounts):
    try:
        with open("accounts.json", "w") as f:
            json.dump({"youtube": accounts}, f)
        logger.info("Successfully saved accounts.json")
    except Exception as e:
        logger.error(f"Error saving accounts.json: {e}")

YOUTUBE_CHANNELS = load_accounts()

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        logger.info(f"Found Discord channel {CHANNEL_ID} ({channel.name})")
    else:
        logger.error(f"Discord channel {CHANNEL_ID} not found or bot lacks access")
    logger.info(f"FastAPI server ready to receive webhooks at {WEBHOOK_URL}")

def subscribe_channel(channel_id, retries=3, delay=5):
    logger.info(f"Attempting to subscribe to YouTube channel {channel_id}")
    for attempt in range(retries):
        try:
            logger.debug(f"Subscription attempt {attempt + 1} for {channel_id}")
            response = requests.post(
                "https://pubsubhubbub.appspot.com/subscribe",
                data={
                    "hub.mode": "subscribe",
                    "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                    "hub.callback": WEBHOOK_URL,
                    "hub.verify": "async"
                },
                timeout=10
            )
            logger.debug(f"Subscription response: status={response.status_code}, text={response.text}, headers={response.headers}")
            if response.status_code == 202:
                logger.info(f"Subscription request accepted for {channel_id}")
                time.sleep(2)
                return True
            else:
                logger.error(f"Subscription failed for {channel_id}: status={response.status_code}, response={response.text}")
                if attempt < retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
        except requests.RequestException as e:
            logger.error(f"Network error during subscription for {channel_id}: {e}")
            if attempt < retries - 1:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
    logger.error(f"Failed to subscribe to {channel_id} after {retries} attempts")
    return False

@bot.command()
async def test(ctx):
    """Test command to verify bot connectivity and permissions"""
    nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    logger.info(f"Test command received in channel {ctx.channel.id} with nonce {nonce}")
    try:
        await ctx.send("Bot is online and working! Checking channel access...", nonce=nonce)
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send(f"Test message from bot to confirm access to channel {CHANNEL_ID}", nonce=nonce)
            await ctx.send(f"Successfully sent test message to configured channel {CHANNEL_ID}", nonce=nonce)
        else:
            await ctx.send(f"Error: Bot cannot access channel {CHANNEL_ID}", nonce=nonce)
        logger.info(f"Test command completed successfully with nonce {nonce}")
    except Exception as e:
        logger.error(f"Test command failed with nonce {nonce}: {e}")
        await ctx.send(f"Test failed: {e}", nonce=nonce)

@bot.command()
async def status(ctx):
    """Check monitored channels and reattempt subscriptions"""
    logger.info("Status command received")
    if not YOUTUBE_CHANNELS:
        await ctx.send("No YouTube channels are currently monitored.")
        return
    message = "Monitored YouTube channels:\n"
    for channel_id in YOUTUBE_CHANNELS:
        message += f"- {channel_id}\n"
        logger.info(f"Reattempting subscription for {channel_id}")
        if subscribe_channel(channel_id):
            message += f"  Subscription verified for {channel_id}\n"
        else:
            message += f"  Failed to verify subscription for {channel_id}\n"
    await ctx.send(message)

@bot.command()
async def monitor(ctx, action: str, platform: str, channel_id: str):
    logger.info(f"Monitor command: action={action}, platform={platform}, channel_id={channel_id}")
    if platform.lower() != "youtube":
        await ctx.send("Only YouTube is supported!")
        logger.warning(f"Unsupported platform {platform}")
        return
    if action.lower() == "add":
        if channel_id in YOUTUBE_CHANNELS:
            await ctx.send(f"Channel {channel_id} is already monitored")
            logger.info(f"Channel {channel_id} already in YOUTUBE_CHANNELS")
            return
        YOUTUBE_CHANNELS.append(channel_id)
        save_accounts(YOUTUBE_CHANNELS)
        if subscribe_channel(channel_id):
            await ctx.send(f"Successfully added YouTube channel {channel_id}")
        else:
            await ctx.send(f"Failed to subscribe to {channel_id} after retries. Check logs.")
    elif action.lower() == "remove":
        if channel_id not in YOUTUBE_CHANNELS:
            await ctx.send(f"Channel {channel_id} is not monitored")
            logger.info(f"Channel {channel_id} not in YOUTUBE_CHANNELS")
            return
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
                },
                timeout=10
            )
            logger.debug(f"Unsubscribe response: status={response.status_code}, text={response.text}")
            if response.status_code == 202:
                await ctx.send(f"Successfully removed YouTube channel {channel_id}")
            else:
                await ctx.send(f"Unsubscribe request failed for {channel_id}. Check logs.")
            logger.info(f"Unsubscribe request sent for {channel_id}")
        except Exception as e:
            await ctx.send(f"Error unsubscribing from {channel_id}: {e}")
            logger.error(f"Unsubscribe error for {channel_id}: {e}")
    else:
        await ctx.send("Invalid action. Use 'add' or 'remove'.")
        logger.warning(f"Invalid action {action}")

@app.get("/webhook")
async def webhook_verify(request: Request, hub_challenge: str = Query(..., alias="hub.challenge")):
    logger.info(f"Received webhook verification: hub.challenge={hub_challenge}")
    logger.debug(f"Verification request headers={request.headers}, query_params={request.query_params}")
    return hub_challenge

@app.post("/webhook")
async def handle_webhook(request: Request):
    logger.info("Received webhook POST request")
    try:
        xml_data = await request.body()
        xml_str = xml_data.decode('utf-8')
        logger.debug(f"Webhook XML payload: {xml_str}")
        root = ET.fromstring(xml_str)
        video_id = root.find(".//{http://www.youtube.com/xml/schemas/2015}videoId")
        title = root.find(".//title")
        if video_id is None or title is None:
            logger.error("Missing videoId or title in webhook XML")
            return {"status": "error", "message": "Invalid webhook data"}
        video_id = video_id.text
        title = title.text
        logger.info(f"Parsed new video: title={title}, video_id={video_id}")
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            message = f"New YouTube video: {title}\nhttps://www.youtube.com/watch?v={video_id}"
            logger.info(f"Sending notification to channel {CHANNEL_ID}: {message}")
            await channel.send(message)
            logger.info(f"Successfully sent notification for video {video_id} to channel {CHANNEL_ID}")
        else:
            logger.error(f"Cannot send notification: Discord channel {CHANNEL_ID} not found")
        return {"status": "ok"}
    except ET.ParseError as e:
        logger.error(f"Failed to parse webhook XML: {e}")
        logger.debug(f"Invalid XML payload: {xml_str}")
        return {"status": "error", "message": "Invalid XML"}
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def startup_event():
    logger.info("Starting FastAPI server and Discord bot")
    asyncio.create_task(bot.start(DISCORD_TOKEN))

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Discord bot")
    await bot.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
