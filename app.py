from flask import Flask
from flask_cors import CORS
from routes.webhook import webhook_bp
from routes.web_chat import web_chat_bp
from config import FLASK_HOST, FLASK_PORT, MODEL_NAME
import ollama

app = Flask(__name__)
CORS(app)

# Registro de rutas
app.register_blueprint(webhook_bp, url_prefix="/webhook")
app.register_blueprint(web_chat_bp, url_prefix="/chat")

# Precargar modelo Ollama al levantar el servidor
def precargar_modelo():
    try:
        print(f"Precargando modelo Ollama: {MODEL_NAME}")
        ollama.chat(model=MODEL_NAME, messages=[
            {"role": "user", "content": "Hola"}
        ])
        print("✅ Modelo precargado.")
    except Exception as e:
        print("⚠️ Error al precargar modelo Ollama:", e)

# Solo precarga si se ejecuta directamente
if __name__ == '__main__':
    precargar_modelo()
    app.run(host=FLASK_HOST, port=FLASK_PORT)
