from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)

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
        try:
            logger.info(f"Filtering data between {start_date} and {end_date}")
            logger.info(f"Total trainings before filter: {len(self.trainingen)}")
            
            filtered = []
            for training in self.trainingen:
                if start_date <= training.datum_inschrijving <= end_date:
                    filtered.append(training)
            
            logger.info(f"Total trainings after filter: {len(filtered)}")
            
            if not filtered:
                logger.warning(f"No trainings found between {start_date} and {end_date}")
            
            return TrainingData(trainingen=filtered)
            
        except Exception as e:
            logger.error(f"Error filtering by period: {str(e)}")
            raise ValueError(f"Kon data niet filteren op periode: {str(e)}")

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
        try:
            total = sum(t.omzet for t in self.trainingen)
            logger.info(f"Calculated total revenue: {total}")
            return total
        except Exception as e:
            logger.error(f"Error calculating total revenue: {str(e)}")
            raise ValueError(f"Kon totale omzet niet berekenen: {str(e)}")

    def get_revenue_by_type(self) -> Dict[str, float]:
        """Calculate revenue per type"""
        try:
            revenue_by_type = {}
            for t in self.trainingen:
                revenue_by_type[t.type] = revenue_by_type.get(t.type, 0) + t.omzet
            
            logger.info(f"Calculated revenue by type: {revenue_by_type}")
            return revenue_by_type
        except Exception as e:
            logger.error(f"Error calculating revenue by type: {str(e)}")
            raise ValueError(f"Kon omzet per type niet berekenen: {str(e)}")

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