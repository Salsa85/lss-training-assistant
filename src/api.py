from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .sheets_agent import SheetsAgent
from .config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID
import logging
from datetime import datetime
from prometheus_client import Counter, Histogram
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LSS Training API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In productie dit aanpassen naar specifieke origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    raise

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

@app.get("/")
async def root():
    """Basic health check endpoint"""
    return {"status": "ok"}

@app.post("/vraag")
async def stel_vraag(query: Query):
    try:
        logger.info(f"Processing question: {query.vraag}")
        response = agent.query_data(query.vraag)
        return {"antwoord": response}
    except Exception as e:
        logger.error(f"Error processing question: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    } 