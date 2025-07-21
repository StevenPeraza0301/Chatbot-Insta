
import time
import threading
from config import INACTIVITY_TIMEOUT
import os
import json

conversation_history = {}
context_cache = {}
history_lock = threading.Lock()

def update_history(user_id: str, user_msg: str, bot_msg: str):
    with history_lock:
        now = time.time()
        hist_data = conversation_history.get(user_id, {"history": [], "last_time": now})
        if now - hist_data["last_time"] > INACTIVITY_TIMEOUT:
            hist_data["history"] = []
        hist_data["history"].append({"role": "user", "content": user_msg})
        hist_data["history"].append({"role": "assistant", "content": bot_msg})
        hist_data["last_time"] = now
        conversation_history[user_id] = hist_data

def get_user_history(user_id: str) -> tuple[list, bool]:
    with history_lock:
        now = time.time()
        hist_data = conversation_history.get(user_id)
        if not hist_data:
            return [], False
        last_time = hist_data.get("last_time", now)
        if now - last_time > INACTIVITY_TIMEOUT:
            return [], True
        return hist_data["history"], False

def reset_user_history(user_id: str):
    with history_lock:
        conversation_history[user_id] = {
            "history": [],
            "last_time": time.time()
        }
        context_cache[user_id] = ""

def get_context(user_id: str) -> str:
    return context_cache.get(user_id, "")

def set_context(user_id: str, context: str):
    context_cache[user_id] = context

def reset_context(user_id: str):
    context_cache[user_id] = ""

def clear_inactive_sessions(timeout=INACTIVITY_TIMEOUT):
    with history_lock:
        now = time.time()
        to_clear = [uid for uid, data in conversation_history.items() if now - data["last_time"] > timeout]
        for uid in to_clear:
            del conversation_history[uid]
            if uid in context_cache:
                del context_cache[uid]

def clear_all_histories():
    with history_lock:
        conversation_history.clear()
        context_cache.clear()
