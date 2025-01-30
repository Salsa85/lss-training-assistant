from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import pandas as pd
import re

@dataclass
class Training:
    datum_inschrijving: datetime
    training_naam: str
    training_datum: datetime
    omzet: float
    type: str
    voornaam: str
    achternaam: str
    bedrijf: str
    email: str
    
    @classmethod
    def from_sheet_row(cls, row):
        """Create Training object from sheet row"""
        # Extract training date from training name
        training_name = str(row['Training'])
        training_date_match = re.search(r'\d{2}/\d{2}/\d{4}', training_name)
        training_date = None
        if training_date_match:
            date_str = training_date_match.group(0)
            training_date = datetime.strptime(date_str, '%d/%m/%Y')
            training_name = training_name.replace(date_str, '').strip()
            
        return cls(
            datum_inschrijving=pd.to_datetime(row['Datum Inschrijving']),
            training_naam=training_name,
            training_datum=training_date,
            omzet=float(row['Omzet']),
            type=row['Type'],
            voornaam=row['Voornaam'],
            achternaam=row['Achternaam'],
            bedrijf=row['Bedrijf'],
            email=row['E-mailadres']
        )

@dataclass
class TrainingData:
    trainingen: List[Training]
    
    @classmethod
    def from_sheet_data(cls, df: pd.DataFrame):
        """Create TrainingData from sheet DataFrame"""
        trainingen = [Training.from_sheet_row(row) for _, row in df.iterrows()]
        return cls(trainingen=trainingen)
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert back to DataFrame if needed"""
        return pd.DataFrame([vars(t) for t in self.trainingen])
    
    def filter_by_period(self, start_date: datetime, end_date: datetime) -> 'TrainingData':
        """Filter trainingen by period"""
        filtered = [
            t for t in self.trainingen 
            if start_date <= t.datum_inschrijving <= end_date
        ]
        return TrainingData(trainingen=filtered)
    
    def filter_by_company(self, company: str) -> 'TrainingData':
        """Filter trainingen by company"""
        filtered = [
            t for t in self.trainingen 
            if company.lower() in t.bedrijf.lower()
        ]
        return TrainingData(trainingen=filtered)
    
    def get_total_revenue(self) -> float:
        """Calculate total revenue"""
        return sum(t.omzet for t in self.trainingen)
    
    def get_revenue_by_type(self) -> dict:
        """Get revenue grouped by training type"""
        revenue_by_type = {}
        for t in self.trainingen:
            revenue_by_type[t.type] = revenue_by_type.get(t.type, 0) + t.omzet
        return revenue_by_type 