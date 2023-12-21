from flask import Flask, request, jsonify
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.multipart import MIMEMultipart  # Add this line
from email.mime.text import MIMEText
import base64
import datetime
import os
import json
from flask_cors import CORS
import stripe


app = Flask(__name__)
# Enable CORS for all routes and origins

CORS(app)

# Google Calendar Functions
SCOPES_CALENDAR = ['https://www.googleapis.com/auth/calendar.events']
def get_calendar_service():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_1')
    if creds_json:
        creds_data = json.loads(creds_json)
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES_CALENDAR)
    #if os.path.exists('token1.json'):
    #    creds = Credentials.from_authorized_user_file('token1.json', SCOPES_CALENDAR)
    else:
        # Handle the error, e.g., credentials not found
        raise ValueError("Missing Google Calendar credentials")
    service = build('calendar', 'v3', credentials=creds)
    return service
def create_event(start_time_str, end_time_str, summary, description):
    service = get_calendar_service()
    start_time = datetime.datetime.fromisoformat(start_time_str)
    end_time = datetime.datetime.fromisoformat(end_time_str)
    event_result = service.events().insert(calendarId='primary',
        body={
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": 'UTC'},
            "end": {"dateTime": end_time.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": 'UTC'},
            "conferenceData": {
                "createRequest": {"requestId": f"some-random-string"}
            }
        },
        conferenceDataVersion=1
    ).execute()
    return event_result
# Gmail Functions
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail.send']
def gmail_authenticate():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        creds_data = json.loads(creds_json)
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES_GMAIL)
    #if os.path.exists('token.json'):
    #    creds = Credentials.from_authorized_user_file('token.json', SCOPES_GMAIL)
    else:
        # Handle the error, e.g., credentials not found
        raise ValueError("Missing Google Gmail credentials")
    return build('gmail', 'v1', credentials=creds)
def create_message(sender, to, subject, message_text):
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
def send_message(service, user_id, message):
    try:
        message = (service.users().messages().send(userId=user_id, body=message)
                   .execute())
        print('Message Id: %s' % message['id'])
        return message
    except Exception as e:
        print('An error occurred: %s' % e)
        return None
    
def send_email(service, user_id, subject, recipient, html_content):
    try:
        # Create a MIMEMultipart message
        message = MIMEMultipart('alternative')
        message['to'] = recipient
        message['from'] = user_id
        message['subject'] = subject

        # Attach both plain text and HTML parts
        part1 = MIMEText("This is an HTML email. Please use an email client that supports HTML to view it.", 'plain')
        part2 = MIMEText(html_content, 'html')
        message.attach(part1)
        message.attach(part2)

        # Encode and send the message
        raw_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        sent_message = service.users().messages().send(userId=user_id, body=raw_message).execute()
        return sent_message

    except Exception as e:
        print('An error occurred: %s' % e)
        return None

    
# Flask Routes
@app.route('/')
def index():
    return "Welcome to the Google Calendar and Gmail Integration!"

@app.route('/create_event', methods=['POST'])
def create_calendar_event():
    data = request.json
    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    summary = data.get('summary')
    description = data.get('description')
    if not all([start_time_str, end_time_str, summary, description]):
        return jsonify({'error': 'Missing data'}), 400
    try:
        event = create_event(start_time_str, end_time_str, summary, description)
        return jsonify({'message': 'Event created successfully', 'event_link': event.get('htmlLink'), 'meet_link': event.get('hangoutLink')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

# Set your secret key. Remember to switch to your live secret key in production.
# See your keys here: https://dashboard.stripe.com/account/apikeys
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        data = request.json
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': data.get('name'),  # Product name
                    },
                    'unit_amount': data.get('amount'),  # Price in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://intellex-academy.vercel.app/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://intellex-academy.vercel.app/cancel',
            metadata={
                'customer_email': data.get('customer_email'),  # Email of the current user
                'listing_email': data.get('listing_email')     # Email associated with the listing
            }
        )
        # Return relevant information from the session
        return jsonify({
            'id': checkout_session.id,
            'url': checkout_session.url,
            'amount_total': checkout_session.amount_total,
            'currency': checkout_session.currency
        })
    except Exception as e:
        print(e)  # Print the error to the server's log
        return jsonify({'error': str(e)}), 403
    
@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    # Your webhook secret (replace with your actual webhook secret)
    webhook_secret = os.getenv('STRIPE_SECRET_WEBHOOK')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        # Handle the event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            # Retrieve email addresses from session metadata
            customer_email = session.get('metadata', {}).get('customer_email', '')
            listing_email = session.get('metadata', {}).get('listing_email', '')

            amount = session.get('metadata', {}).get('amount', '')
            user_name = session.get('metadata', {}).get('user_name', '')
            mentor_name = session.get('metadata', {}).get('mentor_name', '')

            # Step 1: Create Calendar Event
            create_event_data = {
                'start_time': '2024-01-01T09:00:00', # Replace with actual data
                'end_time': '2024-01-01T10:00:00',   # Replace with actual data
                'summary': 'Payment Successful Event',
                'description': 'This event is created upon a successful payment.'
            }
            event = create_event(create_event_data['start_time'], create_event_data['end_time'], 
                         create_event_data['summary'], create_event_data['description'])
            
            calendar_link = event.get('htmlLink')
            
            # Step 2: Send Email Notification
            recipients = [email for email in [customer_email, listing_email] if email]
            if recipients:
                sender = 'your-email@example.com'  # Replace with your email
                subject = 'You have booked an Intellex Session'
                # Construct the path to the template
                template_path = os.path.join(os.path.dirname(__file__), 'template.html')
                service = gmail_authenticate()
                # Read HTML content from file
                with open(template_path, 'r') as file:
                    html_content = file.read()
                
                # Escape curly braces not used for placeholders
                html_content = html_content.replace('{', '{{').replace('}', '}}')

                # Unescape the actual placeholders
                html_content = html_content.replace('{{name}}', '{user_name}')
                html_content = html_content.replace('{{price}}', '{amount}')
                html_content = html_content.replace('{{hyperlink}}', '{hyperlink}')
                html_content = html_content.replace('{{mentor_name}}', '{mentor_name}')

                template_data = {
                    'user_name': user_name,  # From session metadata
                    'price': amount,  # From session metadata
                    'hyperlink': calendar_link,  # Google Calendar event link
                    'mentor_name': mentor_name  # Google Calendar event link
                    }
                
                html_content = html_content.format(**template_data)
                html_content = html_content.replace('{{', '{').replace('}}', '}')

            for recipient in recipients:
                # No need to pass template_path here
                send_email(service, "me", subject, recipient, html_content)

        return jsonify({'status': 'success'}), 200

    except ValueError as e:
        # Invalid payload
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return 'Invalid signature', 400
    except Exception as e:
        return str(e), 500
    

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # Default to 5000 if PORT not set
    app.run(host='0.0.0.0', port=port, debug=False)