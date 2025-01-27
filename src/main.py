from sheets_agent import SheetsAgent
from config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID
import os
import json
import warnings
import urllib3
import sys
import time

# Suppress urllib3 warnings
warnings.filterwarnings('ignore', category=urllib3.exceptions.NotOpenSSLWarning)

def print_with_scroll(text):
    """Print text and auto-scroll"""
    print(text)
    sys.stdout.flush()
    time.sleep(0.1)  # Kleine vertraging voor leesbaarheid

def main():
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print_with_scroll(f"Fout: Credentials bestand niet gevonden op {GOOGLE_CREDENTIALS_FILE}")
        return
        
    try:
        agent = SheetsAgent(GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID)
        range_name = "'Inschrijvingen'!A1:Z50000"
        agent.load_sheet_data(range_name)
        
        print_with_scroll("\n=== LSS Training Assistent ===")
        print_with_scroll("Type 'stop' om te stoppen")
        print_with_scroll("\nVoorbeeldvragen:")
        print_with_scroll("1. Periode-specifieke vragen:")
        print_with_scroll("   - Wat was de omzet in januari 2024?")
        print_with_scroll("   - Hoeveel trainingen zijn er verkocht in 2023?")
        print_with_scroll("   - Wat is de omzet van deze maand?")
        
        print_with_scroll("\n2. Type-specifieke vragen:")
        print_with_scroll("   - Hoeveel Green Belt trainingen zijn er verkocht in december?")
        print_with_scroll("   - Wat is de verdeling van training types dit jaar?")
        
        print_with_scroll("\n3. Vergelijkingen en trends:")
        print_with_scroll("   - Wat is het verschil in omzet tussen november en december 2024?")
        print_with_scroll("   - Hoe verhoudt de omzet van dit jaar zich tot vorig jaar?")
        print_with_scroll("   - Welk type training presteert het beste dit jaar?")
        
        print_with_scroll("\n4. Bedrijfsspecifieke vragen:")
        print_with_scroll("   - Hoeveel trainingen heeft ING afgenomen?")
        print_with_scroll("   - Welke bedrijven hebben de meeste Green Belts?")
        print_with_scroll("   - Wat is de totale omzet van Rabobank dit jaar?")
        
        print_with_scroll("\n5. Export commando's:")
        print_with_scroll("   - Exporteer alle data naar CSV")
        print_with_scroll("   - Exporteer green belt trainingen van 2024")
        print_with_scroll("   - Exporteer trainingen van ING")
        
        while True:
            user_query = input("\nWat wil je weten over de trainingen? > ").strip()
            
            if user_query.lower() in ['stop', 'exit', 'q']:
                print_with_scroll("Tot ziens!")
                break
            
            # Check for export commands
            if user_query.lower().startswith('exporteer'):
                try:
                    # Parse period and company from query
                    period = agent._parse_query_period(user_query)
                    company_filter = None
                    
                    # Simple company detection (can be improved)
                    for company in agent.sheet_data['Bedrijf'].unique():
                        if company.lower() in user_query.lower():
                            company_filter = company
                            break
                    
                    # Export the data
                    filename = agent.export_to_csv(period=period, company_filter=company_filter)
                    print_with_scroll(f"\nData geëxporteerd naar: {filename}")
                    continue
                except Exception as e:
                    print_with_scroll(f"\nFout bij exporteren: {str(e)}")
                    continue
            
            if not user_query:
                continue
                
            try:
                response = agent.query_data(user_query)
                print_with_scroll("\nAntwoord:")
                print_with_scroll(response)
            except Exception as e:
                print_with_scroll(f"\nFout: {str(e)}")
        
    except Exception as e:
        print_with_scroll(f"\nFout: {str(e)}")

if __name__ == "__main__":
    main() 