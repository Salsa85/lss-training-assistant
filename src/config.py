import os
import json
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

# Handle Google credentials for Railway
if os.getenv('RAILWAY_ENVIRONMENT'):
    # Create credentials file from environment variable
    GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if GOOGLE_CREDENTIALS_JSON:
        credentials_path = './credentials/client_secret.json'
        os.makedirs('./credentials', exist_ok=True)
        with open(credentials_path, 'w') as f:
            f.write(GOOGLE_CREDENTIALS_JSON)
        GOOGLE_CREDENTIALS_FILE = credentials_path
else:
    GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE') 