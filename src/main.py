from sheets_agent import SheetsAgent
from config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID
import os
import json
import warnings
import urllib3

# Suppress urllib3 warnings
warnings.filterwarnings('ignore', category=urllib3.exceptions.NotOpenSSLWarning)

def main():
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"Fout: Credentials bestand niet gevonden op {GOOGLE_CREDENTIALS_FILE}")
        return
        
    try:
        agent = SheetsAgent(GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID)
        range_name = "'Inschrijvingen'!A1:Z50000"
        agent.load_sheet_data(range_name)
        
        print("\n=== LSS Training Assistent ===")
        print("Type 'stop' om te stoppen")
        print("Voorbeeldvragen:")
        print("- Wat is de totale omzet van alle trainingen?")
        print("- Welke training heeft de meeste inschrijvingen?")
        print("- Toon de inschrijvingen van deze maand")
        
        while True:
            user_query = input("\nWat wil je weten over de trainingen? > ").strip()
            
            if user_query.lower() in ['stop', 'exit', 'q']:
                print("Tot ziens!")
                break
            
            if not user_query:
                continue
                
            try:
                response = agent.query_data(user_query)
                print("\nAntwoord:", response)
            except Exception as e:
                print(f"\nFout: {str(e)}")
        
    except Exception as e:
        print(f"\nFout: {str(e)}")

if __name__ == "__main__":
    main() 