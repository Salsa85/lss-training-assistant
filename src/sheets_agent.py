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
        self.credentials_file = credentials_file  # Nodig voor lokale ontwikkeling
        self.spreadsheet_id = spreadsheet_id
        
        # Initialize OpenAI (simplified)
        if not os.getenv('OPENAI_API_KEY'):
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        self.client = OpenAI()
        
        # Initialize Google Sheets service
        self.sheet_service = self._get_sheets_service()
        self.sheet_data = None
        
        # Add conversation history
        self.conversation_history = []
        self.max_history = 5  # Aantal berichten om te onthouden
        
    def _get_sheets_service(self):
        # For Railway deployment
        if os.getenv('RAILWAY_ENVIRONMENT'):
            creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
            if not creds_json:
                raise ValueError("GOOGLE_CREDENTIALS_JSON not found in environment")
            try:
                creds_dict = json.loads(creds_json)
                # Check if we have a refresh token
                if 'refresh_token' in creds_dict:
                    creds = Credentials.from_authorized_user_info(creds_dict, self.SCOPES)
                else:
                    # Fall back to client secrets
                    flow = InstalledAppFlow.from_client_config(creds_dict, self.SCOPES)
                    creds = flow.run_local_server(port=0)
            except Exception as e:
                logger.error(f"Error initializing credentials: {str(e)}")
                raise
        else:
            # For local development
            if not os.path.exists(self.credentials_file):
                raise ValueError(f"Credentials file not found at {self.credentials_file}")
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_file, self.SCOPES)
            creds = flow.run_local_server(port=0)
        
        return build('sheets', 'v4', credentials=creds)
    
    def load_sheet_data(self, range_name):
        """Load data from specified range in Google Sheet"""
        try:
            # Fetch data from Google Sheets
            result = self.sheet_service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, 
                range=range_name,
                valueRenderOption='FORMATTED_VALUE'
            ).execute()
            
            values = result.get('values', [])
            if not values:
                raise ValueError('No data found in sheet')
            
            # Create DataFrame
            df = pd.DataFrame(values[1:], columns=values[0])
            
            # Update required columns to include Bedrijf
            required_columns = ['Datum Inschrijving', 'Training', 'Omzet', 'Type', 'Bedrijf']
            df = df[required_columns]
            
            # Clean up training names
            df['Training'] = df['Training'].apply(lambda x: self._clean_training_name(str(x)))
            
            # Clean up company names
            df['Bedrijf'] = df['Bedrijf'].apply(lambda x: self._clean_company_name(str(x)))
            
            # Convert date strings to datetime
            df['Datum Inschrijving'] = pd.to_datetime(
                df['Datum Inschrijving'].apply(self._standardize_date), 
                format='%d-%m-%Y'
            )
            
            # Convert Omzet to float, removing € and . characters
            df['Omzet'] = df['Omzet'].replace('[\€\.]', '', regex=True).str.replace(',', '.').astype(float)
            
            # Sort by date
            df = df.sort_values('Datum Inschrijving')
            
            # Store the data
            self.sheet_data = df
            
            logger.info(f"Loaded {len(df)} rows of data from {df['Datum Inschrijving'].min()} to {df['Datum Inschrijving'].max()}")
            
            return self.sheet_data
            
        except Exception as e:
            logger.error(f"Error loading sheet data: {str(e)}")
            raise

    def _standardize_date(self, date_str):
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
    
    def _clean_training_name(self, training_name):
        """Remove dates and clean up training names"""
        # Remove dates in format dd/mm/yyyy or d/m/yyyy
        training_name = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}', '', training_name)
        
        # Remove dates in format dd-mm-yyyy or d-m-yyyy
        training_name = re.sub(r'\s+\d{1,2}-\d{1,2}-\d{4}', '', training_name)
        
        # Remove extra whitespace
        training_name = ' '.join(training_name.split())
        
        return training_name.strip()
    
    def _clean_company_name(self, company_name):
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

    def _company_matches_query(self, company_name, query):
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

    def _parse_query_period(self, query):
        """Parse the query to determine the period to analyze"""
        query = query.lower()
        current_date = pd.Timestamp.now()
        
        # Check for year mentions
        year_match = re.search(r'20\d{2}', query)
        year = int(year_match.group()) if year_match else None
        
        # Validate year is not in future
        if year and year > current_date.year:
            raise ValueError(f"Kan geen data tonen voor het jaar {year} omdat dit in de toekomst ligt.")
        
        # Check for specific month mentions
        months = {
            'januari': 1, 'februari': 2, 'maart': 3, 'april': 4, 'mei': 5, 'juni': 6,
            'juli': 7, 'augustus': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12
        }
        
        # Check for year only queries
        if year and not any(month in query for month in months):
            return {
                'type': 'year',
                'year': year
            }
        
        # Check for month + year combinations
        for month_name, month_num in months.items():
            if month_name in query:
                # Validate month/year combination is not in future
                if year:
                    future_date = pd.Timestamp(year=year, month=month_num, day=1)
                    if future_date > current_date:
                        raise ValueError(
                            f"Kan geen data tonen voor {month_name} {year} omdat deze periode in de toekomst ligt."
                        )
                return {
                    'type': 'specific_month',
                    'year': year if year else current_date.year,
                    'month': month_num
                }
        
        # Check for relative periods
        if 'vorige maand' in query:
            return {'type': 'previous_month'}
        elif 'deze maand' in query:
            return {'type': 'current_month'}
        elif 'dit jaar' in query:
            return {'type': 'current_year'}
        elif 'vorig jaar' in query:
            return {'type': 'previous_year'}
        
        return {'type': 'all_time'}

    def get_training_summary(self, period=None, company_filter=None):
        """Get summary of trainings, their dates, and values with optional company filter"""
        if self.sheet_data is None:
            raise ValueError('Sheet data not loaded. Call load_sheet_data first.')
        
        filtered_data = self.sheet_data.copy()
        
        if isinstance(period, dict):
            if period['type'] == 'specific_month':
                filtered_data = filtered_data[
                    (filtered_data['Datum Inschrijving'].dt.month == period['month']) &
                    (filtered_data['Datum Inschrijving'].dt.year == period['year'])
                ]
            elif period['type'] == 'year':
                filtered_data = filtered_data[
                    filtered_data['Datum Inschrijving'].dt.year == period['year']
                ]
            elif period['type'] == 'current_month':
                current_date = pd.Timestamp.now()
                filtered_data = filtered_data[
                    filtered_data['Datum Inschrijving'].dt.to_period('M') == 
                    current_date.to_period('M')
                ]
            elif period['type'] == 'previous_month':
                current_date = pd.Timestamp.now()
                previous_month = (current_date - pd.DateOffset(months=1))
                filtered_data = filtered_data[
                    filtered_data['Datum Inschrijving'].dt.to_period('M') == 
                    previous_month.to_period('M')
                ]
            elif period['type'] == 'current_year':
                current_year = pd.Timestamp.now().year
                filtered_data = filtered_data[
                    filtered_data['Datum Inschrijving'].dt.year == current_year
                ]
            elif period['type'] == 'previous_year':
                previous_year = pd.Timestamp.now().year - 1
                filtered_data = filtered_data[
                    filtered_data['Datum Inschrijving'].dt.year == previous_year
                ]
        
        if company_filter:
            # Filter data for matching companies
            filtered_data = filtered_data[
                filtered_data['Bedrijf'].apply(
                    lambda x: self._company_matches_query(x, company_filter)
                )
            ]
        
        # Calculate percentages and trends
        previous_period_data = self._get_previous_period_data(period)
        
        summary = {
            'total_value': float(filtered_data['Omzet'].sum()),
            'trainings': {},
            'by_type': {},
            'by_company': {},  # Add company summary
            'period': self._get_period_description(period),
            'trends': self._calculate_trends(filtered_data, previous_period_data)
        }
        
        # Group by training
        training_groups = filtered_data.groupby('Training')
        for training, group in training_groups:
            summary['trainings'][training] = {
                'total_registrations': len(group),
                'registration_date': group['Datum Inschrijving'].iloc[0].strftime('%d-%m-%Y'),
                'value': float(group['Omzet'].sum())
            }
        
        # Group by Type
        type_groups = filtered_data.groupby('Type')
        for type_name, group in type_groups:
            summary['by_type'][type_name] = {
                'total_revenue': float(group['Omzet'].sum()),
                'total_registrations': len(group)
            }
        
        # Group by Company
        company_groups = filtered_data.groupby('Bedrijf')
        for company, group in company_groups:
            summary['by_company'][company] = {
                'total_revenue': float(group['Omzet'].sum()),
                'total_registrations': len(group),
                'trainings': group['Training'].unique().tolist()
            }
        
        return summary

    def _get_period_description(self, period):
        """Get description for the selected period"""
        if isinstance(period, dict):
            if period['type'] == 'specific_month':
                months = ['januari', 'februari', 'maart', 'april', 'mei', 'juni',
                         'juli', 'augustus', 'september', 'oktober', 'november', 'december']
                month_name = months[period['month'] - 1]
                return f"{month_name} {period['year']}"
            elif period['type'] == 'current_month':
                current_date = pd.Timestamp.now()
                return f"1-{current_date.month}-{current_date.year} tot {current_date.strftime('%d-%m-%Y')}"
            elif period['type'] == 'previous_month':
                previous_month = (pd.Timestamp.now() - pd.DateOffset(months=1))
                return f"1-{previous_month.month}-{previous_month.year} tot {previous_month.strftime('%d-%m-%Y')}"
        return "Alle data"
    
    @sleep_and_retry
    @limits(calls=MAX_REQUESTS_PER_MINUTE, period=ONE_MINUTE)
    def query_data(self, user_query):
        """Query the sheet data using OpenAI with retry logic"""
        try:
            if self.sheet_data is None:
                raise ValueError('Geen data geladen. Roep eerst load_sheet_data aan.')
            
            # Parse period from query
            period = self._parse_query_period(user_query)
            
            # Get summary data for the specified period
            summary = self.get_training_summary(period)
            
            # Get current date
            current_date = pd.Timestamp.now()
            
            # Create context
            context = self._create_context(summary, current_date)
            
            # Create messages array with system prompt and conversation history
            messages = [
                {
                    "role": "system", 
                    "content": self._create_system_prompt(context, current_date)
                }
            ]
            
            # Add conversation history
            messages.extend(self.conversation_history[-self.max_history:])
            
            # Add current query
            messages.append({"role": "user", "content": user_query})
            
            # Get response from OpenAI
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=messages,
                temperature=0.1,
                max_tokens=500,
                timeout=30
            )
            
            # Store the conversation
            self.conversation_history.append({"role": "user", "content": user_query})
            self.conversation_history.append({"role": "assistant", "content": response.choices[0].message.content})
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Unexpected error in query_data: {str(e)}")
            raise 

    def _create_context(self, summary, current_date):
        """Create context string from summary data"""
        context = f"Huidige Datum: {current_date.strftime('%d-%m-%Y')}\n"
        context += f"Getoonde periode: {summary['period']}\n\n"
        context += "Analyse van Inschrijvingen:\n\n"
        
        # Totale omzet voor de periode
        context += f"Totale Omzet: €{summary['total_value']:,.2f}\n"
        
        # Voeg trend informatie toe
        if 'trends' in summary and summary['trends'].get('total_change_percentage', 0) != 0:
            context += f"Verschil met vorige periode: {summary['trends']['total_change_percentage']:.1f}%\n"
        
        # Omzet per type voor de periode
        context += "\nOmzet per Type:\n"
        for type_name, data in summary['by_type'].items():
            context += f"\n{type_name}:\n"
            context += f"- Totale Omzet: €{data['total_revenue']:,.2f}\n"
            context += f"- Aantal Inschrijvingen: {data['total_registrations']}\n"
            
            # Voeg trend informatie per type toe
            if 'trends' in summary and type_name in summary['trends']['by_type']:
                trend = summary['trends']['by_type'][type_name]
                if trend['previous_value'] > 0:
                    context += f"- Verschil met vorige periode: {trend['change_percentage']:.1f}%\n"
        
        # Training details
        context += "\nTraining Details:\n"
        for training, data in summary['trainings'].items():
            context += f"\n{training}:\n"
            context += f"- Inschrijvingen: {data['total_registrations']}\n"
            context += f"- Inschrijfdatum: {data['registration_date']}\n"
            context += f"- Waarde: €{data['value']:,.2f}\n"
        
        # Add company information
        context += "\nInschrijvingen per Bedrijf:\n"
        for company, data in summary['by_company'].items():
            context += f"\n{company}:\n"
            context += f"- Totale Omzet: €{data['total_revenue']:,.2f}\n"
            context += f"- Aantal Inschrijvingen: {data['total_registrations']}\n"
            context += f"- Trainingen: {', '.join(data['trainings'])}\n"
        
        return context
        
    def _create_system_prompt(self, context, current_date):
        """Create system prompt with context"""
        return (
            f"Je bent een Nederlandse AI assistent die trainingsdata analyseert. "
            f"Je kunt de volgende soorten analyses uitvoeren:\n"
            f"1. Omzet per maand of jaar\n"
            f"2. Vergelijkingen tussen periodes (percentages)\n"
            f"3. Overzichten van verkochte trainingen per type\n"
            f"4. Analyses per bedrijf (inschrijvingen en trainingen)\n"
            f"5. Trends en ontwikkelingen\n\n"
            f"De getoonde data bevat alle inschrijvingen. "
            f"Hier is de samenvatting van de gevraagde periode:\n\n{context}\n"
            f"Geef specifieke, data-gedreven antwoorden met waar mogelijk percentages en vergelijkingen. "
            f"Gebruik het € symbool voor geldbedragen en gebruik punten voor duizendtallen. "
            f"Als er om vergelijkingen wordt gevraagd, toon dan de verschillen in percentages. "
            f"Bij vragen over bedrijven, wees flexibel met bedrijfsnamen (bv. 'ING' matcht ook 'ING Bank'). "
            f"Geef je antwoord in het Nederlands."
        ) 

    def _calculate_trends(self, current_data, previous_data):
        """Calculate trends and percentages between periods"""
        current_total = float(current_data['Omzet'].sum())
        previous_total = float(previous_data['Omzet'].sum() if previous_data is not None else 0)
        
        trends = {
            'total_change_percentage': ((current_total - previous_total) / previous_total * 100) 
                if previous_total > 0 else 0,
            'by_type': {}
        }
        
        # Calculate changes per type
        current_by_type = current_data.groupby('Type')['Omzet'].sum()
        if previous_data is not None:
            previous_by_type = previous_data.groupby('Type')['Omzet'].sum()
            for type_name in current_by_type.index:
                current_value = float(current_by_type.get(type_name, 0))
                previous_value = float(previous_by_type.get(type_name, 0))
                trends['by_type'][type_name] = {
                    'current_value': current_value,
                    'previous_value': previous_value,
                    'change_percentage': ((current_value - previous_value) / previous_value * 100)
                        if previous_value > 0 else 0
                }
        
        return trends 

    def _get_previous_period_data(self, period):
        """Get data from the previous period for comparison"""
        if not isinstance(period, dict):
            return None
        
        previous_data = self.sheet_data.copy()
        
        if period['type'] == 'specific_month':
            # Get previous month's data
            if period['month'] == 1:
                prev_month = 12
                prev_year = period['year'] - 1
            else:
                prev_month = period['month'] - 1
                prev_year = period['year']
            
            previous_data = previous_data[
                (previous_data['Datum Inschrijving'].dt.month == prev_month) &
                (previous_data['Datum Inschrijving'].dt.year == prev_year)
            ]
        
        elif period['type'] == 'year':
            # Get previous year's data
            previous_data = previous_data[
                previous_data['Datum Inschrijving'].dt.year == period['year'] - 1
            ]
        
        elif period['type'] == 'current_month':
            # Get previous month's data
            current_date = pd.Timestamp.now()
            previous_month = (current_date - pd.DateOffset(months=1))
            previous_data = previous_data[
                previous_data['Datum Inschrijving'].dt.to_period('M') == 
                previous_month.to_period('M')
            ]
        
        elif period['type'] == 'current_year':
            # Get previous year's data
            current_year = pd.Timestamp.now().year
            previous_data = previous_data[
                previous_data['Datum Inschrijving'].dt.year == current_year - 1
            ]
        
        else:
            return None
        
        return previous_data if not previous_data.empty else None 