from __future__ import print_function
import os, time
from collections import defaultdict
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import re

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
# If you want permanent delete instead of Trash:
# SCOPES = ["https://mail.google.com/"]

def get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""

def normalize_sender(sender):
    """
    Converts:
      'John Smith <john@example.com>'
    into:
      'john@example.com'
    """
    match = re.search(r'<([^>]+)>', sender)
    if match:
        return match.group(1).lower()

    return sender.lower().strip()

def analyze_sender_sizes(service, query="", top_n=25):
    """
    Analyze mailbox usage by sender.

    query examples:
      ""
      "label:inbox"
      "older_than:2y"
      "has:attachment"
    """

    ids = collect_ids(service, query)

    sender_sizes = defaultdict(int)
    sender_counts = defaultdict(int)

    print(f"Analyzing {len(ids)} messages...")

    for index, msg_id in enumerate(ids, start=1):
        time.sleep(0.5) #throttle to avoid rate limits
        try:
            msg = get_message_with_retry(service, msg_id)

            if msg is None:
                continue

            size = msg.get("sizeEstimate", 0)

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            sender = get_header(headers, "From")
            sender = normalize_sender(sender)

            sender_sizes[sender] += size
            sender_counts[sender] += 1

            if index % 500 == 0:
                print(f"Processed {index} messages...")

        except Exception as e:
            print(f"Failed on message {msg_id}: {e}")

    ranking = sorted(
        sender_sizes.items(),
        key=lambda x: x[1],
        reverse=True
    )

    print("\n=== Top Senders by Storage Usage ===")
    print(
        f"{'Sender':50} {'Messages':>10} {'MB':>12}"
    )

    for sender, total_bytes in ranking[:top_n]:
        mb = total_bytes / (1024 * 1024)

        print(
            f"{sender[:50]:50} "
            f"{sender_counts[sender]:10d} "
            f"{mb:12.2f}"
        )

    return ranking

def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def collect_ids(service, query):
    ids = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=500,
            pageToken=page_token
        ).execute()

        if "messages" in resp:
            ids.extend([m["id"] for m in resp["messages"]])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return ids

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def delete_ids(service, ids, permanent=False):
    for batch in chunk(ids, 1000):
        if permanent:
            service.users().messages().batchDelete(
                userId="me",
                body={"ids": batch}
            ).execute()
        else:
            service.users().messages().batchModify(
                userId="me",
                body={"ids": batch, "addLabelIds": ["TRASH"]}
            ).execute()

def get_email_details(service, msg_id, full=False):
    fmt = "full" if full else "metadata"
    msg = service.users().messages().get(
        userId="me",
        id=msg_id,
        format=fmt
    ).execute()
    return msg

def get_message_with_retry(service, msg_id, retries=5):

    delay = 1

    for attempt in range(retries):

        try:
            return service.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From"]
            ).execute()

        except HttpError as e:

            if e.resp.status == 403 and "rateLimitExceeded" in str(e):
                print(
                    f"Rate limited. Sleeping {delay}s..."
                )

                time.sleep(delay)
                delay *= 2
            else:
                raise

    return None

def main():
    service = get_service()
    last_ids = []   # required initialization

    while True:
        print("\n=== Gmail Bulk Actions Menu ===")
        print("1. Enter a Gmail search query")
        print("2. Display first item from last query")
        print("3. Display last item from last query")
        print("4. Delete messages from last query")
        print("5. Add label to messages from last query")
        print("6. View email details by index")
        print("7. Analyze mailbox size by sender")
        print("8. Exit")

        choice = input("Select an option: ").strip()

        # Option 1: Run a new query
        if choice == "1":
            prompt = input("Enter your Gmail search query: ")
            query = "(" + prompt + ")"
            ids = collect_ids(service, query)
            print(f"Found {len(ids)} messages matching query: {query}")
            last_ids = ids

        # Option 2: First item
        elif choice == "2":
            try:
                print("First item:", last_ids[0])
            except:
                print("No results available. Run a query first.")

        # Option 3: Last item
        elif choice == "3":
            try:
                print("Last item:", last_ids[-1])
            except:
                print("No results available. Run a query first.")

        # Option 4: Delete
        elif choice == "4":
            try:
                confirm = input(f"Delete {len(last_ids)} messages? (y/n): ").lower()
                if confirm == "y":
                    delete_ids(service, last_ids, permanent=False)
                    print("Messages moved to Trash.")
                else:
                    print("Delete canceled.")
            except:
                print("No results available. Run a query first.")

        # Option 5: Add label
        elif choice == "5":
            try:
                label = input("Enter Gmail label ID to add: ").strip()
                body = {
                    "ids": last_ids,
                    "addLabelIds": [label],
                    "removeLabelIds": []
                }
                service.users().messages().batchModify(
                    userId="me",
                    body=body
                ).execute()
                print(f"Added label '{label}' to {len(last_ids)} messages.")
            except:
                print("No results available. Run a query first.")

        # Option 6: View email details by index
        elif choice == "6":
            try:
                index = int(input("Enter index of email in last_ids: "))
                msg_id = last_ids[index]

                full = input("Full message? (y/n): ").lower() == "y"
                fmt = "full" if full else "metadata"

                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format=fmt
                ).execute()

                print("\n=== Email Details ===")
                print("Message ID:", msg_id)
                print("Snippet:", msg.get("snippet", ""))
                print("Internal Date:", msg.get("internalDate", ""))
                print("Label IDs:", msg.get("labelIds", []))

                payload = msg.get("payload", {})
                headers = payload.get("headers", [])
                print("\nHeaders:")
                for h in headers:
                    print(f"{h['name']}: {h['value']}")

            except Exception as e:
                print("Error:", e)
                print("No results available or invalid index.")
        # Option 7: Analyze mailbox size by sender: 
        elif choice == "7":

            query = input(
                "Optional Gmail query filter (blank for all mail): "
            ).strip()

            analyze_sender_sizes(service, query)
        # Option 8: Exit
        elif choice == "8":
            print("Exiting Gmail Bulk Actions.")
            break

        else:
            print("Invalid selection. Try again.")

if __name__ == "__main__":
    main()