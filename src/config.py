import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

# Handle credentials path based on environment
if os.getenv('RAILWAY_ENVIRONMENT'):
    CREDENTIALS_DIR = '/app/credentials'
    CREDENTIALS_FILE = 'client_secret.json'
else:
    CREDENTIALS_DIR = './credentials'
    CREDENTIALS_FILE = 'client_secret_1041075119938-eussvr0f6t0c94rbcnuspdtomrknmbt0.apps.googleusercontent.com.json'

# Ensure credentials directory exists
os.makedirs(CREDENTIALS_DIR, exist_ok=True)

# Set credentials file path
GOOGLE_CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, CREDENTIALS_FILE)

# Handle Google credentials for Railway
if os.getenv('RAILWAY_ENVIRONMENT') and os.getenv('GOOGLE_CREDENTIALS_JSON'):
    with open(GOOGLE_CREDENTIALS_FILE, 'w') as f:
        f.write(os.getenv('GOOGLE_CREDENTIALS_JSON'))

if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    raise ValueError(f"Google credentials file not found at {GOOGLE_CREDENTIALS_FILE}") 