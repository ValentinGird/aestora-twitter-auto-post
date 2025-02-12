import os
import time
import tweepy
import gspread
import requests
import random
import json
from oauth2client.service_account import ServiceAccountCredentials

LOG_FILE = "tweets_log.json"

def count_tweets_last_24h():
    """Compte le nombre de tweets postés dans les dernières 24 heures"""
    now = time.time()

    # Vérifier si le fichier existe, sinon le créer
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            json.dump({"tweets": []}, f)

    # Lire le fichier correctement
    with open(LOG_FILE, "r") as f:
        try:
            logs = json.load(f)  # Convertir la string JSON en dictionnaire
        except json.JSONDecodeError:
            logs = {"tweets": []}  # Si fichier corrompu, on le réinitialise
    
    recent_tweets = [t for t in logs["tweets"] if now - t["timestamp"] < 86400]
    
    return len(recent_tweets)

def log_tweet():
    """Ajoute un tweet dans le log avec timestamp"""
    now = time.time()

    # Charger les logs existants
    with open(LOG_FILE, "r") as f:
        logs = json.load(f)

    # Ajouter le tweet
    logs["tweets"].append({"timestamp": now})

    # Écrire le log mis à jour
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f)

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

def upload_image_v1(api_v1, image_url):
    """ Télécharge et upload une image sur Twitter via l'API v1.1, retourne le media_id """
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
    """ Poste un tweet avec l'API v2 en ajoutant un média si disponible """
    try:
        if media_id:
            response = client.create_tweet(text=tweet_text, media_ids=[media_id])
        else:
            response = client.create_tweet(text=tweet_text)

        tweet_id = response.data["id"]
        print(f"✅ Tweet posté : https://twitter.com/user/status/{tweet_id}")

        log_tweet()  # Enregistrer le tweet dans le log
        
        return tweet_id

    except tweepy.TweepyException as e:
        print(f"🚨 Erreur lors de la publication : {e}")
        return None

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
    """ Récupère le prochain tweet à poster (toujours ligne 2) """
    tweets = sheet.get_all_values()[1:]  
    return tweets[0] if tweets else None

def post_tweet(api_v1, api_v2, sheet, tweet_data):
    """ Poste un tweet principal avec une image en utilisant API v1.1 pour l'image et API v2 pour le tweet """
    try:
        media_id = upload_image_v1(api_v1, tweet_data[1]) if tweet_data[1] else None
        tweet_id = post_tweet_v2(api_v2, tweet_data[0], media_id)

        # Si la colonne C contient un texte, le poster en réponse
        if tweet_id and len(tweet_data) > 2 and tweet_data[2].strip():
            post_tweet_v2(api_v2, tweet_data[2], reply_to=tweet_id)
        
        # Supprimer la ligne après publication
        sheet.delete_rows(2)
        print(f"✅ Tweet posté et supprimé de Google Sheets : {tweet_id}")

    except Exception as e:
        print(f"🚨 Erreur lors de la publication : {e}")

def main():
    api_v1, api_v2 = authenticate_twitter()
    client = authenticate_google_sheets()
    sheet = client.open("X - Aestora").sheet1

    while True:
        tweets_posted = count_tweets_last_24h()

        if tweets_posted < 5:
            tweet_data = get_next_tweet(sheet)
            if tweet_data:
                post_tweet(api_v1, api_v2, sheet, tweet_data)
                delay = random.randint(7200, 21600)  # Attente aléatoire entre 2h et 6h
                print(f"⏳ Prochain tweet dans {delay // 3600} heures")
                time.sleep(delay)
            else:
                print("❌ Plus de tweets disponibles, en attente de nouveaux...")
                time.sleep(3600)  # Vérifier à nouveau après 1h
        else:
            print("🚨 Limite de 5 tweets atteinte sur 24h. En attente avant de recommencer...")
            time.sleep(3600)  # Vérifier toutes les heures

if __name__ == "__main__":
    main()
