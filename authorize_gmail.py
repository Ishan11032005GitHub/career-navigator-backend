from google_auth_oauthlib.flow import InstalledAppFlow
import pickle

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def main():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES)
    creds = flow.run_local_server(port=8085)
    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)
    print("✅ Authorization complete — token saved as token.pickle")

if __name__ == '__main__':
    main()
