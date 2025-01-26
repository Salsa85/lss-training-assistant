from openai import OpenAI, OpenAIError
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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ONE_MINUTE = 60
MAX_REQUESTS_PER_MINUTE = 50  # Aanpassen aan je OpenAI limiet

class SheetsAgent:
    def __init__(self, credentials_file, spreadsheet_id):
        self.SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        
        # Initialize OpenAI
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        self.client = OpenAI()  # Laat OpenAI de key uit de environment halen
        
        self.sheet_service = self._get_sheets_service()
        self.sheet_data = None
        
    def _get_sheets_service(self):
        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
                
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
                
        return build('sheets', 'v4', credentials=creds)
    
    def load_sheet_data(self, range_name):
        """Load data from specified range in Google Sheet"""
        # Specify the exact columns we want
        result = self.sheet_service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, 
            range=range_name,
            valueRenderOption='FORMATTED_VALUE'
        ).execute()
        
        values = result.get('values', [])
        if not values:
            raise ValueError('No data found in sheet')
        
        # Get all data first
        df = pd.DataFrame(values[1:], columns=values[0])
        
        # Only keep the columns we need
        required_columns = ['Datum Inschrijving', 'Training', 'Omzet', 'Type']
        df = df[required_columns]
        
        # Clean up training names by removing dates
        df['Training'] = df['Training'].apply(lambda x: self._clean_training_name(str(x)))
        
        # Convert date column to datetime
        def standardize_date(date_str):
            try:
                if not isinstance(date_str, str):
                    date_str = str(date_str)
                date_obj = pd.to_datetime(date_str, format='%d-%m-%Y')
                return date_obj.strftime('%d-%m-%Y')
            except:
                return str(date_str)

        df['Datum Inschrijving'] = df['Datum Inschrijving'].apply(standardize_date)
        df['Datum Inschrijving'] = pd.to_datetime(
            df['Datum Inschrijving'], 
            format='%d-%m-%Y',
            errors='coerce'
        )
        
        # Convert Omzet column to numeric
        df['Omzet'] = df['Omzet'].astype(str).replace('[\€,]', '', regex=True).astype(float)
        
        self.sheet_data = df
        return self.sheet_data
    
    def _clean_training_name(self, training_name):
        """Remove dates and clean up training names"""
        # Remove dates in format dd/mm/yyyy or d/m/yyyy
        training_name = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}', '', training_name)
        
        # Remove dates in format dd-mm-yyyy or d-m-yyyy
        training_name = re.sub(r'\s+\d{1,2}-\d{1,2}-\d{4}', '', training_name)
        
        # Remove extra whitespace
        training_name = ' '.join(training_name.split())
        
        return training_name.strip()
    
    def get_training_summary(self):
        """Get summary of trainings, their dates, and values"""
        if self.sheet_data is None:
            raise ValueError('Sheet data not loaded. Call load_sheet_data first.')
        
        # Get current date and start of current month
        current_date = pd.Timestamp.now()
        current_month_start = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Filter data for current month
        current_month_data = self.sheet_data[
            self.sheet_data['Datum Inschrijving'].dt.to_period('M') == 
            current_date.to_period('M')
        ]
        
        summary = {
            'total_value': float(current_month_data['Omzet'].sum()),
            'trainings': {},
            'by_type': {},
            'period': f"1-{current_date.month}-{current_date.year} to {current_date.strftime('%d-%m-%Y')}"
        }
        
        # Group by training (for current month only)
        training_groups = current_month_data.groupby('Training')
        for training, group in training_groups:
            summary['trainings'][training] = {
                'total_registrations': len(group),
                'registration_date': group['Datum Inschrijving'].iloc[0].strftime('%d-%m-%Y'),
                'value': float(group['Omzet'].sum())  # Sum for the month
            }
        
        # Group by Type (for current month only)
        type_groups = current_month_data.groupby('Type')
        for type_name, group in type_groups:
            summary['by_type'][type_name] = {
                'total_revenue': float(group['Omzet'].sum()),
                'total_registrations': len(group)
            }
        
        return summary
    
    @sleep_and_retry
    @limits(calls=MAX_REQUESTS_PER_MINUTE, period=ONE_MINUTE)
    def query_data(self, user_query):
        """Query the sheet data using OpenAI with retry logic"""
        try:
            if self.sheet_data is None:
                raise ValueError('Geen data geladen. Roep eerst load_sheet_data aan.')
            
            # Get current date
            current_date = pd.Timestamp.now()
            
            # Get summary data
            summary = self.get_training_summary()
            
            # Create context with structured information
            context = f"Huidige Datum: {current_date.strftime('%d-%m-%Y')}\n"
            context += f"Getoonde periode: {summary['period']}\n\n"
            context += "Analyse van Inschrijvingen:\n\n"
            context += f"Totale Omzet deze Maand: €{summary['total_value']:,.2f}\n\n"
            
            # Add type-based revenue information
            context += "Omzet per Type (Deze Maand):\n"
            for type_name, data in summary['by_type'].items():
                context += f"\n{type_name}:\n"
                context += f"- Totale Omzet: €{data['total_revenue']:,.2f}\n"
                context += f"- Aantal Inschrijvingen: {data['total_registrations']}\n"
            
            context += "\nTraining Details (Deze Maand):\n"
            for training, data in summary['trainings'].items():
                context += f"\n{training}:\n"
                context += f"- Inschrijvingen: {data['total_registrations']}\n"
                context += f"- Inschrijfdatum: {data['registration_date']}\n"
                context += f"- Waarde: €{data['value']:,.2f}\n"
            
            # Create the prompt for OpenAI
            messages = [
                {
                    "role": "system", 
                    "content": (
                        f"Je bent een Nederlandse AI assistent die trainingsdata analyseert. "
                        f"Je spreekt alleen over deze data, en je praat niet over onrelevante dingen. "
                        f"De getoonde data is gefilterd voor de huidige maand. "
                        f"Hier is de samenvatting van alle beschikbare data:\n\n{context}\n"
                        f"Geef specifieke, data-gedreven antwoorden gebaseerd op deze informatie. "
                        f"Bij vragen over omzet, toon bij voorkeur de verdeling per Type. "
                        f"Bij het bespreken van datums, gebruik de huidige datum ({current_date.strftime('%d-%m-%Y')}) als referentie. "
                        f"Alle getoonde waardes zijn voor de huidige maand tenzij anders aangegeven. "
                        f"Gebruik het € symbool voor geldbedragen en gebruik punten voor duizendtallen. "
                        f"Geef je antwoord in het Nederlands."
                    )
                },
                {"role": "user", "content": user_query}
            ]
            
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=messages,
                temperature=0.1,
                max_tokens=500,
                timeout=30
            )
            
            return response.choices[0].message.content
            
        except OpenAIError as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise HTTPException(
                status_code=503,
                detail="Er is een probleem met de AI service. Probeer het later opnieuw."
            )
        except Exception as e:
            logger.error(f"Unexpected error in query_data: {str(e)}")
            raise 