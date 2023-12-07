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
            link = item.find('link').text
            titles_today.append((title, link))

    titles_text = ' ;'.join([f"Заголовок: {title}, Ссылка: {link}" for title, link in titles_today])
    return titles_text


def process_titles_with_gpt(titles_text):
    prompt_text = (
            "Обобщите заголовки следующих новостей, представив их в виде короткого бюллетеня. "
            "Используйте новую строку для каждого пункта. Для новостей на похожие темы, "
            "пожалуйста, сгруппируйте ссылки рядом с соответствующими заголовками. "
            "Отформатируй итоговый текст в Markdown"
            "Вот пары заголовков и ссылок:" + titles_text
    )
    response = client.chat.completions.create(  # Используйте 'completions.create' для получения ответа
        model="gpt-4-0613",
        messages=[
            {"role": "system", "content": "Ты ассистент русскоязычного руководителя"},
            {"role": "user", "content": prompt_text},
        ],
        max_tokens=4096
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
        "parse_mode": "MarkdownV2",
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(send_message_url, data=data)
        response.raise_for_status()  # Вызывает исключение для неудачных HTTP-запросов
        if response.status_code == 200:
            print("Сообщение успешно отправлено")
        else:
            print(f"Ошибка при отправке сообщения: {response.status_code}")
    except requests.RequestException as e:
        print(f"Произошла ошибка при отправке сообщения: {e}")

    return response.json()

def escape_markdown(text):
    escape_chars = '_~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in text])



def job():
    url = load_config("feed_url")
    today_titles = fetch_news_titles(url)
    summary = process_titles_with_gpt(today_titles)
    print(summary)
    escaped_message = escape_markdown(summary)
    send_telegram_message(escaped_message)

job()