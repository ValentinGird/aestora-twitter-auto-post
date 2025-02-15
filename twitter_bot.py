import os
import time
import tweepy
import gspread
import requests
import random
import json
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

TWEET_LOG_FILE = "tweet_log.json"  # Fichier pour enregistrer les tweets postés
USED_IMAGES_FILE = "used_images.json"  # Fichier pour éviter la répétition des images

# Vérifier et créer le fichier used_images.json s'il n'existe pas
if not os.path.exists(USED_IMAGES_FILE):
    with open(USED_IMAGES_FILE, "w", encoding="utf-8") as file:
        json.dump([], file)  # Initialise avec une liste vide
    print("🆕 Fichier used_images.json créé !")

def authenticate_twitter():
    """ Authentification à l'API Twitter """
    twitter_api_key = os.getenv("TWITTER_API_KEY")
    twitter_api_secret = os.getenv("TWITTER_API_SECRET")
    twitter_access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    twitter_access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    if not all([twitter_api_key, twitter_api_secret, twitter_access_token, twitter_access_secret]):
        raise ValueError("🚨 ERREUR : Une ou plusieurs variables Twitter sont manquantes. Vérifie Railway.")

    auth = tweepy.OAuthHandler(twitter_api_key, twitter_api_secret)
    auth.set_access_token(twitter_access_token, twitter_access_secret)

    print("✅ Connexion à l'API Twitter réussie !")

    return tweepy.API(auth, wait_on_rate_limit=True), tweepy.Client(
        bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
        consumer_key=twitter_api_key,
        consumer_secret=twitter_api_secret,
        access_token=twitter_access_token,
        access_token_secret=twitter_access_secret
    )

def authenticate_google_sheets():
    """ Authentification à l'API Google Sheets """
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    google_creds = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if not google_creds:
        raise ValueError("🚨 ERREUR : GOOGLE_SHEETS_CREDENTIALS non définie ! Vérifie Railway.")

    google_creds = json.loads(google_creds)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
    client = gspread.authorize(creds)
    print("✅ Connexion à Google Sheets réussie !")
    return client

def load_used_images():
    """ Charge la liste des images utilisées depuis le fichier """
    if os.path.exists(USED_IMAGES_FILE):
        with open(USED_IMAGES_FILE, "r", encoding="utf-8") as file:
            used_images = json.load(file)
            print(f"📂 {len(used_images)} images utilisées chargées depuis le fichier.")
            return used_images
    print("📂 Aucune image utilisée trouvée.")
    return []

def save_used_image(image_url):
    """ Enregistre une image utilisée et supprime la plus ancienne si nécessaire """
    used_images = load_used_images()

    if image_url in used_images:
        print("🔄 Image déjà utilisée, pas d'ajout.")
        return  # Ne pas ajouter de doublon

    used_images.append(image_url)

    # Si la liste dépasse 300 images, supprimer la plus ancienne (FIFO)
    if len(used_images) > 300:
        removed_image = used_images.pop(0)
        print(f"🔄 Suppression de l'image la plus ancienne : {removed_image}")

    with open(USED_IMAGES_FILE, "w", encoding="utf-8") as file:
        json.dump(used_images, file, indent=4)

    print(f"✅ Nouvelle image enregistrée : {image_url}")
    print(f"📊 Nombre total d'images enregistrées : {len(used_images)}")

def get_random_tweet(sheet):
    """ Récupère une ligne aléatoire qui n'a pas été postée récemment """
    rows = sheet.get_all_values()[1:]  # Exclure l'en-tête
    if not rows:
        print("❌ Aucun tweet trouvé dans Google Sheets !")
        return None

    used_images = load_used_images()

    # Filtrer les tweets dont l'image n'a pas été postée récemment
    available_tweets = [row for row in rows if row[1] not in used_images]

    if not available_tweets:
        print("⚠️ Toutes les images ont été utilisées récemment. Sélection aléatoire parmi toutes les images.")
        available_tweets = rows  # Réutilisation des images plus anciennes

    tweet_data = random.choice(available_tweets)

    print(f"🎯 Tweet sélectionné : {tweet_data[0]}")
    print(f"🖼️ Images sélectionnées : {tweet_data[1]}, {tweet_data[2]}")

    # Sauvegarde de l'image utilisée
    save_used_image(tweet_data[1])

    return tweet_data

