import streamlit as st
from sheets_agent import SheetsAgent
from config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID
import requests
import io

st.title("LSS Training Assistent")

# Initialize agent in session state
if 'agent' not in st.session_state:
    st.session_state.agent = SheetsAgent(GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID)
    st.session_state.agent.load_sheet_data("'Inschrijvingen'!A1:Z50000")

# Input veld
vraag = st.text_input("Wat wil je weten over de trainingen?")

# Ververs knop
if st.button("Ververs Data"):
    st.session_state.agent.load_sheet_data("'Inschrijvingen'!A1:Z50000")
    st.success("Data ververst!")

# Vraag verwerken
if vraag:
    try:
        antwoord = st.session_state.agent.query_data(vraag)
        st.write("Antwoord:", antwoord)
    except Exception as e:
        st.error(f"Fout: {str(e)}")

# Export knop
if st.button("Exporteer Data"):
    try:
        # Get current query from text input
        current_query = st.session_state.get('last_query', '')
        
        # Call export endpoint
        response = requests.post(
            "http://localhost:8000/export",
            json={"query": current_query},
            stream=True
        )
        
        if response.status_code == 200:
            # Get filename from headers
            content_disposition = response.headers.get('Content-Disposition', '')
            filename = content_disposition.split('filename=')[-1].strip('"')
            
            # Offer download
            st.download_button(
                label="Download CSV",
                data=response.content,
                file_name=filename,
                mime="text/csv"
            )
        else:
            st.error("Fout bij het exporteren van data")
            
    except Exception as e:
        st.error(f"Fout: {str(e)}") 