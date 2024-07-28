# Este script cambia la configuración del bot. Corre automaticamente desde main.py si es necesario.

from InquirerPy import prompt
import os
import re
import sys
import shutil


def parse_config(content):
    config = {}
    for line in content.strip().split('\n'):
        if '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            if value.startswith(("'", '"')) and value.endswith(("'", '"')):
                value = value[1:-1]
            if value.isdigit():
                value = int(value)
            else:
              if str(value).lower() in ('true', 'True'):
                  value = True
              if str(value).lower() in ('false', 'False'):
                  value = False
            config[key] = value
    return config
  
def update_config_file(file_path, new_values):
    with open(file_path, 'r') as file:
        lines = file.readlines()
    updated_lines = []
    for line in lines:
        line = line.strip()
        if '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            if key in new_values and new_values[key] != '':
                new_value = new_values[key]
                if isinstance(new_value, str):
                    updated_lines.append(f"{key} = '{new_value}'")
                else:
                    updated_lines.append(f"{key} = {new_value}")
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)
    with open(file_path, 'w') as file:
        file.write('\n'.join(updated_lines))


def print_welcome(text):
  padding = " " * (73 - len(text))
  url_pattern = r'(https?://\S+|\/\S+)'
  colored_text = re.sub(url_pattern, r'\033[1;38;5;226m\1\033[38;5;231;48;5;128m', text)
  print(f"\033[38;5;231;48;5;128m {colored_text}{padding}\033[0m")

def welcome():
  print("\033[2J\033[H")
  print_welcome("¡Hola! Soy Ada")
  print_welcome("")
  print_welcome("Como es tu primera vez, voy a ayudarte a configurarme.")
  print_welcome("Para obtener un token de Telegram, habla con BotFather y escribe /newbot")
  print_welcome("BotFather es el bot que administra bots: https://t.me/botfather")
  print_welcome("")
  print_welcome("Una vez que tengas el token, pegalo aquí abajo.")

if not os.path.exists("config.py"):
  welcome()
  config=parse_config(open("config.py.example").read())
else:
  config=parse_config(open("config.py").read())
  if config["TELEGRAM_TOKEN"]=="":
    welcome()

print()
result = prompt(questions = [
    {"type": "input", "message": f"Token de Telegram [{config['TELEGRAM_TOKEN']}]:", "name": "TELEGRAM_TOKEN"},
    {"type": "input", "message": f"URL pública [{config['PUBLIC_URL']}]:", "name": "PUBLIC_URL"},
    {"type": "confirm", "message": f"Restringir acceso a web [{'Yes' if config['WEB_SESSION_REQUIRED'] else 'No'}]:", "name": "WEB_SESSION_REQUIRED", "default": config['WEB_SESSION_REQUIRED']},
    {"type": "number", "message": f"Duración de sesión web (mins) [{config['WEB_SESSION_EXPIRY']}]:", "name": "WEB_SESSION_EXPIRY", "default": config['WEB_SESSION_EXPIRY'], "when": lambda x: x["WEB_SESSION_REQUIRED"]},
])

if result["WEB_SESSION_EXPIRY"]:
  result["WEB_SESSION_EXPIRY"]=int(result["WEB_SESSION_EXPIRY"])
else:
  result.pop("WEB_SESSION_EXPIRY")
if not os.path.exists("config.py"):
  shutil.copy("config.py.example", "config.py")
update_config_file("config.py", result)