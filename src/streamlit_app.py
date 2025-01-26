import streamlit as st
from sheets_agent import SheetsAgent
from config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID

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