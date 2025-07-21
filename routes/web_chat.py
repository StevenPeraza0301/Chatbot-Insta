# routes/web_chat.py

from flask import Blueprint, request, jsonify
from services.chat_service import handle_message

web_chat_bp = Blueprint('web_chat', __name__)

@web_chat_bp.route('/', methods=['POST'])
def web_chat():
    data = request.get_json()
    user_msg = data.get('message', '').lower()
    user_id = data.get('user_id', 'web-user')  # Puedes hacer esto dinámico si usas múltiples usuarios

    bot_reply = handle_message(user_id, user_msg, channel='web')
    return jsonify({"reply": bot_reply})
