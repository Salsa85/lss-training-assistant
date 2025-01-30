import os
from dotenv import load_dotenv
import json

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

# Handle credentials path based on environment
if os.getenv('RAILWAY_ENVIRONMENT'):
    CREDENTIALS_DIR = '/app/credentials'
    CREDENTIALS_FILE = 'client_secret.json'
    
    # Create credentials from environment variable
    if os.getenv('GOOGLE_CREDENTIALS_JSON'):
        credentials_data = json.loads(os.getenv('GOOGLE_CREDENTIALS_JSON'))
        
        # Ensure it's in the correct format for installed applications
        if 'installed' not in credentials_data:
            credentials_data = {
                'installed': {
                    'client_id': credentials_data.get('client_id'),
                    'project_id': credentials_data.get('project_id'),
                    'auth_uri': credentials_data.get('auth_uri', 'https://accounts.google.com/o/oauth2/auth'),
                    'token_uri': credentials_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                    'auth_provider_x509_cert_url': credentials_data.get('auth_provider_x509_cert_url', 'https://www.googleapis.com/oauth2/v1/certs'),
                    'client_secret': credentials_data.get('client_secret'),
                    'redirect_uris': credentials_data.get('redirect_uris', ['urn:ietf:wg:oauth:2.0:oob', 'http://localhost'])
                }
            }
        
        # Ensure credentials directory exists
        os.makedirs(CREDENTIALS_DIR, exist_ok=True)
        
        # Write credentials file
        with open(os.path.join(CREDENTIALS_DIR, CREDENTIALS_FILE), 'w') as f:
            json.dump(credentials_data, f)
else:
    CREDENTIALS_DIR = './credentials'
    CREDENTIALS_FILE = 'client_secret.json'

# Set credentials file path
GOOGLE_CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, CREDENTIALS_FILE)

# Validate credentials file
if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    raise ValueError(
        f"Google credentials file not found at {GOOGLE_CREDENTIALS_FILE}\n"
        "Please create this file with your Google OAuth credentials.\n"
        "See README.md for instructions on how to set up credentials."
    )

# Validate credentials format
try:
    with open(GOOGLE_CREDENTIALS_FILE, 'r') as f:
        credentials_data = json.load(f)
        if 'installed' not in credentials_data:
            raise ValueError("Invalid credentials format: missing 'installed' key")
except Exception as e:
    raise ValueError(f"Error validating credentials: {str(e)}") 