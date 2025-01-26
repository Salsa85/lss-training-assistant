import requests
import logging
from requests.exceptions import RequestException

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

def test_api():
    try:
        # Test root endpoint
        logger.info("Testing root endpoint...")
        response = requests.get(f"{BASE_URL}/")
        response.raise_for_status()
        print("Root endpoint response:", response.json())

        # Test ververs endpoint
        logger.info("Testing ververs endpoint...")
        response = requests.get(f"{BASE_URL}/ververs")
        response.raise_for_status()
        print("\nVervers response:", response.json())

        # Test vraag endpoint
        logger.info("Testing vraag endpoint...")
        vragen = [
            "Wat is de totale omzet deze maand?"
        ]
        
        for vraag in vragen:
            logger.info(f"Testing question: {vraag}")
            response = requests.post(
                f"{BASE_URL}/vraag",
                json={"vraag": vraag}
            )
            response.raise_for_status()
            print(f"\nVraag: {vraag}")
            print("Response:", response.json())

    except RequestException as e:
        logger.error(f"Network error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    test_api() 