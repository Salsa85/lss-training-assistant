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

# Verander deze imports
from src.tools import (
    clean_training_name, 
    clean_company_name, 
    standardize_date, 
    company_matches_query,
    get_sheets_service,
    ONE_MINUTE,
    MAX_REQUESTS_PER_MINUTE,
    logger
)
from src.data_models import Training, TrainingData
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
        
        # Add conversation history
        self.conversation_history = []
        self.max_history = 5  # Aantal vorige berichten om te onthouden
        
        # Update system prompt
        self.system_prompt = (
            "Je bent een Nederlandse AI assistent die trainingsdata analyseert. "
            "Je hebt toegang tot de conversatie geschiedenis en kunt daardoor verwijzen naar eerdere vragen en antwoorden. "
            "Je kunt de volgende soorten analyses uitvoeren:\n\n"
            
            "1. Omzet analyses:\n"
            "   - Totale omzet per periode (maand/kwartaal/jaar)\n"
            "   - Omzet per type training\n"
            "   - Vergelijkingen tussen periodes\n\n"
            
            "2. Training analyses:\n"
            "   - Aantal inschrijvingen per type training\n"
            "   - Overzicht van verkochte trainingen\n"
            "   - Verdeling tussen training types\n\n"
            
            "3. Periode analyses:\n"
            "   - Deze/vorige maand\n"
            "   - Specifieke maanden (bijv. 'januari 2024')\n"
            "   - Kwartalen (Q1-Q4)\n"
            "   - Jaren\n\n"
            
            "4. Trend analyses:\n"
            "   - Vergelijkingen met vorige periodes\n"
            "   - Groei percentages\n"
            "   - Populaire training types\n\n"
            
            "Voorbeeldvragen:\n"
            "- 'Wat is de omzet van vorige maand?'\n"
            "- 'Hoeveel trainingen zijn er verkocht in Q4 2023?'\n"
            "- 'Wat is de verdeling van training types dit jaar?'\n"
            "- 'Vergelijk de omzet van januari met december'\n\n"
            
            "Geef specifieke, data-gedreven antwoorden met waar mogelijk:\n"
            "- Exacte aantallen inschrijvingen\n"
            "- Omzet per type training\n"
            "- Percentages voor vergelijkingen\n"
            "- € symbool voor geldbedragen\n"
            "- Punten voor duizendtallen\n"
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
        try:
            query = query.lower()
            current_date = pd.Timestamp.now()
            
            # Check for specific month mentions
            months = {
                'januari': 1, 'februari': 2, 'maart': 3, 'april': 4, 'mei': 5, 'juni': 6,
                'juli': 7, 'augustus': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12
            }
            
            # Extract year
            year_match = re.search(r'20\d{2}', query)
            year = int(year_match.group()) if year_match else current_date.year
            
            # Check for month mentions
            for month_name, month_num in months.items():
                if month_name in query:
                    try:
                        # Create start and end dates for the month
                        start_date = pd.Timestamp(year=year, month=month_num, day=1)
                        end_date = start_date + pd.offsets.MonthEnd(1)
                        
                        # Validate month is not in future
                        if start_date > current_date:
                            raise ValueError(
                                f"Kan geen data tonen voor {month_name} {year} omdat deze periode in de toekomst ligt."
                            )
                        
                        logger.info(f"Using specific month period: {start_date} to {end_date}")
                        return start_date, end_date
                    except Exception as e:
                        logger.error(f"Error creating month dates: {str(e)}")
                        raise ValueError(f"Kon geen datums maken voor {month_name} {year}: {str(e)}")
            
            # Check for relative periods
            if 'deze maand' in query:
                start_date = pd.Timestamp(year=current_date.year, month=current_date.month, day=1)
                end_date = start_date + pd.offsets.MonthEnd(1)
                logger.info(f"Using current month period: {start_date} to {end_date}")
                return start_date, end_date
            
            if 'vorige maand' in query:
                last_month = current_date - pd.DateOffset(months=1)
                start_date = pd.Timestamp(year=last_month.year, month=last_month.month, day=1)
                end_date = start_date + pd.offsets.MonthEnd(1)
                logger.info(f"Using previous month period: {start_date} to {end_date}")
                return start_date, end_date
            
            # Check for quarter mentions
            quarters = {
                'q1': (1, 3),
                'eerste kwartaal': (1, 3),
                'q2': (4, 6),
                'tweede kwartaal': (4, 6),
                'q3': (7, 9),
                'derde kwartaal': (7, 9),
                'q4': (10, 12),
                'vierde kwartaal': (10, 12)
            }
            
            # Check for quarter in query
            for quarter_name, (start_month, end_month) in quarters.items():
                if quarter_name in query:
                    try:
                        # Create start and end dates for the quarter
                        start_date = pd.Timestamp(year=year, month=start_month, day=1)
                        end_date = pd.Timestamp(year=year, month=end_month, day=1) + pd.offsets.MonthEnd(1)
                        
                        # Validate quarter is not in future
                        if start_date > current_date:
                            raise ValueError(
                                f"Kan geen data tonen voor {quarter_name} {year} omdat deze periode in de toekomst ligt."
                            )
                        
                        logger.info(f"Parsed period: {quarter_name} {year} ({start_date} to {end_date})")
                        return start_date, end_date
                    except Exception as e:
                        logger.error(f"Error creating quarter dates: {str(e)}")
                        raise ValueError(f"Kon geen datums maken voor {quarter_name} {year}: {str(e)}")
            
            # Check for year mentions
            year_match = re.search(r'20\d{2}', query)
            year = int(year_match.group()) if year_match else None
            
            # Validate year is not in future
            if year and year > current_date.year:
                raise ValueError(f"Kan geen data tonen voor het jaar {year} omdat dit in de toekomst ligt.")
            
            # Check for year only queries
            if year and not any(month in query for month in months):
                return {
                    'type': 'year',
                    'year': year
                }
            
            # Default: return all time
            min_date = pd.Timestamp(year=2000, month=1, day=1)
            max_date = current_date
            logger.info(f"Using default period: all time ({min_date} to {max_date})")
            return min_date, max_date
            
        except Exception as e:
            logger.error(f"Error in _parse_query_period: {str(e)}")
            raise ValueError(f"Kon de periode niet bepalen: {str(e)}")

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
    def query_data(self, user_query: str) -> str:
        """Query the training data using OpenAI"""
        try:
            if not self.training_data:
                raise ValueError('Geen data geladen. Roep eerst load_sheet_data aan.')
            
            # Parse period from query
            try:
                period = self._parse_query_period(user_query.lower())
                start_date = period[0]
                end_date = period[1]
            except Exception as e:
                logger.error(f"Error parsing period: {str(e)}")
                raise ValueError(f"Kon de periode niet bepalen: {str(e)}")
            
            # Filter data if period specified
            try:
                filtered_data = (
                    self.training_data.filter_by_period(start_date, end_date)
                    if period else self.training_data
                )
            except Exception as e:
                logger.error(f"Error filtering data: {str(e)}")
                raise ValueError(f"Kon de data niet filteren: {str(e)}")
            
            # Create context with relevant statistics
            try:
                # Group by type for registration counts
                type_counts = {}
                type_revenue = {}
                for training in filtered_data.trainingen:
                    type_counts[training.type] = type_counts.get(training.type, 0) + 1
                    type_revenue[training.type] = type_revenue.get(training.type, 0) + training.omzet
                
                context = {
                    "totale_omzet": filtered_data.get_total_revenue(),
                    "totaal_aantal_inschrijvingen": len(filtered_data.trainingen),
                    "periode": f"{start_date.strftime('%d-%m-%Y')} tot {end_date.strftime('%d-%m-%Y')}",
                    "per_type": {
                        type_name: {
                            "aantal_inschrijvingen": count,
                            "omzet": revenue
                        }
                        for type_name, count, revenue in zip(
                            type_counts.keys(),
                            type_counts.values(),
                            type_revenue.values()
                        )
                    }
                }
                
                logger.info(f"Created context with {len(type_counts)} training types")
                
            except Exception as e:
                logger.error(f"Error creating context: {str(e)}")
                raise ValueError(f"Kon de context niet maken: {str(e)}")
            
            # Create messages array with system prompt and conversation history
            messages = [
                {"role": "system", "content": self.system_prompt}
            ]
            
            # Add conversation history
            messages.extend(self.conversation_history[-self.max_history:])
            
            # Add current query
            messages.append({"role": "user", "content": f"Context:\n{json.dumps(context, indent=2)}\n\nVraag: {user_query}"})
            
            # Get response from OpenAI
            response = self.client.chat.completions.create(
                model="gpt-4-0125-preview",
                messages=messages,
                temperature=0,
            )
            
            # Store the conversation
            self.conversation_history.append({"role": "user", "content": user_query})
            self.conversation_history.append({"role": "assistant", "content": response.choices[0].message.content})
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Unexpected error in query_data: {str(e)}")
            raise ValueError(f"Er is een fout opgetreden: {str(e)}")

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