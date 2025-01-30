from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import re

@dataclass
class Training:
    """Represents a single training registration"""
    datum_inschrijving: datetime
    training_naam: str
    omzet: float
    type: str
    bedrijf: str

    @classmethod
    def from_row(cls, row: pd.Series) -> 'Training':
        """Create Training instance from DataFrame row"""
        try:
            # Parse date with explicit format
            datum = pd.to_datetime(row['Datum Inschrijving'], format='%d-%m-%Y')
            
            # Clean omzet value
            omzet_str = str(row['Omzet'])
            omzet = float(omzet_str.replace('€', '').replace('.', '').replace(',', '.'))
            
            return cls(
                datum_inschrijving=datum,
                training_naam=row['Training'],
                omzet=omzet,
                type=row['Type'],
                bedrijf=row['Bedrijf']
            )
        except Exception as e:
            raise ValueError(f"Error parsing row: {str(e)}\nRow data: {row}")

@dataclass
class TrainingData:
    """Collection of training registrations with filtering capabilities"""
    trainingen: List[Training]

    @classmethod
    def from_sheet_data(cls, df: pd.DataFrame) -> 'TrainingData':
        """Create TrainingData from DataFrame"""
        trainingen = []
        errors = []
        
        for idx, row in df.iterrows():
            try:
                training = Training.from_row(row)
                trainingen.append(training)
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
        
        if errors:
            raise ValueError(f"Errors parsing data:\n" + "\n".join(errors))
            
        return cls(trainingen=trainingen)

    def filter_by_period(self, start_date: datetime, end_date: datetime) -> 'TrainingData':
        """Filter trainings by date range"""
        filtered = [
            t for t in self.trainingen 
            if start_date <= t.datum_inschrijving <= end_date
        ]
        return TrainingData(trainingen=filtered)

    def filter_by_type(self, type_query: str) -> 'TrainingData':
        """Filter trainings by type"""
        filtered = [
            t for t in self.trainingen 
            if type_query.lower() in t.type.lower()
        ]
        return TrainingData(trainingen=filtered)

    def filter_by_company(self, company_query: str) -> 'TrainingData':
        """Filter trainings by company"""
        filtered = [
            t for t in self.trainingen 
            if company_query.lower() in t.bedrijf.lower()
        ]
        return TrainingData(trainingen=filtered)

    def get_total_revenue(self) -> float:
        """Calculate total revenue"""
        return sum(t.omzet for t in self.trainingen)

    def get_revenue_by_type(self) -> Dict[str, float]:
        """Calculate revenue per type"""
        revenue_by_type = {}
        for t in self.trainingen:
            revenue_by_type[t.type] = revenue_by_type.get(t.type, 0) + t.omzet
        return revenue_by_type

    def to_dataframe(self) -> pd.DataFrame:
        """Convert back to DataFrame"""
        return pd.DataFrame([
            {
                'Datum Inschrijving': t.datum_inschrijving.strftime('%d-%m-%Y'),
                'Training': t.training_naam,
                'Omzet': f'€ {t.omzet:,.2f}',
                'Type': t.type,
                'Bedrijf': t.bedrijf
            }
            for t in self.trainingen
        ]) 