from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from src.sheets_agent import SheetsAgent
from src.config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID
import logging
from datetime import datetime
from prometheus_client import Counter, Histogram
import time
import io
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LSS Training API")

# Define allowed origins
ALLOWED_ORIGINS = [
    "https://trainingen.leansixsigmagroep.nl",
    "http://localhost:8501",  # Voor lokale Streamlit development
    "http://localhost:3000",  # Voor lokale React development
    "https://agenda:8890"     # Voor andere development URLs
]

# Update CORS middleware with specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Access-Control-Allow-Origin",
        "Access-Control-Allow-Methods",
        "Access-Control-Allow-Headers",
        "Access-Control-Allow-Credentials"
    ],
    expose_headers=["Content-Disposition"],
    max_age=3600,
)

# Initialize agent with error handling
try:
    logger.info("Initializing SheetsAgent...")
    agent = SheetsAgent(GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID)
    range_name = "'Inschrijvingen'!A1:Z50000"
    agent.load_sheet_data(range_name)
    logger.info("SheetsAgent initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize SheetsAgent: {str(e)}")
    agent = None

# Metrics
REQUEST_COUNT = Counter('api_requests_total', 'Total API requests', ['endpoint'])
REQUEST_LATENCY = Histogram('api_request_latency_seconds', 'Request latency')

@app.middleware("http")
async def add_metrics(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    REQUEST_COUNT.labels(endpoint=request.url.path).inc()
    REQUEST_LATENCY.observe(time.time() - start_time)
    return response

class Query(BaseModel):
    vraag: str

class ExportQuery(BaseModel):
    query: str

@app.get("/")
async def root():
    """Basic health check endpoint"""
    return {"status": "ok"}

@app.post("/vraag")
async def process_question(query: Query):
    """Process a question about the training data"""
    try:
        if agent is None:
            raise HTTPException(
                status_code=503,
                detail="SheetsAgent not initialized. Please try again later."
            )

        logger.info(f"Processing question: {query.vraag}")
        
        if not agent.training_data:
            logger.error("No training data loaded")
            raise HTTPException(
                status_code=500,
                detail="Training data not loaded. Please try again later."
            )
        
        response = agent.query_data(query.vraag)
        if not response:
            raise HTTPException(
                status_code=500,
                detail="Could not generate response. Please try again."
            )
        
        return {"antwoord": response}
        
    except Exception as e:
        logger.error(f"Error processing question: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing question: {str(e)}"
        )

@app.get("/ververs")
async def ververs_data():
    try:
        logger.info("Refreshing data...")
        agent.load_sheet_data("'Inschrijvingen'!A1:Z50000")
        return {"status": "Data ververst"}
    except Exception as e:
        logger.error(f"Error refreshing data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    if agent is None:
        raise HTTPException(status_code=503, detail="SheetsAgent not initialized")
    return {"status": "healthy"}

@app.get("/export")
@app.post("/export")
async def export_data(query: str = None, query_body: ExportQuery = None):
    """Export data to CSV based on query"""
    try:
        # Get query from either query parameter or body
        export_query = query or (query_body.query if query_body else None)
        if not export_query:
            raise HTTPException(status_code=400, detail="Query parameter is required")
            
        # Parse period and company from query
        period = agent._parse_query_period(export_query)
        company_filter = None
        
        # Simple company detection
        for company in agent.sheet_data['Bedrijf'].unique():
            if company.lower() in export_query.lower():
                company_filter = company
                break
        
        # Create CSV in memory
        output = io.StringIO()
        agent.export_to_csv(
            filename=output,
            period=period,
            company_filter=company_filter
        )
        
        # Reset buffer position
        output.seek(0)
        
        # Generate filename
        current_date = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"training_export_{current_date}.csv"
        
        # Return streaming response
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Access-Control-Expose-Headers': 'Content-Disposition'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) 