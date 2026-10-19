"""Interactive pairing on the owner's Mac; no token is written to disk/logs."""

import getpass
import re
import secrets
import subprocess
import sys
import time

from telegram_notify import TelegramError, send, telegram_api


REPO = 'StarkDegenz/GPT-5h-RESET'


def paired_chat(updates, nonce):
    chats = set()
    for update in updates:
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        sender = message.get('from') or {}
        if (message.get('text') == '/start ' + nonce and
                chat.get('type') == 'private' and
                type(chat.get('id')) is int and chat['id'] > 0 and
                sender.get('id') == chat['id'] and not sender.get('is_bot')):
            chats.add(chat['id'])
    if len(chats) > 1:
        raise TelegramError('Plusieurs destinataires détectés : recommencer l’association.')
    return next(iter(chats), None)


def save_secret(name, value):
    result = subprocess.run(['gh', 'secret', 'set', name, '--repo', REPO],
                            input=value.encode(), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    if result.returncode:
        raise TelegramError('Enregistrement GitHub impossible ; aucun détail secret affiché.')


def main():
    if not sys.stdin.isatty():
        raise TelegramError('Un terminal interactif avec saisie masquée est obligatoire.')
    print('Connexion Telegram → secrets GitHub du dépôt ' + REPO)
    print('Le jeton sera envoyé uniquement à Telegram et aux secrets GitHub.')
    token = getpass.getpass('Colle le jeton BotFather ici (saisie masquée), puis Entrée : ').strip()
    bot = telegram_api(token, 'getMe')
    username = bot.get('username', '')
    if not bot.get('is_bot') or not re.fullmatch(r'[A-Za-z0-9_]+', username):
        raise TelegramError('Le compte du bot n’a pas pu être vérifié.')
    if telegram_api(token, 'getWebhookInfo').get('url'):
        raise TelegramError('Ce bot utilise déjà un webhook. Association arrêtée sans modifier sa configuration.')
    nonce = secrets.token_urlsafe(24)
    print('Bot vérifié : @' + username)
    print('Ouvre ce lien et appuie sur Démarrer dans Telegram :')
    print('https://t.me/' + username + '?start=' + nonce)
    print('Le lien expire à la fermeture de cet assistant. Ne le partage pas.')
    deadline = time.monotonic() + 300
    chat = None
    while time.monotonic() < deadline:
        chat = paired_chat(telegram_api(token, 'getUpdates', {'timeout': 0}), nonce)
        if chat:
            break
        time.sleep(3)
    if chat is None:
        raise TelegramError('Association non reçue après cinq minutes. Aucun secret enregistré.')
    if input('Enregistrer ce bot pour ce compte Telegram dans GitHub ? Tape OUI : ').strip() != 'OUI':
        print('Association annulée ; aucun secret enregistré.')
        return
    # Store destination first. Token is the final activation credential.
    save_secret('TELEGRAM_CHAT_ID', str(chat))
    save_secret('TELEGRAM_BOT_TOKEN', token)
    send(token, chat, '✅ Connexion Telegram enregistrée pour GPT-5h-RESET. Ceci est un message de test de notification, sans appel ChatGPT.')
    print('Secrets enregistrés et message de test envoyé. Confirme sa réception dans Telegram.')


if __name__ == '__main__':
    try:
        main()
    except (TelegramError, OSError, KeyboardInterrupt, EOFError):
        print('Association arrêtée ou échouée. Aucun jeton ni erreur brute affiché. Si l’envoi de test a échoué après l’enregistrement, les secrets peuvent déjà être présents dans GitHub.')
        raise SystemExit(1)
