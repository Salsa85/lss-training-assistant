import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID') 