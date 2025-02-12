import os
import time
import tweepy
import gspread
import requests
import random
import json
from oauth2client.service_account import ServiceAccountCredentials

TWEET_LOG_FILE = "tweets_log.json"


def load_tweet_log():
    """ Charge les logs des tweets envoyés """
    if os.path.exists(TWEET_LOG_FILE):
        with open(TWEET_LOG_FILE, "r") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return []
    return []


def save_tweet_log(log):
    """ Sauvegarde le log des tweets """
    with open(TWEET_LOG_FILE, "w") as file:
        json.dump(log, file, indent=4)


def count_tweets_last_24h():
    """ Compte les tweets postés dans les dernières 24h """
    logs = load_tweet_log()
    now = time.time()
    recent_tweets = [t for t in logs if now - t["timestamp"] < 86400]  # Tweets des dernières 24h
    return len(recent_tweets)


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
        raise ValueError("🚨 ERREUR : La variable GOOGLE_SHEETS_CREDENTIALS n'est pas définie ! Vérifie Railway.")

    try:
        google_creds = json.loads(google_creds)
    except json.JSONDecodeError:
        raise ValueError("🚨 ERREUR : JSON mal formaté pour GOOGLE_SHEETS_CREDENTIALS !")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
    client = gspread.authorize(creds)
    
    print("✅ Connexion à Google Sheets réussie !")
    
    return client


def get_next_tweet(sheet):
    """ Récupère le prochain tweet à poster """
    tweets = sheet.get_all_values()[1:]  # Ignore la première ligne (headers)
    return tweets[0] if tweets else None


def upload_image_v1(api_v1, image_url):
    """ Télécharge et upload une image sur Twitter via l'API v1.1 """
    if not image_url or not image_url.startswith("http"):
        print("⚠️ Aucune image valide fournie. Le tweet sera posté sans image.")
        return None  

    filename = "temp.jpg"
    response = requests.get(image_url)
    
    if response.status_code != 200:
        print(f"⚠️ Erreur lors du téléchargement de l'image : {response.status_code}")
        return None

    with open(filename, "wb") as file:
        file.write(response.content)

    media = api_v1.media_upload(filename)
    os.remove(filename)

    print(f"✅ Image uploadée avec succès, Media ID : {media.media_id}")
    
    return media.media_id


def post_tweet_v2(client, tweet_text, media_id=None):
    """ Poste un tweet avec l'API v2 """
    try:
        if media_id:
            response = client.create_tweet(text=tweet_text, media_ids=[media_id])
        else:
            response = client.create_tweet(text=tweet_text)

        tweet_id = response.data["id"]
        print(f"✅ Tweet posté : https://twitter.com/user/status/{tweet_id}")

        # Sauvegarde du tweet dans le log
        log = load_tweet_log()
        log.append({"timestamp": time.time(), "tweet_id": tweet_id})
        save_tweet_log(log)

    except tweepy.TweepyException as e:
        print(f"🚨 Erreur lors de la publication : {e}")


def main():
    api_v1, api_v2 = authenticate_twitter()
    client = authenticate_google_sheets()
    sheet = client.open("X - Aestora").sheet1

    while True:  # Le bot tourne en continu
        tweets_posted = count_tweets_last_24h()
        if tweets_posted >= 5:
            print("🚨 Limite de 5 tweets atteinte. Attente avant de réessayer...")
            time.sleep(3600)  # Attente d'une heure avant de réessayer
            continue
        
        tweet_data = get_next_tweet(sheet)
        if tweet_data:
            media_id = upload_image_v1(api_v1, tweet_data[1]) if tweet_data[1] else None
            post_tweet_v2(api_v2, tweet_data[0], media_id)
            sheet.delete_rows(2)
            delay = random.randint(7200, 21600)
            print(f"⏳ Prochain tweet dans {delay // 3600} heures")
            time.sleep(delay)
        else:
            print("❌ Plus de tweets disponibles, en attente de nouveaux...")
            time.sleep(1800)  # Vérifie à nouveau toutes les 30 min

if __name__ == "__main__":
    main()
