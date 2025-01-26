import os
import json
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')

# Handle Google credentials
if GOOGLE_CREDENTIALS_JSON:
    # For Railway deployment
    credentials_path = '/app/credentials/client_secret.json'
    os.makedirs('/app/credentials', exist_ok=True)
    with open(credentials_path, 'w') as f:
        f.write(GOOGLE_CREDENTIALS_JSON)
    GOOGLE_CREDENTIALS_FILE = credentials_path
else:
    # For local development
    GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', './credentials/client_secret.json')

if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    raise ValueError(f"Google credentials file not found at {GOOGLE_CREDENTIALS_FILE}") 