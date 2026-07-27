# GmailBulkActions
Utility to perform bulk actions using Gmail API to address Web UI limitations

Basic workflow if interested in building your own:

1. Creating a Google Cloud project
https://console.cloud.google.com

2. Enabling the Gmail API

3. Downloading credentials.json (OAuth

client secrets)

4. Running your Python script

5. Completing the browser OAuth flow

6. The script writes token.json automatically

Reauthentication may be required on subsequent runs in oath token expired.

Important nuance that I learned so you don't have to is that some compound queries must be enclosed in parentheses which is done in the script automatically. Example of query that I used: "unsubscribe label:unread larger:1K 
