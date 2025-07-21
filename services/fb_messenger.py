# services/fb_messenger.py

import requests
from config import PAGE_ACCESS_TOKEN

def send_fb_message(recipient_id: str, text: str):
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    headers = {
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 200:
        print(f"Error al enviar mensaje: {response.status_code} - {response.text}")
