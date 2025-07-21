# routes/webhook.py

from flask import Blueprint, request
from config import VERIFY_TOKEN
from services.chat_service import handle_message
from services.fb_messenger import send_fb_message

webhook_bp = Blueprint('webhook', __name__)

@webhook_bp.route('/', methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Error de verificación", 403

@webhook_bp.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    if data.get('object') == 'page':
        for entry in data.get('entry', []):
            for messaging in entry.get('messaging', []):
                if messaging.get('message') and 'text' in messaging['message']:
                    sender_id = messaging['sender']['id']
                    user_msg = messaging['message']['text'].lower()

                    bot_reply = handle_message(sender_id, user_msg, channel='meta')
                    send_fb_message(sender_id, bot_reply)
    return "OK", 200
