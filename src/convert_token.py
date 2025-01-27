import pickle
import json

def convert_token_to_json():
    # Load the pickle file
    with open('token.pickle', 'rb') as token_file:
        creds = pickle.load(token_file)
    
    # Convert to dict
    creds_dict = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }
    
    # Save as JSON
    with open('credentials.json', 'w') as json_file:
        json.dump(creds_dict, json_file, indent=2)
    
    print("Credentials saved to credentials.json")
    print("\nCopy this JSON to Railway's GOOGLE_CREDENTIALS_JSON environment variable:")
    print(json.dumps(creds_dict, indent=2))

if __name__ == "__main__":
    convert_token_to_json() 