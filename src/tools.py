from openai import OpenAI
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pandas as pd
import pickle
import os.path
import re
from tenacity import retry, stop_after_attempt, wait_exponential
from fastapi import HTTPException
import os
import logging
from ratelimit import limits, sleep_and_retry
import json
import io
import urllib.parse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ONE_MINUTE = 60
MAX_REQUESTS_PER_MINUTE = 50

def clean_training_name(training_name):
    """Remove dates and clean up training names"""
    if not isinstance(training_name, str):
        training_name = str(training_name)
        
    # Remove dates in format dd/mm/yyyy or d/m/yyyy
    training_name = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}', '', training_name)
    
    # Remove dates in format dd-mm-yyyy or d-m-yyyy
    training_name = re.sub(r'\s+\d{1,2}-\d{1,2}-\d{4}', '', training_name)
    
    # Remove extra whitespace
    training_name = ' '.join(training_name.split())
    
    return training_name.strip()

def clean_company_name(company_name):
    """Clean and standardize company names"""
    if not isinstance(company_name, str):
        company_name = str(company_name)
    
    # Basic cleaning
    company_name = company_name.strip()
    company_name = ' '.join(company_name.split())  # Normalize whitespace
    
    # Remove common legal suffixes
    suffixes = [' bv', ' b.v.', ' nv', ' n.v.', ' inc', ' ltd']
    for suffix in suffixes:
        if company_name.lower().endswith(suffix):
            company_name = company_name[:-len(suffix)]
    
    return company_name.strip()

def standardize_date(date_str):
    """Standardize date format"""
    try:
        if not isinstance(date_str, str):
            date_str = str(date_str)
        # Remove any leading/trailing whitespace
        date_str = date_str.strip()
        # Parse the date
        date_obj = pd.to_datetime(date_str, format='%d-%m-%Y')
        return date_obj.strftime('%d-%m-%Y')
    except:
        logger.warning(f"Could not parse date: {date_str}")
        return date_str

def company_matches_query(company_name, query):
    """Check if company name matches query using flexible matching"""
    company = company_name.lower()
    search = query.lower()
    
    # Direct substring match
    if search in company or company in search:
        return True
    
    # Split into words and check for partial matches
    company_words = set(company.split())
    search_words = set(search.split())
    
    # Check if any search word is part of any company word or vice versa
    for sword in search_words:
        for cword in company_words:
            if sword in cword or cword in sword:
                return True
    
    return False

def get_sheets_service(credentials_file, scopes):
    """Initialize and return Google Sheets service"""
    # For Railway deployment
    if os.getenv('RAILWAY_ENVIRONMENT'):
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        if not creds_json:
            raise ValueError("GOOGLE_CREDENTIALS_JSON not found in environment")
        try:
            creds_dict = json.loads(creds_json)
            # Check if we have a refresh token
            if 'refresh_token' in creds_dict:
                creds = Credentials.from_authorized_user_info(creds_dict, scopes)
            else:
                # Fall back to client secrets
                flow = InstalledAppFlow.from_client_config(creds_dict, scopes)
                creds = flow.run_local_server(port=0)
        except Exception as e:
            logger.error(f"Error initializing credentials: {str(e)}")
            raise
    else:
        # For local development
        if not os.path.exists(credentials_file):
            raise ValueError(f"Credentials file not found at {credentials_file}")
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_file, scopes)
        creds = flow.run_local_server(port=0)
    
    return build('sheets', 'v4', credentials=creds) 