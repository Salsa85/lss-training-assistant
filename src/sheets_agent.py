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
from .tools import (
    clean_training_name, 
    clean_company_name, 
    standardize_date, 
    company_matches_query,
    get_sheets_service,
    ONE_MINUTE,
    MAX_REQUESTS_PER_MINUTE,
    logger
)
from .data_models import Training, TrainingData
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SheetsAgent:
    def __init__(self, credentials_file, spreadsheet_id):
        self.SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        
        # Initialize OpenAI
        if not os.getenv('OPENAI_API_KEY'):
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        self.client = OpenAI()
        
        # Initialize Google Sheets service
        self.sheet_service = get_sheets_service(credentials_file, self.SCOPES)
        self.training_data: Optional[TrainingData] = None
        
        # Define system prompt
        self.system_prompt = (
            "Je bent een Nederlandse AI assistent die trainingsdata analyseert. "
            "Je kunt de volgende soorten analyses uitvoeren:\n"
            "1. Omzet per maand of jaar\n"
            "2. Vergelijkingen tussen periodes (percentages)\n"
            "3. Overzichten van verkochte trainingen per type\n"
            "4. Analyses per bedrijf (inschrijvingen en trainingen)\n"
            "5. Trends en ontwikkelingen\n\n"
            "Geef specifieke, data-gedreven antwoorden met waar mogelijk percentages en vergelijkingen. "
            "Gebruik het € symbool voor geldbedragen en gebruik punten voor duizendtallen. "
            "Als er om vergelijkingen wordt gevraagd, toon dan de verschillen in percentages. "
            "Bij vragen over bedrijven, wees flexibel met bedrijfsnamen (bv. 'ING' matcht ook 'ING Bank'). "
            "Geef je antwoord in het Nederlands."
        )
        
    def load_sheet_data(self, range_name):
        """Load data from specified range in Google Sheet"""
        try:
            result = self.sheet_service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            
            # Convert to DataFrame
            df = pd.DataFrame(
                result.get('values', [])[1:],  # Skip header row
                columns=result.get('values', [])[0]  # Use header row as columns
            )
            
            # Convert to TrainingData
            self.training_data = TrainingData.from_sheet_data(df)
            
            return True
            
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
        
        # Check for quarter mentions
        quarters = {
            'q1': [1, 2, 3],
            'eerste kwartaal': [1, 2, 3],
            'q2': [4, 5, 6],
            'tweede kwartaal': [4, 5, 6],
            'q3': [7, 8, 9],
            'derde kwartaal': [7, 8, 9],
            'q4': [10, 11, 12],
            'vierde kwartaal': [10, 11, 12]
        }
        
        # Extract year for quarter
        year_match = re.search(r'20\d{2}', query)
        year = int(year_match.group()) if year_match else current_date.year
        
        # Check for quarter in query
        for quarter_name, months in quarters.items():
            if quarter_name in query:
                return {
                    'type': 'quarter',
                    'year': year,
                    'months': months,
                    'quarter_name': quarter_name.upper() if quarter_name.startswith('q') else quarter_name
                }
        
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
        if self.training_data is None:
            raise ValueError('Sheet data not loaded. Call load_sheet_data first.')
        
        filtered_data = self.training_data.filter_by_period(period[0], period[1]) if period else self.training_data
        
        if company_filter:
            # Filter data for matching companies
            filtered_data = filtered_data.filter_by_company(company_filter)
        
        # Calculate percentages and trends
        previous_period_data = self._get_previous_period_data(period)
        
        summary = {
            'total_value': filtered_data.get_total_revenue(),
            'trainings': {},
            'by_type': {},
            'by_company': {},  # Add company summary
            'period': self._get_period_description(period),
            'trends': self._calculate_trends(filtered_data, previous_period_data)
        }
        
        # Group by training
        training_groups = filtered_data.trainingen
        for training in training_groups:
            summary['trainings'][training.training_naam] = {
                'total_registrations': 1,
                'registration_date': training.datum_inschrijving.strftime('%d-%m-%Y'),
                'value': training.omzet
            }
        
        # Group by Type
        type_groups = [t.type for t in training_groups]
        for type_name in type_groups:
            summary['by_type'][type_name] = {
                'total_revenue': sum(t.omzet for t in training_groups if t.type == type_name),
                'total_registrations': len([t for t in training_groups if t.type == type_name])
            }
        
        # Group by Company
        company_groups = [t.bedrijf for t in training_groups]
        for company in company_groups:
            summary['by_company'][company] = {
                'total_revenue': sum(t.omzet for t in training_groups if t.bedrijf.lower() == company.lower()),
                'total_registrations': len([t for t in training_groups if t.bedrijf.lower() == company.lower()]),
                'trainings': [t.training_naam for t in training_groups if t.bedrijf.lower() == company.lower()]
            }
        
        return summary

    def _get_period_description(self, period):
        """Get description for the selected period"""
        if isinstance(period, dict):
            if period['type'] == 'quarter':
                return f"{period['quarter_name']} {period['year']}"
            elif period['type'] == 'specific_month':
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
        """Query the training data using OpenAI"""
        try:
            if self.training_data is None:
                raise ValueError('Geen data geladen. Roep eerst load_sheet_data aan.')
            
            # Parse period from query
            period = self._parse_query_period(user_query)
            
            # Filter data if period specified
            filtered_data = (
                self.training_data.filter_by_period(period[0], period[1])
                if period else self.training_data
            )
            
            # Create context with relevant statistics
            context = {
                "totale_omzet": filtered_data.get_total_revenue(),
                "omzet_per_type": filtered_data.get_revenue_by_type(),
                "aantal_trainingen": len(filtered_data.trainingen),
                "periode": f"{period[0].strftime('%d-%m-%Y')} tot {period[1].strftime('%d-%m-%Y')}"
                if period else "alle data"
            }
            
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"Context:\n{json.dumps(context, indent=2)}\n\nVraag: {user_query}"}
            ]
            
            response = self.client.chat.completions.create(
                model="gpt-4-0125-preview",
                messages=messages,
                temperature=0,
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            raise Exception(f"Error querying OpenAI: {str(e)}")

    def _create_context(self, summary, current_date):
        """Create context string from summary data"""
        context = f"Huidige Datum: {current_date.strftime('%d-%m-%Y')}\n"
        context += f"Getoonde periode: {summary['period']}\n\n"
        context += "Analyse van Inschrijvingen:\n\n"
        
        # Totale omzet voor de periode
        context += f"Totale Omzet: €{summary['total_value']:,.2f}\n"
        context += f"Aantal Inschrijvingen: {sum(data['total_registrations'] for data in summary['by_type'].values())}\n\n"
        
        # Voeg trend informatie toe
        if 'trends' in summary and summary['trends'].get('total_change_percentage', 0) != 0:
            context += f"Verschil met vorige periode: {summary['trends']['total_change_percentage']:.1f}%\n\n"
        
        # Omzet per type voor de periode
        context += "Omzet per Type:\n"
        for type_name, data in summary['by_type'].items():
            context += f"\n{type_name}:\n"
            context += f"- Totale Omzet: €{data['total_revenue']:,.2f}\n"
            context += f"- Aantal Inschrijvingen: {data['total_registrations']}\n"
            
            # Voeg trend informatie per type toe
            if 'trends' in summary and type_name in summary['trends']['by_type']:
                trend = summary['trends']['by_type'][type_name]
                if trend['previous_value'] > 0:
                    context += f"- Verschil met vorige periode: {trend['change_percentage']:.1f}%\n"
        
        # Gedetailleerde inschrijvingen
        context += "\nGedetailleerde Inschrijvingen:\n"
        sorted_trainings = sorted(
            summary['trainings'].items(),
            key=lambda x: pd.to_datetime(x[1]['registration_date'], format='%d-%m-%Y')
        )
        for training, data in sorted_trainings:
            context += f"\n{training}:\n"
            context += f"- Inschrijfdatum: {data['registration_date']}\n"
            context += f"- Aantal: {data['total_registrations']}\n"
            context += f"- Omzet: €{data['value']:,.2f}\n"
        
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
            f"5. Trends en ontwikkelingen\n"
            f"6. Data exports naar CSV\n\n"
            f"De getoonde data bevat alle inschrijvingen. "
            f"Hier is de samenvatting van de gevraagde periode:\n\n{context}\n"
            f"Geef specifieke, data-gedreven antwoorden met waar mogelijk percentages en vergelijkingen. "
            f"Gebruik het € symbool voor geldbedragen en gebruik punten voor duizendtallen. "
            f"Als er om vergelijkingen wordt gevraagd, toon dan de verschillen in percentages. "
            f"Bij vragen over bedrijven, wees flexibel met bedrijfsnamen (bv. 'ING' matcht ook 'ING Bank'). "
            f"Bij export verzoeken, geef duidelijke download instructies. "
            f"Geef je antwoord in het Nederlands."
        ) 

    def _calculate_trends(self, current_data, previous_data):
        """Calculate trends and percentages between periods"""
        current_total = float(current_data.get_total_revenue())
        previous_total = float(previous_data.get_total_revenue() if previous_data is not None else 0)
        
        trends = {
            'total_change_percentage': ((current_total - previous_total) / previous_total * 100) 
                if previous_total > 0 else 0,
            'by_type': {}
        }
        
        # Calculate changes per type
        current_by_type = current_data.get_revenue_by_type()
        if previous_data is not None:
            previous_by_type = previous_data.get_revenue_by_type()
            for type_name in current_by_type.keys():
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
        
        previous_data = self.training_data.filter_by_period(period[0] - pd.DateOffset(years=1), period[0] - pd.DateOffset(days=1))
        
        return previous_data if not previous_data.trainingen.empty else None 

    def export_to_csv(self, filename=None, period=None, company_filter=None):
        """Export data to CSV with optional period and company filters"""
        try:
            if self.training_data is None:
                raise ValueError('Geen data geladen. Roep eerst load_sheet_data aan.')
            
            # Start with a copy of the data
            export_data = self.training_data.filter_by_period(period[0], period[1]) if period else self.training_data
            
            # Apply company filter if specified
            if company_filter:
                export_data = export_data.filter_by_company(company_filter)
            
            # Format data...
            
            # Handle both file and StringIO output
            if isinstance(filename, io.StringIO):
                # Write directly to StringIO
                export_data.to_dataframe().to_csv(
                    filename,
                    index=False,
                    sep=';',
                    encoding='utf-8-sig'
                )
                return filename
            else:
                # Generate default filename if none provided
                if filename is None:
                    current_date = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
                    filename = f'training_export_{current_date}.csv'
                
                # Ensure filename has .csv extension
                if not filename.endswith('.csv'):
                    filename += '.csv'
                
                # Export to file
                export_data.to_dataframe().to_csv(
                    filename,
                    index=False,
                    sep=';',
                    encoding='utf-8-sig'
                )
                return filename
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {str(e)}")
            raise 

    def _filter_data(self, data, filters):
        """Filter data based on multiple criteria"""
        filtered_data = data.copy()
        
        # Filter by year
        if 'year' in filters:
            filtered_data = filtered_data.filter_by_period(pd.Timestamp(year=filters['year'], month=1, day=1), pd.Timestamp(year=filters['year'], month=12, day=31))
        
        # Filter by month
        if 'month' in filters:
            filtered_data = filtered_data.filter_by_period(pd.Timestamp(year=pd.Timestamp.now().year, month=filters['month'], day=1), pd.Timestamp(year=pd.Timestamp.now().year, month=filters['month'], day=31))
        
        # Filter by training type
        if 'training_type' in filters:
            type_query = filters['training_type'].lower()
            filtered_data = filtered_data.filter_by_type(type_query)
        
        # Filter by specific training
        if 'training' in filters:
            training_query = filters['training'].lower()
            filtered_data = filtered_data.filter_by_training(training_query)
        
        return filtered_data

    def _parse_search_filters(self, query):
        """Parse query to extract search filters"""
        query = query.lower()
        filters = {}
        
        # Extract year
        year_match = re.search(r'20\d{2}', query)
        if year_match:
            filters['year'] = int(year_match.group())
        
        # Extract month
        months = {
            'januari': 1, 'februari': 2, 'maart': 3, 'april': 4,
            'mei': 5, 'juni': 6, 'juli': 7, 'augustus': 8,
            'september': 9, 'oktober': 10, 'november': 11, 'december': 12
        }
        for month_name, month_num in months.items():
            if month_name in query:
                filters['month'] = month_num
                break
        
        # Extract training types
        training_types = ['green belt', 'black belt', 'yellow belt', 'lean', 'six sigma']
        for training_type in training_types:
            if training_type in query:
                filters['training_type'] = training_type
                break
        
        # Handle relative periods
        if 'deze maand' in query:
            current_date = pd.Timestamp.now()
            filters['year'] = current_date.year
            filters['month'] = current_date.month
        elif 'vorige maand' in query:
            current_date = pd.Timestamp.now()
            previous_date = current_date - pd.DateOffset(months=1)
            filters['year'] = previous_date.year
            filters['month'] = previous_date.month
        elif 'dit jaar' in query:
            filters['year'] = pd.Timestamp.now().year
        elif 'vorig jaar' in query:
            filters['year'] = pd.Timestamp.now().year - 1
        
        return filters

    def _get_period_description_from_filters(self, filters):
        """Create period description from filters"""
        parts = []
        
        if 'month' in filters and 'year' in filters:
            months = ['januari', 'februari', 'maart', 'april', 'mei', 'juni',
                     'juli', 'augustus', 'september', 'oktober', 'november', 'december']
            parts.append(f"{months[filters['month']-1]} {filters['year']}")
        elif 'year' in filters:
            parts.append(str(filters['year']))
        
        if 'training_type' in filters:
            parts.append(filters['training_type'])
        
        if parts:
            return ' - '.join(parts)
        return "Alle data" 