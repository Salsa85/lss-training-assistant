"""
Tools module for the LSS Training Assistant

This module contains helper functions for data cleaning, API rate limiting,
and service initialization.
"""

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

# Constants
ONE_MINUTE = 60
MAX_REQUESTS_PER_MINUTE = 60

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_training_name(training_name: str) -> str:
    """
    Clean and standardize training names by removing dates and extra whitespace.
    
    Args:
        training_name (str): The raw training name from the spreadsheet
        
    Returns:
        str: Cleaned training name
        
    Example:
        >>> clean_training_name("Green Belt Training 12/12/2024")
        "Green Belt Training"
    """
    if not isinstance(training_name, str):
        training_name = str(training_name)
    
    # Remove dates in format dd/mm/yyyy or d/m/yyyy
    training_name = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}', '', training_name)
    
    # Remove dates in format dd-mm-yyyy or d-m-yyyy
    training_name = re.sub(r'\s+\d{1,2}-\d{1,2}-\d{4}', '', training_name)
    
    # Remove extra whitespace
    training_name = ' '.join(training_name.split())
    
    return training_name.strip()

def clean_company_name(company_name: str) -> str:
    """
    Clean and standardize company names by removing legal suffixes and normalizing whitespace.
    
    Args:
        company_name (str): The raw company name from the spreadsheet
        
    Returns:
        str: Cleaned company name
        
    Example:
        >>> clean_company_name("ACME B.V.")
        "ACME"
    """
    if not isinstance(company_name, str):
        company_name = str(company_name)
    
    # Basic cleaning
    company_name = company_name.strip()
    company_name = ' '.join(company_name.split())
    
    # Remove common legal suffixes
    suffixes = [' bv', ' b.v.', ' nv', ' n.v.', ' inc', ' ltd']
    for suffix in suffixes:
        if company_name.lower().endswith(suffix):
            company_name = company_name[:-len(suffix)]
    
    return company_name.strip()

def standardize_date(date_str: str) -> str:
    """
    Convert various date formats to standard dd-mm-yyyy format.
    
    Args:
        date_str (str): Date string in various formats
        
    Returns:
        str: Standardized date string in dd-mm-yyyy format
        
    Example:
        >>> standardize_date("1/1/2024")
        "01-01-2024"
    """
    try:
        if not isinstance(date_str, str):
            date_str = str(date_str)
        date_str = date_str.strip()
        
        # Parse using pandas (implementation in sheets_agent.py)
        from pandas import to_datetime
        date_obj = to_datetime(date_str, format='%d-%m-%Y')
        return date_obj.strftime('%d-%m-%Y')
    except:
        logger.warning(f"Could not parse date: {date_str}")
        return date_str

def company_matches_query(company_name: str, query: str) -> bool:
    """
    Check if a company name matches a search query using flexible matching.
    
    Args:
        company_name (str): The company name to check
        query (str): The search query to match against
        
    Returns:
        bool: True if the company matches the query
        
    Example:
        >>> company_matches_query("ING Bank Nederland", "ing")
        True
    """
    company = company_name.lower()
    search = query.lower()
    
    # Direct substring match
    if search in company or company in search:
        return True
    
    # Split into words and check for partial matches
    company_words = set(company.split())
    search_words = set(search.split())
    
    for sword in search_words:
        for cword in company_words:
            if sword in cword or cword in sword:
                return True
    
    return False

def get_sheets_service(credentials_file: str, scopes: list) -> object:
    """Initialize and return a Google Sheets service object."""
    try:
        creds = None
        token_path = 'token.pickle'

        # Check if we're running on Railway
        if os.getenv('RAILWAY_ENVIRONMENT'):
            logger.info("Running on Railway, using environment credentials")
            try:
                # Get credentials from environment
                creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
                if not creds_json:
                    raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not found")
                
                # Parse credentials
                creds_data = json.loads(creds_json)
                creds = Credentials.from_authorized_user_info(creds_data, scopes)
                
            except Exception as e:
                logger.error(f"Error loading Railway credentials: {str(e)}")
                raise
        else:
            logger.info("Running locally, using file credentials")
            # Local development flow
            if os.path.exists(token_path):
                with open(token_path, 'rb') as token:
                    creds = pickle.load(token)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes)
                    creds = flow.run_local_server(port=0)
                
                with open(token_path, 'wb') as token:
                    pickle.dump(creds, token)

        # Build and return service
        service = build('sheets', 'v4', credentials=creds)
        logger.info("Successfully created Sheets service")
        return service

    except Exception as e:
        logger.error(f"Error in get_sheets_service: {str(e)}")
        raise 