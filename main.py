# [Ada]
#
# Bot de telegram con panel de administración web que permite notificar a los administradores
# y enviar mensajes a través de una API REST, por Sebastian Findling. [https://github.com/sebolio/ada]

import telebot
import flask
import sqlite3
import base64
import requests
import uuid
import logging
import signal
import sys
import os
import re
from functools import wraps
from telebot.types import Message
from flask import Flask, send_file, request, render_template, jsonify, g
from threading import Thread
from datetime import datetime, timedelta
from importlib import reload

def run_setup():
  try:
    code=os.system(f"{sys.executable} setup.py")
    if code == 0:
      print("\n✅ Configuración guardada. Puedes cambiarla usando: \033[33mpython setup.py\033[m")
      if 'config' in sys.modules:
        reload(sys.modules['config'])
      else:
        import config
    else:
      print("❌ No se completó la configuración.")
      sys.exit()
  except Exception as e:
    print(f"❌ Error en la configuración: {e}")
    sys.exit()

# Correr setup si no existe config.py
while True:
  try:
    import config
    break
  except ImportError:
    run_setup()
  
# Inicializar bot de Telegram
if not config.TELEGRAM_TOKEN:
  print("❌ No has configurado el token de Telegram.")
  run_setup()

while True:
  try:
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    bot.set_my_description("👩🏻‍🎤\n\nBot de telegram con panel de administración web que permite notificar a los administradores y enviar mensajes a través de una API REST.\n\nCreado por Sebastian Findling\n\nhttps://github.com/sebolio/ada")
    break
  except:
    print(f"\n❌ Parece que el token de Telegram es incorrecto ('\033[31m{config.TELEGRAM_TOKEN}\033[m')")
    run_setup()
    
bot.set_my_commands([
    telebot.types.BotCommand("/start", "Primeros pasos"),
    telebot.types.BotCommand("/panel", "Abrir panel administrativo")
])

cli = sys.modules['flask.cli']
cli.show_server_banner = lambda *x: None
app = flask.Flask(__name__)

