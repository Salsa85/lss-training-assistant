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
        print("\nVoorbeeldvragen:")
        print("1. Periode-specifieke vragen:")
        print("   - Wat was de omzet in januari 2024?")
        print("   - Hoeveel trainingen zijn er verkocht in 2023?")
        print("   - Wat is de omzet van deze maand?")
        
        print("\n2. Type-specifieke vragen:")
        print("   - Hoeveel Green Belt trainingen zijn er verkocht in december?")
        print("   - Wat is de verdeling van training types dit jaar?")
        
        print("\n3. Vergelijkingen en trends:")
        print("   - Wat is het verschil in omzet tussen november en december 2024?")
        print("   - Hoe verhoudt de omzet van dit jaar zich tot vorig jaar?")
        print("   - Welk type training presteert het beste dit jaar?")
        
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