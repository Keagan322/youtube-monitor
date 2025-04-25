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
from collections import defaultdict
import psutil

# Configure logging with reduced verbosity
logging.basicConfig(
    level=logging.INFO,
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

# Message deduplication cache
sent_messages = defaultdict(list)

def load_accounts():
    try:
        with open("accounts.json", "r") as f:
            data = json.load(f)
            accounts = data.get("youtube", [])
            logger.info(f"Loaded {len(accounts)} YouTube channels")
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
        logger.info("Saved accounts.json")
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
        logger.error(f"Discord channel {CHANNEL_ID} not found")
    logger.info(f"FastAPI server ready at {WEBHOOK_URL}")
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    logger.info(f"Server status: CPU={cpu_percent}%, Memory={memory.percent}%")

def subscribe_channel(channel_id, retries=3, delay=5):
    logger.info(f"Subscribing to YouTube channel {channel_id}")
    for attempt in range(retries):
        try:
            response = requests.post(
                "https://pubsubhubbub.appspot.com/subscribe",
                data={
                    "hub.mode": "subscribe",
                    "hub.topic": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                    "hub.callback": WEBHOOK_URL,
                    "hub.verify": "async"
                },
                timeout=15
            )
            if response.status_code == 202:
                logger.info(f"Subscription accepted for {channel_id}, lease_seconds={response.headers.get('hub-lease-seconds', 'unknown')}")
                time.sleep(2)
                return True
            else:
                logger.error(f"Subscription failed for {channel_id}: status={response.status_code}, response={response.text}")
                if attempt < retries - 1:
                    time.sleep(delay)
        except requests.RequestException as e:
            logger.error(f"Network error for {channel_id}: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    logger.error(f"Failed to subscribe to {channel_id} after {retries} attempts")
    return False

@bot.command()
async def ping(ctx):
    nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    logger.info(f"Ping command received with nonce {nonce}")
    message_key = (str(ctx.channel.id), "ping", time.time() // 10)
    if any(key == message_key for key, _ in sent_messages[str(ctx.channel.id)]):
        logger.debug(f"Skipping duplicate ping with nonce {nonce}")
        return
    sent_messages[str(ctx.channel.id)].append((message_key, nonce))
    try:
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        latency = bot.latency * 1000
        await ctx.send(
            f"Pong! Bot is online.\nServer: CPU={cpu_percent}%, Memory={memory.percent}% used\nLatency: {latency:.2f}ms",
            nonce=nonce
        )
        logger.info(f"Ping completed with nonce {nonce}")
    except Exception as e:
        logger.error(f"Ping failed with nonce {nonce}: {e}")
        await ctx.send(f"Ping failed: {e}", nonce=nonce)

@bot.command()
async def test(ctx):
    nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    logger.info(f"Test command received with nonce {nonce}")
    message_key = (str(ctx.channel.id), "test", time.time() // 10)
    if any(key == message_key for key, _ in sent_messages[str(ctx.channel.id)]):
        logger.debug(f"Skipping duplicate test with nonce {nonce}")
        return
    sent_messages[str(ctx.channel.id)].append((message_key, nonce))
    try:
        await ctx.send("Bot is online and working! Checking channel access...", nonce=nonce)
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            channel_nonce = nonce + "-channel"
            channel_key = (str(channel.id), "test-channel", time.time() // 10)
            if any(key == channel_key for key, _ in sent_messages[str(channel.id)]):
                logger.debug(f"Skipping duplicate channel test with nonce {channel_nonce}")
                return
            sent_messages[str(channel.id)].append((channel_key, channel_nonce))
            await channel.send(f"Test message from bot to confirm access to channel {CHANNEL_ID}", nonce=channel_nonce)
            success_nonce = nonce + "-success"
            success_key = (str(ctx.channel.id), "test-success", time.time() // 10)
            if any(key == success_key for key, _ in sent_messages[str(ctx.channel.id)]):
                logger.debug(f"Skipping duplicate success test with nonce {success_nonce}")
                return
            sent_messages[str(ctx.channel.id)].append((success_key, success_nonce))
            await ctx.send(f"Successfully sent test message to configured channel {CHANNEL_ID}", nonce=success_nonce)
        else:
            await ctx.send(f"Error: Bot cannot access channel {CHANNEL_ID}", nonce=nonce)
        logger.info(f"Test completed with nonce {nonce}")
    except Exception as e:
        logger.error(f"Test failed with nonce {nonce}: {e}")
        await ctx.send(f"Test failed: {e}", nonce=nonce)

@bot.command()
async def status(ctx):
    nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    logger.info(f"Status command received with nonce {nonce}")
    message_key = (str(ctx.channel.id), "status", time.time() // 10)
    if any(key == message_key for key, _ in sent_messages[str(ctx.channel.id)]):
        logger.debug(f"Skipping duplicate status with nonce {nonce}")
        return
    sent_messages[str(ctx.channel.id)].append((message_key, nonce))
    if not YOUTUBE_CHANNELS:
        await ctx.send("No YouTube channels are currently monitored.", nonce=nonce)
        return
    message = "Monitored YouTube channels:\n"
    for channel_id in YOUTUBE_CHANNELS:
        message += f"- {channel_id}\n"
        logger.info(f"Reattempting subscription for {channel_id}")
        if subscribe_channel(channel_id):
            message += f"  Subscription verified for {channel_id}\n"
        else:
            message += f"  Failed to verify subscription for {channel_id}\n"
    await ctx.send(message, nonce=nonce)

@bot.command()
async def testwebhook(ctx):
    nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    logger.info(f"Testwebhook command received with nonce {nonce}")
    message_key = (str(ctx.channel.id), "testwebhook", time.time() // 10)
    if any(key == message_key for key, _ in sent_messages[str(ctx.channel.id)]):
        logger.debug(f"Skipping duplicate testwebhook with nonce {nonce}")
        return
    sent_messages[str(ctx.channel.id)].append((message_key, nonce))
    retries = 3
    delay = 5
    last_error = None
    for attempt in range(retries):
        try:
            xml_payload = '''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
    <entry>
        <yt:videoId>test123</yt:videoId>
        <title>Test Video</title>
    </entry>
</feed>'''
            logger.info(f"Attempting test webhook POST, attempt {attempt + 1}")
            response = requests.post(
                WEBHOOK_URL,
                data=xml_payload,
                headers={"Content-Type": "application/xml"},
                timeout=15
            )
            logger.info(f"Test webhook response: status={response.status_code}, text={response.text}")
            if response.status_code == 200:
                await ctx.send("Test webhook sent successfully. Check Discord channel for notification.", nonce=nonce)
                return
            else:
                await ctx.send(f"Test webhook failed: status={response.status_code}, response={response.text}", nonce=nonce)
                if attempt < retries - 1:
                    time.sleep(delay)
        except requests.RequestException as e:
            last_error = e
            logger.error(f"Testwebhook failed with nonce {nonce}: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    await ctx.send(f"Testwebhook failed after {retries} attempts: {last_error or 'Unknown error'}", nonce=nonce)

@bot.command()
async def monitor(ctx, action: str, platform: str, channel_id: str):
    nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    logger.info(f"Monitor command: action={action}, platform={platform}, channel_id={channel_id}, nonce={nonce}")
    message_key = (str(ctx.channel.id), f"monitor-{action}-{platform}-{channel_id}", time.time() // 10)
    if any(key == message_key for key, _ in sent_messages[str(ctx.channel.id)]):
        logger.debug(f"Skipping duplicate monitor with nonce {nonce}")
        return
    sent_messages[str(ctx.channel.id)].append((message_key, nonce))
    if platform.lower() != "youtube":
        await ctx.send("Only YouTube is supported!", nonce=nonce)
        logger.warning(f"Unsupported platform {platform}")
        return
    if action.lower() == "add":
        if channel_id in YOUTUBE_CHANNELS:
            await ctx.send(f"Channel {channel_id} is already monitored", nonce=nonce)
            logger.info(f"Channel {channel_id} already in YOUTUBE_CHANNELS")
            return
        YOUTUBE_CHANNELS.append(channel_id)
        save_accounts(YOUTUBE_CHANNELS)
        if subscribe_channel(channel_id):
            await ctx.send(f"Successfully added YouTube channel {channel_id}", nonce=nonce)
        else:
            await ctx.send(f"Failed to subscribe to {channel_id} after retries. Check logs.", nonce=nonce)
    elif action.lower() == "remove":
        if channel_id not in YOUTUBE_CHANNELS:
            await ctx.send(f"Channel {channel_id} is not monitored", nonce=nonce)
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
                timeout=15
            )
            logger.info(f"Unsubscribe response: status={response.status_code}, text={response.text}")
            if response.status_code == 202:
                await ctx.send(f"Successfully removed YouTube channel {channel_id}", nonce=nonce)
            else:
                await ctx.send(f"Unsubscribe request failed for {channel_id}. Check logs.", nonce=nonce)
            logger.info(f"Unsubscribe request sent for {channel_id}")
        except Exception as e:
            await ctx.send(f"Error unsubscribing from {channel_id}: {e}", nonce=nonce)
            logger.error(f"Unsubscribe error for {channel_id}: {e}")
    else:
        await ctx.send("Invalid action. Use 'add' or 'remove'.", nonce=nonce)
        logger.warning(f"Invalid action {action}")

@app.get("/webhook")
async def webhook_verify(request: Request, hub_challenge: str = Query(..., alias="hub.challenge")):
    logger.info(f"Received webhook verification: hub.challenge={hub_challenge}")
    return hub_challenge

@app.post("/webhook")
async def handle_webhook(request: Request):
    logger.info("Received webhook POST request")
    try:
        xml_data = await request.body()
        xml_str = xml_data.decode('utf-8')
        logger.info(f"Webhook XML payload: {xml_str}")
        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015'
        }
        root = ET.fromstring(xml_str)
        video_id_elem = root.find(".//yt:videoId", namespaces)
        title_elem = root.find(".//atom:title", namespaces)
        if video_id_elem is None or title_elem is None:
            logger.error("Missing videoId or title in webhook XML")
            return {"status": "error", "message": "Invalid webhook data"}
        video_id = video_id_elem.text
        title = title_elem.text
        logger.info(f"Parsed new video: title={title}, video_id={video_id}")
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            message = f"New YouTube video: {title}\nhttps://www.youtube.com/watch?v={video_id}"
            logger.info(f"Sending notification to channel {CHANNEL_ID}: {message}")
            nonce = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
            message_key = (str(channel.id), f"notification-{video_id}", time.time() // 10)
            if any(key == message_key for key, _ in sent_messages[str(channel.id)]):
                logger.debug(f"Skipping duplicate notification with nonce {nonce}")
                return {"status": "ok"}
            sent_messages[str(channel.id)].append((message_key, nonce))
            await channel.send(message, nonce=nonce)
            logger.info(f"Sent notification for video {video_id} to channel {CHANNEL_ID}")
        else:
            logger.error(f"Cannot send notification: Discord channel {CHANNEL_ID} not found")
        return {"status": "ok"}
    except ET.ParseError as e:
        logger.error(f"Failed to parse webhook XML: {e}")
        logger.info(f"Invalid XML payload: {xml_str}")
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