DATABASE = 'bot_data.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS topics
                          (id INTEGER PRIMARY KEY, name TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                          (id INTEGER, message_id INTEGER PRIMARY KEY, text TEXT, 
                           topic TEXT, sent BOOLEAN, received BOOLEAN, read BOOLEAN, 
                           timestamp DATETIME)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS api_calls
                          (id INTEGER PRIMARY KEY, endpoint TEXT, method TEXT, 
                           params TEXT, response TEXT, success BOOLEAN, timestamp DATETIME)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS chats
                          (id INTEGER PRIMARY KEY, user_id TEXT, user_username TEXT,
                           user_name TEXT, message TEXT, timestamp DATETIME)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_users
                          (id INTEGER PRIMARY KEY, user_id INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS tokens (
                              token TEXT PRIMARY KEY,
                              expires_at DATETIME)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings
                  (key TEXT PRIMARY KEY, value TEXT)''')
        db.commit()

init_db()

def generate_token():
    token = str(uuid.uuid4()).split('-')[0]
    expires_at = datetime.utcnow() + timedelta(minutes=config.WEB_SESSION_EXPIRY)
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM tokens WHERE expires_at < ?", (datetime.utcnow(),))
    cursor.execute("INSERT INTO tokens (token, expires_at) VALUES (?, ?)", (token, expires_at))
    db.commit()
    return token
  
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not config.WEB_SESSION_REQUIRED:
            return f(*args, **kwargs)
        if len(list(request.args)) == 1 and list(request.args)[0] != 'token':
            token = list(request.args)[0]
        else:
          try:
            token = request.args.get('token') or request.form.get('token') or request.json.get('token')
          except Exception as e:
            return '', 404
        if not token:
            return jsonify({'message': 'Token requerido'}), 403
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM tokens WHERE token = ? AND expires_at > ?", (token, datetime.utcnow()))
        result = cursor.fetchone()
        if not result:
          accept = request.headers.get('Accept', '')
          is_browser = 'text/html' in accept
          if is_browser:
            return send_file('web/unauthorized.html')
          else:
            return jsonify({'message': 'Token invalido'}), 403
        return f(*args, **kwargs)
    return decorated_function
  
def get_setting(key):
  db = get_db()
  cursor = db.cursor()
  cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
  result = cursor.fetchone()
  return result[0] if result else None

def set_setting(key, value):
  db = get_db()
  cursor = db.cursor()
  cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
  db.commit()
    
def get_admin_users():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT user_id FROM admin_users")
    return [row[0] for row in cursor.fetchall()]

def get_topics():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM topics")
    return [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]

def log_message(user, message):
  with app.app_context():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO chats
                  (user_id, user_username, user_name, message, timestamp)
                  VALUES (?, ?, ?, ?, ?)''',
                  (user.id, user.username, user.first_name, str(message.text), datetime.now()))
    db.commit()
 
def admin_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    with app.app_context():
      admin_users = get_admin_users()
      message = args[0] if args else None
      if message and message.from_user.id not in admin_users:
        bot.send_message(message.chat.id, "😂")
        return
    return f(*args, **kwargs)
  return decorated_function

@bot.message_handler(commands=["start"])
def start_communication(message):
  user = message.from_user
  chat = message.chat
  with app.app_context():
    if not get_admin_users():
      greeting = f"¡Hola {user.first_name}!\n\n"
      greeting += f"Como es la primera vez que corres el bot, he configurado tu cuenta de Telegram como administrador ({user.id}).\n\n"
      greeting += f"Ahora puedes acceder al panel de administración usando el comando /panel y enviar mensajes a través de la API REST."
      bot.send_message(message.chat.id, greeting)
      db=get_db()
      cursor = db.cursor()
      cursor.execute("INSERT INTO admin_users (user_id) VALUES (?)", (user.id,))
      db.commit()
      return
    if user.id in get_admin_users():
      send_admin_panel(message)
    else:
      greeting = f"Hola {user.first_name}!\n\n"
      bot.reply_to(message, "No te conozco, pero puedes conocerme a mí en: https://github.com/sebolio/ada")

@bot.message_handler(commands=["panel"])
@admin_required
def send_admin_panel(message):
  with app.app_context():
    log_message(message.from_user, message)
    if not config.WEB_SESSION_REQUIRED:
      text ="👩🏻‍🎤 *Panel de Administración*\n\nAviso: tu panel no está protegido. Modifica el valor de `WEB_SESSION_REQUIRED` en  `config.py` o ejecuta la configuración automática con `python setup.py`, "
      text+="de lo contrario cualquier persona puede acceder a esta URL y utilizarlo.\n\nUtiliza este botón para acceder:"
      url = f'{config.PUBLIC_URL}'
    else: 
      text="👩🏻‍🎤 *Panel de Administración*\n\nUtiliza este botón para acceder:"
      token = generate_token()
      url = f'{config.PUBLIC_URL}/?{token}'
    keyboard = telebot.types.InlineKeyboardMarkup()
    button = telebot.types.InlineKeyboardButton(text="Abrir Panel de Administración", url=url)
    keyboard.add(button)
    
    # Eliminar mensaje anterior con botón de Panel
    last_message = get_setting('admin_panel_message_id')
    if last_message:
      try:
        bot.delete_message(message.chat.id, last_message)
      except Exception as e:
        pass
    
    new_message=bot.send_message(message.chat.id, text, reply_markup=keyboard, parse_mode='Markdown')
    set_setting('admin_panel_message_id', new_message.message_id)

@bot.message_handler(regexp="^.*$")
def log_chat(message):
  with app.app_context():
    log_message(message.from_user, message)


################ WEB y API ################

@app.route('/')
@token_required
def index():
    with open('web/index.html', 'r') as file:
      content = file.read()
      content = content.replace('{botUser}', bot.get_me().username)
      if not config.WEB_SESSION_REQUIRED:
        content = "<script>window.tokenDisabled=true;</script>"+content
    return content
  
@app.route('/web/<file>', methods=['GET'])
def get_file(file):
   return send_file(f'web/{file}')

@app.route('/<topic>/<message>', methods=['GET'])
def simple_say(topic, message):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM topics WHERE name = ?", (topic,))
    topic_exists = cursor.fetchone()[0]
    if topic_exists:
      for user in get_admin_users():
        msg = bot.send_message(user, message)
      cursor.execute('''INSERT INTO messages 
                      (message_id, text, topic, sent, received, read, timestamp) 
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (msg.message_id, message, topic, True, True, False, datetime.now()))
      db.commit()
      success = True
      response = f'Enviado ({msg.message_id})'
    else:
      success = False
      response = 'Topic inválido'
    cursor.execute('''INSERT INTO api_calls 
                    (endpoint, method, params, response, success, timestamp) 
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    ('/'+topic, 'GET', str(message), response, success, datetime.now()))
    db.commit()
    return jsonify({'success': success})
      
@app.route('/say', methods=['POST'])
def say():
    db = get_db()
    cursor = db.cursor()
    data = request.form
    text = data.get('text', '')
    topic = data.get('topic', '')
    message_type = data.get('type', 'message')
    update_id = int(data.get('updateId', 0))
    target_user = int(data.get('targetUser', 0))
    
    image_url = data.get('imageUrl')
    image_base64 = data.get('imageBase64')

    if topic not in [t['name'] for t in get_topics()]:
        return jsonify({'success': False, 'message': 'Invalid topic'})

    if target_user:
        target_users = [target_user]
        if target_user not in get_admin_users():
            return jsonify({'success': False, 'message': 'User is not an admin'})
    else:
        target_users = get_admin_users()

    text = text.replace('\\n', '\n')
    
    responses = []
    for user in target_users:
        try:
            if update_id:
                message = bot.edit_message_text(chat_id=user, message_id=update_id, text=text)
            else:
                if image_url:
                    message = bot.send_photo(user, image_url, caption=text)
                elif image_base64:
                    image_data = base64.b64decode(image_base64)
                    message = bot.send_photo(user, image_data, caption=text)
                else:
                    message = bot.send_message(user, text)

            cursor.execute('''INSERT OR REPLACE INTO messages 
                          (message_id, text, topic, sent, received, read, timestamp) 
                          VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          (message.message_id, text, topic, True, True, False, datetime.now()))
            db.commit()

            responses.append({
                'success': True,
                'message_id': message.message_id,
                'chat_id': user
            })
        except Exception as e:
            responses.append({
                'success': False,
                'error': str(e),
                'chat_id': user
            })

    cursor.execute('''INSERT INTO api_calls 
                      (endpoint, method, params, response, success, timestamp) 
                      VALUES (?, ?, ?, ?, ?, ?)''',
                   ('/say', 'POST', str(data), str(responses), True, datetime.now()))
    db.commit()

    return jsonify(responses)

@app.route('/topics', methods=['GET', 'POST', 'DELETE'])
@token_required
def manage_topics():
    db = get_db()
    cursor = db.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM topics")
        topics = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
        return jsonify(topics)
    elif request.method == 'POST':
        topic = request.json['name']
        cursor.execute("INSERT INTO topics (name) VALUES (?)", (topic,))
        db.commit()
        return jsonify({'success': True, 'message': 'Topic added'})
    elif request.method == 'DELETE':
        topic_id = request.json['id']
        cursor.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        db.commit()
        return jsonify({'success': True, 'message': 'Topic deleted'})

@app.route('/logs/messages', methods=['GET'])
@token_required
def get_message_logs():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM messages ORDER BY timestamp DESC")
    messages = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
    return jsonify(messages)

@app.route('/logs/api_calls', methods=['GET'])
@token_required
def get_api_call_logs():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM api_calls ORDER BY timestamp DESC")
    api_calls = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
    return jsonify(api_calls)
  
@app.route('/logs/chats', methods=['GET'])
@token_required
def get_chat_logs():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM chats ORDER BY timestamp DESC")
    chats = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
    return jsonify(chats)

@app.route('/admins', methods=['GET', 'POST', 'DELETE'])
@token_required
def manage_admins():
    db = get_db()
    cursor = db.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM admin_users")
        admins = [{'id': row[0], 'user_id': row[1]} for row in cursor.fetchall()]
        return jsonify(admins)
    elif request.method == 'POST':
        user_id = request.json['user_id']
        cursor.execute("INSERT INTO admin_users (user_id) VALUES (?)", (user_id,))
        db.commit()
        return jsonify({'success': True, 'message': 'Admin added'})
    elif request.method == 'DELETE':
        admin_id = request.json['id']
        cursor.execute("DELETE FROM admin_users WHERE id = ?", (admin_id,))
        db.commit()
        return jsonify({'success': True, 'message': 'Admin deleted'})

def run_flask():
  app.run(host=config.WEB_SERVER_HOST, port=config.WEB_SERVER_PORT)

flask_thread = Thread(target=run_flask)
flask_thread.start()

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
print("🌐 Web corriendo en:", config.PUBLIC_URL)

def signal_handler(signum, frame):
  print('Presiona Ctrl+C una vez más')
  sys.exit()
signal.signal(signal.SIGINT, signal_handler)

def print_welcome(text):
  padding = " " * (60 - len(text))
  url_pattern = r'(https?://\S+)'
  colored_text = re.sub(url_pattern, r'\033[1;38;5;226m\1\033[38;5;231;48;5;128m', text)
  print(f"\033[38;5;231;48;5;128m {colored_text}{padding}\033[0m")

with app.app_context():
  if not get_admin_users():
    username=bot.get_me().username
    print_welcome("¡Aún no sé quién eres!")
    print_welcome("")
    print_welcome("Debes añadirme a tu Telegram para configurarte como admin.")
    print_welcome(f"Accede aquí: https://t.me/{username}")
  else:
    print("🤖 Ada corriendo en Telegram: https://t.me/"+bot.get_me().username)

while True:
  bot.infinity_polling(timeout=60, long_polling_timeout=60, none_stop=True)
  print("Reiniciando polling:", datetime.now()) 