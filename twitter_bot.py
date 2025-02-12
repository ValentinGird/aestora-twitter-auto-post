import os
import time
import tweepy
import gspread
import requests
import random
import json
from oauth2client.service_account import ServiceAccountCredentials

def authenticate_twitter():
    """ Authentification à l'API Twitter """
    auth = tweepy.OAuthHandler(os.getenv("TWITTER_API_KEY"), os.getenv("TWITTER_API_SECRET"))
    auth.set_access_token(os.getenv("TWITTER_ACCESS_TOKEN"), os.getenv("TWITTER_ACCESS_SECRET"))
    return tweepy.API(auth, wait_on_rate_limit=True)

def authenticate_google_sheets():
    """ Authentification à l'API Google Sheets via variable d'environnement """
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Charger la clé depuis la variable d’environnement
    google_creds = json.loads(os.getenv("GOOGLE_SHEETS_CREDENTIALS"))
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
    client = gspread.authorize(creds)
    return client

def get_next_tweet(sheet):
    """ Récupère le prochain tweet à poster (toujours ligne 2) """
    tweets = sheet.get_all_values()[1:]  # Ignore la première ligne (headers)
    return tweets[0] if tweets else None

def upload_image(api, image_url):
    """ Télécharge et upload une image sur Twitter, retourne le media_id """
    filename = "temp.jpg"
    response = requests.get(image_url)
    with open(filename, "wb") as file:
        file.write(response.content)
    media = api.media_upload(filename)
    os.remove(filename)
    return media.media_id

def post_tweet(api, sheet, tweet_data):
    """ Poste un tweet principal avec une image, puis un tweet en réponse si nécessaire """
    try:
        media_id = upload_image(api, tweet_data[1])
        tweet = api.update_status(status=tweet_data[0], media_ids=[media_id])
        
        # Si la colonne C contient un texte, le poster en réponse
        if len(tweet_data) > 2 and tweet_data[2].strip():
            api.update_status(status=tweet_data[2], in_reply_to_status_id=tweet.id, auto_populate_reply_metadata=True)
        
        # Supprimer la ligne après publication
        sheet.delete_rows(2)
        print(f"Tweet posté et supprimé de Google Sheets : {tweet.id}")
    except Exception as e:
        print(f"Erreur lors de la publication : {e}")

def main():
    api = authenticate_twitter()
    client = authenticate_google_sheets()
    sheet = client.open("X - Aestora").sheet1
    
    for _ in range(5):  # 5 posts par jour
        tweet_data = get_next_tweet(sheet)
        if tweet_data:
            post_tweet(api, sheet, tweet_data)
            delay = random.randint(7200, 21600)  # Attente aléatoire entre 2h et 6h
            print(f"Prochain tweet dans {delay // 3600} heures")
            time.sleep(delay)
        else:
            print("Plus de tweets disponibles, en attente de nouveaux...")
            break

if __name__ == "__main__":
    main()
    
