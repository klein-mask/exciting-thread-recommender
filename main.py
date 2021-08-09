from fastapi import FastAPI
from slackers.server import router
from slackers.hooks import events
import slackweb
import requests
import config
from functools import reduce
import datetime
import os
import random
from logging import getLogger

SLACK_WORKSPACE_DOMAIN = os.environ['SLACK_WORKSPACE_DOMAIN']
SLACK_BOT_AUTH_TOKEN = os.environ['SLACK_BOT_AUTH_TOKEN']
SLACK_INCOMMING_WEBHOOK_URL = os.environ['SLACK_INCOMMING_WEBHOOK_URL']
SLACK_NOTIFY_CHANNEL_ID = os.environ['SLACK_NOTIFY_CHANNEL_ID']
SLACK_BOT_ID = os.environ['SLACK_BOT_ID']

app = FastAPI()
app.include_router(router)

logger = getLogger(__name__)

@events.on("reaction_added")
def handle_mention(payload):
    event = payload['event']
    if event['item']['channel'] == SLACK_NOTIFY_CHANNEL_ID:
        return

    try:
        slack_notify(event)
    except Exception as e:
        logger.error(e)

@events.on("message")
def handle_message(payload):
    event = payload['event']
    if (event['channel'] == SLACK_NOTIFY_CHANNEL_ID) or not ('thread_ts' in event):
        return

    try:
        slack_notify(event)
    except Exception as e:
        logger.error(e)

def slack_notify(event):
    thread = get_thread(event)

    if is_excite(event, thread['data']):
        notify_thread_url = get_thread_url(event, thread['data'])
        if not is_notifyed_today(notify_thread_url):
            # ユーザー情報
            user_info = requests.get(config.slack_api_url['USERS_INFO'],
                               headers={'Authorization': f'Bearer {SLACK_BOT_AUTH_TOKEN}'},
                               params={'user': event['user']}).json()

            # チャンネル情報
            channel_info = requests.get(config.slack_api_url['CONVERSATIONS_INFO'],
                               headers={'Authorization': f'Bearer {SLACK_BOT_AUTH_TOKEN}'},
                               params={'channel': thread['channel']}).json()

            attachments = [
                {
                    "fallback": "This bot is exciting thread teacher.",
                    "color": "#a52a2a",
                    "author_name": user_info['user']['profile']['first_name'],
                    "author_link": f"https://{SLACK_WORKSPACE_DOMAIN}/team/{user_info['user']['id']}",
                    "author_icon": user_info['user']['profile']['image_72'],
                    "title": f"#{channel_info['channel']['name']}で以下のスレッドが盛り上がってます !!!",
                    "text": f"{thread['data']['messages'][0]['text']}\n\n<{notify_thread_url}|:point_right: スレッドを見に行く！！>",
                    "image_url": random.choice(config.attachment_images),
                    "footer": config.attachment_footer_text,
                    "footer_icon": config.attachment_footer_image,
                    "ts": thread['data']['messages'][0]['ts']
                }
            ]
            slackweb.Slack(url=SLACK_INCOMMING_WEBHOOK_URL).notify(attachments=attachments)

def get_thread(event):
    channel = ''
    ts = ''
    if event['type'] == config.event_type['REACTION_ADDED']:
        channel = event['item']['channel']
        ts = event['item']['ts']
    elif event['type'] == config.event_type['MESSAGE']:
        channel = event['channel']
        ts = event['thread_ts']

    return {
        'channel': channel,
        'ts': ts,
        'data': requests.get(config.slack_api_url['CONVERSATIONS_REPLIES'],
                        headers={'Authorization': f'Bearer {SLACK_BOT_AUTH_TOKEN}'},
                        params={'channel': channel, 'ts': ts}).json()
    }

def get_thread_url(event, thread):
    BASE_URL = f'https://{SLACK_WORKSPACE_DOMAIN}/archives'

    if event['type'] == config.event_type['REACTION_ADDED']:
        channel = event['item']['channel']
        ts = f"p{event['item']['ts'].replace('.', '')}"
        if 'thread_ts' in thread['messages'][0]:
            thread_ts = thread['messages'][0]['thread_ts']
            return BASE_URL + '/' + channel + '/' + ts + f'?thread_ts={thread_ts}&cid={channel}'
        else:
            return BASE_URL + '/' + channel + '/' + ts
    elif event['type'] == config.event_type['MESSAGE']:
        channel = event['channel']
        ts = f"p{event['thread_ts'].replace('.', '')}"
        return BASE_URL + '/' + channel + '/' + ts

def is_excite(event, thread):
    if event['type'] == config.event_type['REACTION_ADDED']:
        reactions = thread['messages'][0]['reactions']

        stamp_type_count  = len([ x['name'] for x in reactions ])
        stamp_total_count = reduce(lambda a, b: a + b, [ x['count'] for x in reactions ])

        return (stamp_type_count >= config.threshold['stamp_type_count'] or
            stamp_total_count >= config.threshold['stamp_total_count'])
    elif event['type'] == config.event_type['MESSAGE']:
        message = thread['messages'][0]
        return (message['reply_count'] >= config.threshold['reply_count'] and
                message['reply_users_count'] >= config.threshold['reply_users_count'])

def is_notifyed_today(notify_thread_url):
    now = datetime.datetime.now()
    latest = str(now.timestamp())
    oldest = str((now - datetime.timedelta(days=1)).timestamp())

    payload = {
        'channel': SLACK_NOTIFY_CHANNEL_ID,
        'latest': latest,
        'oldest': oldest
    }

    res = requests.get(config.slack_api_url['CONVERSATIONS_HISTORY'],
                       headers={'Authorization': f'Bearer {SLACK_BOT_AUTH_TOKEN}'},
                       params=payload).json()

    bot_notified_urls = [x['attachments'][0]['title_link'] for x in res['messages'] if
                          'attachments' in x and
                         'title_link' in x['attachments'][0] and
                          'bot_id' in x and
                          x['bot_id'] == SLACK_BOT_ID]

    return notify_thread_url in bot_notified_urls