def upload_images_v1(api_v1, image_urls):
    """ Télécharge et upload une ou plusieurs images sur Twitter """
    media_ids = []
    for image_url in image_urls:
        if image_url and image_url.startswith("http"):
            response = requests.get(image_url)
            if response.status_code == 200:
                filename = "temp.jpg"
                with open(filename, "wb") as file:
                    file.write(response.content)
                media = api_v1.media_upload(filename)
                os.remove(filename)
                media_ids.append(media.media_id)
                print(f"✅ Image uploadée avec succès : {image_url}")
            else:
                print(f"⚠️ Erreur de téléchargement image : {response.status_code}")
    return media_ids

def post_tweet_v2(client, tweet_text, media_ids=None, reply_to=None):
    """ Poste un tweet en ajoutant des médias et/ou en tant que réponse """
    try:
        response = client.create_tweet(text=tweet_text, media_ids=media_ids, in_reply_to_tweet_id=reply_to)
        tweet_id = response.data['id']
        print(f"✅ Tweet posté : https://twitter.com/user/status/{tweet_id}")

        # Enregistrer le tweet posté avec un horodatage
        log_tweet(tweet_id)

        return tweet_id
    except tweepy.TweepyException as e:
        print(f"🚨 Erreur de publication : {e}")
        return None

def log_tweet(tweet_id):
    """ Enregistre un tweet posté avec un horodatage """
    now = int(time.time())
    log_entry = {"tweet_id": tweet_id, "timestamp": now}

    if os.path.exists(TWEET_LOG_FILE):
        with open(TWEET_LOG_FILE, "r", encoding="utf-8") as file:
            logs = json.load(file)
    else:
        logs = []

    logs.append(log_entry)

    with open(TWEET_LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(logs, file, indent=4)

    print(f"📝 Tweet {tweet_id} enregistré dans le journal.")

def count_tweets_last_24h():
    """ Compte les tweets postés dans les dernières 24h """
    now = int(time.time())
    if os.path.exists(TWEET_LOG_FILE):
        with open(TWEET_LOG_FILE, "r", encoding="utf-8") as file:
            logs = json.load(file)
    else:
        logs = []

    # Filtrer les tweets postés dans les dernières 24 heures
    recent_tweets = [t for t in logs if now - t["timestamp"] < 86400]

    with open(TWEET_LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(recent_tweets, file, indent=4)

    tweet_count = len(recent_tweets)
    print(f"📊 Nombre de tweets postés dans les dernières 24h : {tweet_count}/10")
    return tweet_count

def post_tweet(api_v1, api_v2, sheet):
    """ Poste un tweet aléatoire avec ses images et une réponse """
    tweet_data = get_random_tweet(sheet)
    if not tweet_data:
        print("❌ Aucun tweet à poster.")
        return

    text, image1, image2, reply_text = tweet_data[0], tweet_data[1], tweet_data[2], tweet_data[3]
    print(f"📝 Préparation du tweet : {text}")

    media_ids = upload_images_v1(api_v1, [image1, image2])

    tweet_id = post_tweet_v2(api_v2, text, media_ids)

    if tweet_id and reply_text.strip():
        print("🔄 Poste de la réponse au tweet...")
        post_tweet_v2(api_v2, reply_text, reply_to=tweet_id)

def main():
    api_v1, api_v2 = authenticate_twitter()
    client = authenticate_google_sheets()
    sheet = client.open("X - Aestora").sheet1

    while True:
        tweet_count = count_tweets_last_24h()
        if tweet_count < 10:
            print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Préparation pour poster un nouveau tweet...")
            post_tweet(api_v1, api_v2, sheet)
            delay = random.randint(7200, 21600)
            print(f"⏳ Prochain tweet dans {delay // 3600} heures ({delay} secondes)")
            time.sleep(delay)
        else:
            print("🚨 Limite de 10 tweets atteinte, attente du reset...")
            time.sleep(3600)

if __name__ == "__main__":
    print("🏁 Démarrage du script...")
    main()
