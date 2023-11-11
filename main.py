from xml.etree import ElementTree as ET
import datetime
import requests
from openai import OpenAI

import os
import json
from typing import Optional

def load_config(key: Optional[str] = None):
    # Получение абсолютного пути к директории, где находится main.py
    current_directory = os.path.dirname(os.path.abspath(__file__))
    # Объединение этого пути с именем файла, который вы хотите открыть
    file_path = os.path.join(current_directory, "config.json")

    with open(file_path, "r") as file:
        config = json.load(file)

    if key:
        if key not in config:
            raise KeyError(f"The key '{key}' was not found in the config file.")
        return config[key]  # Возвращаем значение заданного ключа
    else:
        return config  # Возвращаем весь конфигурационный словарь


# Здесь должен быть ваш OpenAI API ключ
client = OpenAI(api_key=load_config("openai_token"))

def fetch_news_titles(url):
    response = requests.get(url)
    root = ET.fromstring(response.content)
    today = datetime.datetime.now().date()
    titles_today = []

    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        pub_date = datetime.datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z').date()
        if pub_date == today:
            title = item.find('title').text
            titles_today.append(title)

    titles_text = ' '.join(titles_today)
    return titles_text


def process_titles_with_gpt(titles_text):
    prompt_text = f"Обобщите заголовки этих новостей на русском в короткий бюллетень, разделив каждый пункт новой строкой:\n{titles_text}"
    response = client.chat.completions.create(  # Используйте 'completions.create' для получения ответа
        model="gpt-3.5-turbo-1106",
        messages=[
            {"role": "system", "content": "Ты ассистент руководителя"},
            {"role": "user", "content": prompt_text},
        ],
        max_tokens=1024
    )

    # Проверьте, является ли 'response' словарём или объектом
    # Если 'response' - это словарь (как показано в вашем примере ошибки), используйте код ниже:
    if isinstance(response, dict):
        summary = response['choices'][0]['message']['content']
    # Если 'response' - это объект, попробуйте использовать точечную нотацию:
    else:
        summary = response.choices[0].message.content
    print(summary)
    return summary


def send_telegram_message(message):
    # Place your Telegram bot's API token here
    TELEGRAM_TOKEN = load_config("TELEGRAM_BOT_TOKEN")
    # Place your own Telegram user ID here
    TELEGRAM_CHAT_ID = load_config("TELEGRAM_CHAT_ID")
    send_message_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(send_message_url, data=data)
    return response.json()


def job():
    url = load_config("feed_url")
    today_titles = fetch_news_titles(url)
    summary = process_titles_with_gpt(today_titles)
    send_telegram_message(summary)
    print(summary)

job()