import streamlit as st
import requests
import pandas as pd
import altair as alt
from requests.auth import HTTPBasicAuth
from datetime import datetime
import json
# --- 1. NEW IMPORT ---
from streamlit_autorefresh import st_autorefresh
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type, RetryError
import re # --- NEW --- (For search)

# --- START OF NEW SECTION (Gmail Imports) ---
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import timezone # <-- NEW for UTC
# --- END OF NEW SECTION ---

# --- 2. Page Configuration ---
st.set_page_config(
    page_title="TKTS Dashboard",
    page_icon="🎟️",
    layout="wide",
)

# --- 2b. NEW: Altair Global Theme ---
def set_altair_theme():
    """
    Sets a global Altair theme to use 'Manrope' font.
    """
    font = "Manrope"
    
    # Global theme settings
    alt.themes.register("my_theme", lambda: {
        "config": {
            "font": font,
            "title": {"font": font, "fontSize": 14}, # Chart titles
            "header": {"font": font, "labelFont": font}, # Headers
            "axis": {"font": font, "labelFont": font, "titleFont": font}, # All axis text
            "legend": {"font": font, "labelFont": font, "titleFont": font}, # Legend text
            "text": {"font": font}, # For text marks
        }
    })
    alt.themes.enable("my_theme")

# Apply the theme
set_altair_theme()


# --- 3. Authentication ---
try:
    JIRA_DOMAIN = st.secrets["JIRA_DOMAIN"]
    JIRA_USER_EMAIL = st.secrets["JIRA_USER_EMAIL"]
    JIRA_API_TOKEN = st.secrets["JIRA_API_TOKEN"]
    JIRA_AUTH = HTTPBasicAuth(JIRA_USER_EMAIL, JIRA_API_TOKEN)
except Exception:
    st.error("Secrets not configured. Please add JIRA_DOMAIN, JIRA_USER_EMAIL, and JIRA_API_TOKEN to your Streamlit secrets.")
    st.stop()


# --- 4. Helper Function for SLA Formatting ---
def format_time_remaining(time_diff):
    """Formats a timedelta into a human-readable SLA status."""
    if pd.isna(time_diff):
        return "N/A (No SLA)"

    if time_diff.total_seconds() < 0:
        ago = -time_diff
        days, rem = divmod(ago.total_seconds(), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        if days > 0:
            return f"🚨 Breached {int(days)}d {int(hours)}h ago"
        elif hours > 0:
            return f"🚨 Breached {int(hours)}h {int(minutes)}m ago"
        else:
            return f"🚨 Breached {int(minutes)}m ago"
    elif time_diff.total_seconds() < 8 * 3600:
        days, rem = divmod(time_diff.total_seconds(), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        return f"⚠️ {int(hours)}h {int(minutes)}m remaining"
    else:
        days, rem = divmod(time_diff.total_seconds(), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        return f"✅ {int(days)}d {int(hours)}h remaining"


# --- 5. Load Jira Data (Active Tickets) ---
@st.cache_data(ttl=300)
@retry(
    wait=wait_fixed(2),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(requests.RequestException)
)
def load_jira_data():
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    jql_query = """
        project = TKTS AND 
        issuetype in ("ANZ - Advanced Pixels", "ANZ - Audio Creatives", "ANZ - Bespoke Requests", "ANZ - Brand Lift Study Creatives", "ANZ - CTV and BVOD Creatives", "ANZ - Celtra Creatives", "ANZ - DCO Creatives", "ANZ - DOOH Creatives", "ANZ - Display Creatives", "ANZ - HTML5 Hosted Creatives", "ANZ - Native Creatives", "ANZ - Rejected Creatives", "ANZ - Social Boost Creatives", "ANZ - Standard Pixels", "ANZ - Troubleshooting - Creatives", "ANZ - Troubleshooting - Pixels", "ANZ - Video Creatives", "DE - Audio Creatives", "DE - Bespoke Requests", "DE - CTV Creatives", "DE - Celtra Creatives", "DE - Display Creatives", "DE - Native Creatives", "DE - Troubleshooting Creatives", "DE - Video Creatives", "IN - Audio Creatives", "IN - Bespoke Requests", "IN - Brand Lift Study Creatives", "IN - CTV/OTT Creatives", "IN - DCO Creatives", "IN - Display Creatives", "IN - Native Creatives", "IN - Troubleshooting Requests", "IN - Video Creatives", "Lenovo - Bespoke Request", "Lenovo - Display Creatives", "Lenovo - Trackers", "Lenovo - Troubleshooting", "Lenovo - Video Creatives", "MENA - Bespoke Requests", "MENA - Display Creatives", "MENA - Native Creatives", "MENA - Troubleshooting Creatives", "MENA - Video Creatives", "SEA - Audio Creatives", "SEA - Bespoke Requests", "SEA - Celtra Creatives", "SEA - DOOH Creatives", "SEA - Display Creatives", "SEA - Native Creatives", "SEA - Troubleshooting Creatives", "SEA - Video Creatives", "SEA - OMG/Assembly Creatives", "UK - Ad-Lib Creatives", "UK - Audio Creatives", "UK - Bespoke Requests", "UK - CTV Creatives", "UK - Celtra Creatives", "UK - Customer Match Creatives", "UK - Display Creatives", "UK - Native Creatives", "UK - Skin Creatives", "UK - Stories Creatives", "UK - THG - Creatives and Trackers", "UK - Troubleshooting Creatives", "UK - Video Creatives", "China - Bespoke Request", "China - Inbound", "MENA - Celtra Creatives", "IN - Customer Match Creatives", "ANZ - SeenThis Creatives - Self-serve only", "SEA - SeenThis Creatives - Self-serve only", "IN - SeenThis Creatives - Self-serve only", "UK - SeenThis Creatives - Self-serve only", "MENA - SeenThis Creatives - Self-serve only", "SEA - DCO Creatives", "MENA - CTV Creatives", "SEA - OTT Creatives") AND 
        status in ("In Progress", Open, Reopened, "Waiting for customer", "Waiting for support")
    """
    
    fields_to_request = ["status", "assignee", "created", "project", "issuetype", "customfield_10704", "customfield_10522", "customfield_16020"]

    payload = json.dumps({
        "jql": jql_query,
        "fields": fields_to_request,
        "maxResults": 1000
    })

    response = requests.post(url, headers=headers, data=payload, auth=JIRA_AUTH, timeout=10)
    response.raise_for_status()
    data = response.json()

    issues_list = []
    for issue in data.get('issues', []):
        request_type = "N/A"
        if issue['fields'].get('issuetype'):
            try:
                request_type = issue['fields']['issuetype']['name']
            except (KeyError, TypeError, AttributeError):
                request_type = "Other (See Jira)"
        
        breach_time = pd.NaT 
        sla_field = issue['fields'].get('customfield_10704') 
        
        if sla_field: 
            try:
                breach_time = sla_field['ongoingCycle']['breachTime']['iso8601']
            except (KeyError, TypeError, AttributeError, TypeError):
                try:
                    breach_time = sla_field['completedCycles'][-1]['breachTime']['iso8601']
                except (KeyError, TypeError, AttributeError, IndexError):
                    pass 
        
        issues_list.append({
            "key": issue['key'],
            "status": issue['fields']['status']['name'],
            "assignee": (issue['fields']['assignee']['displayName']
                         if issue['fields']['assignee'] else "Unassigned"),
            "created": issue['fields']['created'],
            "request_type": request_type, 
            "breach_time_api": breach_time,
            "campaign_start_main": issue['fields'].get("customfield_10522"),
            "campaign_start_china": issue['fields'].get("customfield_16020")
        })

    st.session_state['last_fetch_time'] = datetime.now()

    if not issues_list:
        return pd.DataFrame(columns=[
            "key", "status", "assignee", "created", "request_type", 
            "breach_time_api", "campaign_start_main", "campaign_start_china"
        ])

    df = pd.DataFrame(issues_list)
    df['created'] = pd.to_datetime(df['created'], utc=True)
    df['breach_time_api'] = pd.to_datetime(df['breach_time_api'], utc=True)
    df['campaign_start_main'] = pd.to_datetime(df['campaign_start_main'], utc=True, errors='coerce')
    df['campaign_start_china'] = pd.to_datetime(df['campaign_start_china'], utc=True, errors='coerce')
    df['campaign_start_date'] = df['campaign_start_china'].fillna(df['campaign_start_main'])
    
    return df


# --- 5b. Load All-Time Jira Data (30-day window) ---
@st.cache_data(ttl=300)
@retry(
    wait=wait_fixed(2), 
    stop=stop_after_attempt(3), 
    retry=retry_if_exception_type(requests.RequestException)
)
def load_all_jira_data():
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    # JQL now filtered for 30 days for speed and accuracy
    jql_query = """
        project = TKTS AND created >= -30d AND status IN (
            "Open",
            "In Progress",
            "Reopened",
            "Waiting for support",
            "Waiting for customer",
            "Campaign/request closed",
            "Resolved",
            "Closed"
        )
    """

    # --- UPDATED: Added assignee and issuetype ---
    fields_to_request = ["key", "status", "created", "resolutiondate", "assignee", "issuetype"]

    payload = json.dumps({
        "jql": jql_query,
        "fields": fields_to_request,
        "maxResults": 1000 
    })

    response = requests.post(url, headers=headers, data=payload, auth=JIRA_AUTH, timeout=15)
    response.raise_for_status()
    data = response.json()

    issues = []
    for issue in data.get("issues", []):
        fields = issue["fields"]
        
        # --- UPDATED: Parse new fields ---
        assignee_data = fields.get('assignee')
        assignee = assignee_data['displayName'] if assignee_data else "Unassigned"
        
        issuetype_data = fields.get('issuetype')
        request_type = issuetype_data['name'] if issuetype_data else "N/A"
        
        issues.append({
            "key": issue["key"],
            "created": fields["created"],
            "resolutiondate": fields.get("resolutiondate"),
            "status": fields["status"]["name"],
            "assignee": assignee,
            "request_type": request_type
        })
    
    if not issues:
        # --- UPDATED: Added new columns to empty dataframe ---
        return pd.DataFrame(columns=["key", "created", "resolutiondate", "status", "assignee", "request_type"])

    df = pd.DataFrame(issues)
    df["created"] = pd.to_datetime(df["created"], utc=True)
    df["resolutiondate"] = pd.to_datetime(df["resolutiondate"], utc=True, errors="coerce")
    return df

# --- 5c. NEW: Helper Function for Newly Assigned Tickets ---
@st.cache_data(ttl=300) # Match our refresh
@retry(
    wait=wait_fixed(2), 
    stop=stop_after_attempt(3), 
    retry=retry_if_exception_type(requests.RequestException)
)
def load_newly_assigned_tickets():
    """
    Fetches all tickets that had their assignee field CHANGED today.
    Returns a list of dicts: [{'key': 'TKTS-123', 'assignee': 'John Doe'}, ...]
    """
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    # This JQL finds tickets where the assignee field was modified today
    jql_query = """
        project = TKTS AND assignee CHANGED during (startOfDay(), now())
    """
    
    # --- UPDATED: Also fetch the ticket key ---
    fields_to_request = ["assignee", "key"] 

    payload = json.dumps({
        "jql": jql_query,
        "fields": fields_to_request,
        "maxResults": 1000
    })

    response = requests.post(url, headers=headers, data=payload, auth=JIRA_AUTH, timeout=15)
    response.raise_for_status()
    data = response.json()
    
    # --- UPDATED: Return a list of dictionaries ---
    assigned_tickets_list = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {})
        assignee_data = fields.get('assignee')
        assignee = assignee_data['displayName'] if assignee_data else "Unassigned"
        
        assigned_tickets_list.append({
            "key": issue.get("key"),
            "assignee": assignee
        })
    
    return assigned_tickets_list


# --- 5d. NEW: Helper Function for Ticket Lookup ---
@st.cache_data(ttl=60) # Short cache for individual ticket lookups
def get_ticket_details(ticket_key):
    """
    Fetches details for a single ticket from Jira.
    """
    # Smart logic: if just a number is passed, prefix it.
    if re.fullmatch(r'\d+', ticket_key):
        ticket_key = f"TKTS-{ticket_key}"
    
    # Check if it's a valid TKTS key format
    if not re.fullmatch(r'TKTS-\d+', ticket_key, re.IGNORECASE):
        raise ValueError(f"Invalid ticket format. Please use 'TKTS-1234' or just '1234'.")

    url = f"{JIRA_DOMAIN}/rest/api/3/issue/{ticket_key.upper()}"
    headers = {"Accept": "application/json"}
    
    # Request specific fields
    params = {
        "fields": "status,assignee,created,resolutiondate,issuetype"
    }

    response = requests.get(url, headers=headers, params=params, auth=JIRA_AUTH, timeout=10)
    
    # Handle "Not Found" specifically
    if response.status_code == 404:
        raise FileNotFoundError(f"Ticket '{ticket_key.upper()}' not found.")
    
    # Handle other errors
    response.raise_for_status()
    
    data = response.json()
    fields = data.get("fields", {})
    
    # --- Parse the data ---
    # Assignee
    assignee_data = fields.get('assignee')
    assignee = assignee_data['displayName'] if assignee_data else "Unassigned"
    
    # Status
    status_data = fields.get('status')
    status = status_data['name'] if status_data else "N/A"
    
    # Request Type
    issuetype_data = fields.get('issuetype')
    request_type = issuetype_data['name'] if issuetype_data else "N/A"
    
    # Dates
    created_date = pd.to_datetime(fields.get('created')).strftime('%d-%b-%Y %H:%M')
    resolved_date_raw = fields.get('resolutiondate')
    resolved_date = pd.to_datetime(resolved_date_raw).strftime('%d-%b-%Y %H:%M') if resolved_date_raw else "Not yet resolved"

    return {
        "Ticket ID": data['key'],
        "Link": f"{JIRA_DOMAIN}/browse/{data['key']}",
        "Status": status,
        "Assignee": assignee,
        "Request Type": request_type,
        "Created": created_date,
        "Resolved": resolved_date
    }

# --- START OF NEW SECTION (Gmail Functions) ---
# --- 5e. NEW: GMAIL - Authentication ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

@st.cache_resource
def get_gmail_service():
    """Builds and returns a Gmail API service object.
       Uses @st.cache_resource to only do this once.
    """
    creds = None
    # Check if the token is in Streamlit's secrets
    if 'GMAIL_TOKEN' in st.secrets:
        # Load credentials from the Streamlit secret
        creds_json = st.secrets['GMAIL_TOKEN']
        creds = Credentials.from_authorized_user_info(json.loads(creds_json), SCOPES)

    if not creds:
        # Don't stop the app, just return None. We'll handle this gracefully.
        print("Gmail token not found in Streamlit Secrets.")
        return None
    
    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except HttpError as error:
        print(f"An error occurred building the Gmail service: {error}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

# --- 5f. NEW: GMAIL - Priority Ticket Counter ---
@st.cache_data(ttl=300) # Refresh every 5 minutes
def get_priority_ticket_count(service, today_str):
    """
    Searches Gmail for priority tickets for the given day and returns a unique count.
    """
    if not service:
        return 0

    # --- UPDATED: Broader query (removed 'to:' and 'in:inbox', added 'Urgent') ---
    query = f'(adops-ea@miqdigital.com OR adops-emea@miqdigital.com) ("priority" OR "prioritise" OR "Urgent") after:{today_str}'
    
    try:
        # Search for messages
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return 0 # No priority emails today

        unique_ticket_ids = set()
        
        # Regex to find TKTS-#####
        ticket_regex = re.compile(r'TKTS-\d+', re.IGNORECASE)
        
        # We use a batch request to get all message snippets at once
        batch = service.new_batch_http_request()
        
        def add_tickets_to_set(request_id, response, exception):
            if exception is None:
                # Combine subject and snippet to search
                subject = ""
                snippet = response.get('snippet', '')
                headers = response.get('payload', {}).get('headers', [])
                for h in headers:
                    if h['name'].lower() == 'subject':
                        subject = h['value']
                        break
                
                # This searches both Subject and Body Snippet
                search_text = subject + " " + snippet
                
                # Find all "TKTS-XXXX" patterns
                found_tickets = ticket_regex.findall(search_text)
                if found_tickets:
                    for ticket in found_tickets:
                        unique_ticket_ids.add(ticket.upper())
            else:
                # Don't show an error, just log it to the Streamlit console
                print(f"Warning: Failed to get email part: {exception}")

        # Limit to 50 results to be safe and fast
        for message in messages[:50]: 
            batch.add(service.users().messages().get(userId='me', id=message['id'], format='metadata', metadataHeaders=['subject']), callback=add_tickets_to_set)
        
        batch.execute()

        return len(unique_ticket_ids)

    except HttpError as error:
        # Don't stop the app, just log the error and return 0
        print(f"An error occurred searching Gmail: {error}")
        return 0
    except Exception as e:
        print(f"An error occurred parsing Gmail messages: {e}")
        return 0
# --- END OF NEW SECTION ---


# --- 6. CSS (UPDATED FOR MANROPE FONT & ALL ICON FIXES) ---
st.markdown("""
<style>
/* --- NEW: Import Manrope from Google Fonts --- */
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@200;400;500;600&display=swap');
/* --- NEW: Import Material Icons Font --- */
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');

/* --- 1. GLOBAL FONT (Applied to body and all st- elements) --- */
html, body, [class*="st-"] {
    font-family: 'Manrope', Arial, sans-serif;
    font-weight: 200; /* Use ExtraLight as the default */
}

/* --- 2. HEADERS (st.header, st.subheader, custom HTML) --- */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Manrope', Arial, sans-serif !important;
}

/* --- 3. TABLE CONTENT (st.dataframe) --- */
/* This rule sets the font family for the table */
div[data-baseweb="data-table"] * {
    font-family: 'Manrope', Arial, sans-serif !important;
    font-weight: 400 !important; /* Force table text to be readable */
}

/* --- 4. NEW: CENTER HIGHLIGHTS SECTION --- */
/* This targets the columns only inside our new custom div */
.highlights-container [data-testid="stVerticalBlock"] {
    text-align: center; /* Center-aligns the h3 and the ul block */
}

/* This finds the <ul> lists that were centered by the rule above */
.highlights-container [data-testid="stVerticalBlock"] ul {
    text-align: left;      /* Aligns the text *inside* the list to the left */
    display: inline-block; /* Makes the left-aligned list block center-able */
}

/* --- 5. UPDATED: FIX ALL ICONS --- */

/* This rule targets elements with BOTH a Streamlit class AND the icon class */
div[data-testid="stExpander"] [class*="material-icons"] {
    font-family: 'Material Icons' !important;
    font-weight: 400 !important; /* Reset weight for the icon itself */
}

/* This fixes the dropdown arrow in all select boxes */
div[data-testid="stSelectbox"] [data-testid="stSvgIcon"] {
    font-family: 'Material Icons' !important; /* Use the correct font */
    font-weight: 400 !important; /* Reset weight for the icon */
    font-size: 24px !important; /* Ensure it's the right size */
}

/* This fixes the table icons */
div[data-baseweb="data-table"] span[class*="material-icons"] {
    font-family: 'Material Icons' !important;
    font-weight: 400 !important; /* Reset weight for the icon itself */
}
/* --- END ICON FIXES --- */


/* --- ADDED: Header CSS --- */
.header-container {
    padding: 2rem;
    background-image: url('https://i.ibb.co/nMTJF4B9/vj-HZbu8-Imgur.jpg');
    background-size: cover;
    background-position: center;
    margin-bottom: 1rem; /* Space below header */
    border-radius: 0px !important; /* Keep it sharp */
}
.header-text {
    color: white;
    text-align: center;
    font-size: 2.0rem; /* <-- Reduced font size */
    font-weight: 500;  /* Kept at 500 (Medium) for readability */
    font-family: 'Manrope', Arial, sans-serif;
}
/* --- End Header CSS --- */

/* --- FIX: This is the rule that makes the table full-width --- */
table {
    width: 100% !important;
}

/* Remove rounded corners from all containers, tabs, and blocks */
div[data-testid="stContainer"],
div[data-testid="stTabs"],
div[data-testid="stMarkdownContainer"],
div[data-testid="stHorizontalBlock"],
div[data-testid="stVerticalBlock"],
div[data-testid="stExpander"],
div[data-testid="stMetric"],
section.main div.block-container,
div[data-testid="stBorderedStContainer"],
div[data-testid="stDataFrame"],
div[data-baseweb="data-table"], /* <-- ✅ NEW: Targets inner dataframe */
div[data-testid="stAlert"] {      /* <-- ✅ NEW: Targets st.info/st.error */
    border-radius: 0px !important;
}

/* --- FIX: Make all standard buttons sharp-edged --- */
button[kind="primary"],
button[kind="secondary"],
div[data-testid="stButton"] > button,
button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primary"] {
    border-radius: 0px !important;
}

/* --- NEW: Make selectbox sharp --- */
div[data-testid="stSelectbox"] div[data-baseweb="select"] {
    border-radius: 0px !important;
}

/* Make tab headers flat */
button[role="tab"] {
    border-radius: 0px !important;
}

/* Tab border for clarity */
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 1px solid rgba(49, 51, 63, 0.2);
}

/* Center metric labels and values */
div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"] {
    display: flex;
    justify-content: center;
}

/* Center text globally if wrapped in <div style='text-align:center;'> */
.text-center {
    text-align: center !important;
}

/* Make markdown table headers bold and centered */
table th {
    text-align: center !important;
    font-weight: 600 !important; /* Kept at 600 (SemiBold) for readability */
}

</style>
""", unsafe_allow_html=True)

# --- 7. Header (Unchanged) ---
st.markdown(
    """
    <div class="header-container">
        <div class="header-text">TKTS Dashboard</div>
    </div>
    """,
    unsafe_allow_html=True
)


# --- 8. Load Data (UPDATED FOR GMAIL) ---
# Define default empty DataFrames
df = pd.DataFrame(columns=[
    "key", "status", "assignee", "created", "request_type", 
    "breach_time_api", "campaign_start_main", "campaign_start_china",
    "campaign_start_date" 
])
# --- UPDATED: Default df_all with new columns ---
df_all = pd.DataFrame(columns=["key", "created", "resolutiondate", "status", "assignee", "request_type"])

# --- Block 1: Load Active Tickets ---
try:
    df = load_jira_data()
    if df.empty:
        st.info("Data loaded. No active tickets found.")

except RetryError as e:
    last_exception = e.last_attempt.exception()
    error_details = f"Error: {last_exception}"
    if isinstance(last_exception, requests.HTTPError):
        response = last_exception.response
        error_details = (
            f"HTTP Error {response.status_code} ({response.reason}). "
            f"Check Secrets/Permissions. Response: {response.text[:200]}..."
        )
    st.error(f"Failed to fetch ACTIVE tickets: {error_details}", icon="🚨")
except Exception as e:
    st.error(f"Error loading ACTIVE tickets: {e}", icon="🚨")


# --- Block 2: Load All-Time Metrics ---
try:
    df_all = load_all_jira_data()
except RetryError as e:
    last_exception = e.last_attempt.exception()
    error_details = f"Error: {last_exception}"
    if isinstance(last_exception, requests.HTTPError):
        response = last_exception.response
        error_details = (
            f"HTTP Error {response.status_code} ({response.reason}). "
            f"Response: {response.text[:200]}..."
        )
    st.error(f"Failed to fetch DAILY metrics: {error_details}", icon="📉")
except Exception as e:
    st.error(f"Error loading DAILY metrics: {e}", icon="📉")

# --- START OF NEW SECTION (Gmail) ---
# --- Block 3: Load Priority Tickets ---
priority_count = 0 # Default value
gmail_service = get_gmail_service()
if gmail_service is None:
    # Show a visible warning on the app if the service failed to build
    st.warning("Could not connect to Gmail API. 'Priority TKTS' count will be 0. Check GMAIL_TOKEN secret.", icon="📧")
else:
    try:
        # Use UTC for a consistent "today"
        today_str = datetime.now(timezone.utc).strftime('%Y/%m/%d')
        priority_count = get_priority_ticket_count(gmail_service, today_str)
    except Exception as e:
        # Catch-all to ensure the app never crashes from Gmail
        st.warning(f"Could not fetch priority ticket count: {e}", icon="📧")
# --- END OF NEW SECTION ---


# --- Stop only if BOTH fail and we have no data at all ---
if df.empty and df_all.empty:
    st.error("All data sources failed to load. Please check secrets and JIRA connection.")
    st.stop()


# --- 9. Compute SLA & Daily Metrics ---
now = pd.Timestamp.now(tz='UTC')

df['breach_time'] = df['breach_time_api'] 
df['time_diff'] = df['breach_time'] - now

df['SLA Timer'] = df['time_diff'].apply(format_time_remaining)

def assign_sla_status(time_diff):
    if pd.isna(time_diff):
        return "⚪ N/A"
    if time_diff.total_seconds() < 0:
        return "🚨 Breached"
    return "✅ Within SLA"

df['SLA_Status'] = df['time_diff'].apply(assign_sla_status)

df['Ticket'] = df['key'] # Column for display
df['Ticket Link'] = df['key'].apply(lambda key: f"{JIRA_DOMAIN}/browse/{key}") # Column for URL

total_tickets = len(df)
breached_df = df[df['SLA_Status'] == '🚨 Breached']
within_sla_df = df[df['SLA_Status'] == '✅ Within SLA']
breached_count = len(breached_df)
within_sla_count = len(within_sla_df)

# --- NEW: Daily Metrics ---
today = pd.Timestamp.now(tz='UTC').date()

df_all["created_date"] = df_all["created"].dt.date
df_all["resolved_date"] = df_all["resolutiondate"].dt.date

created_today_count = len(df_all[df_all["created_date"] == today])
closed_today_count = len(df_all[df_all["resolved_date"] == today])
# --- End of New Metrics ---


# --- 10. Tabs Layout (UPDATED with new tab) ---
tab_dashboard, tab_explorer, tab_lookup = st.tabs(["SUMMARY", "EXPLORE", "TICKET LOOKUP"])

# --- THIS IS THE CORRECTED, FULL TAB_DASHBOARD BLOCK ---
with tab_dashboard:
    # --- UPDATED: Metrics Section with centered content ---
    with st.container(border=True):
        # --- UPDATED: Create 8 columns for 6 metrics ---
        _, col1, col2, col3, col4, col5, col6, _ = st.columns([1, 2, 2, 2, 2, 2, 2, 1])
        
        # --- UPDATED MARKDOWN: Wrapped in a single centered div ---
        col1.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:orange; margin-bottom:0px; padding-bottom:0px;'>{total_tickets}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Active</p>
        </div>
        """, unsafe_allow_html=True)
        
        col2.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:green; margin-bottom:0px; padding-bottom:0px;'>{within_sla_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Within SLA</p>
        </div>
        """, unsafe_allow_html=True)

        col3.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:red; margin-bottom:0px; padding-bottom:0px;'>{breached_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Breached</p>
        </div>
        """, unsafe_allow_html=True)

        col4.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:blue; margin-bottom:0px; padding-bottom:0px;'>{created_today_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Created Today</p>
        </div>
        """, unsafe_allow_html=True)

        col5.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:purple; margin-bottom:0px; padding-bottom:0px;'>{closed_today_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Closed Today</p>
        </div>
        """, unsafe_allow_html=True)
        
        # --- NEW: Priority Ticket Metric ---
        col6.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:#FFC300; margin-bottom:0px; padding-bottom:0px;'>{priority_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>Priority TKTS Today</p>
        </div>
        """, unsafe_allow_html=True)


    # --- Filter Buttons (Unchanged) ---
    st.markdown("### Real-Time TKTS Summary")
    col_b1, col_b2, col_b3, _ = st.columns([1, 1, 1, 3])

    all_type = "primary" if st.session_state.get('filter', 'All') == 'All' else "secondary"
    sla_type = "primary" if st.session_state.get('filter', 'All') == '✅ Within SLA' else "secondary"
    breached_type = "primary" if st.session_state.get('filter', 'All') == '🚨 Breached' else "secondary"

    if col_b1.button(f"All ({total_tickets})", use_container_width=True, type=all_type):
        st.session_state.filter = 'All'
        st.rerun()
    if col_b2.button(f"✅ Within SLA ({within_sla_count})", use_container_width=True, type=sla_type):
        st.session_state.filter = '✅ Within SLA'
        st.rerun()
    if col_b3.button(f"🚨 Breached ({breached_count})", use_container_width=True, type=breached_type):
        st.session_state.filter = '🚨 Breached'
        st.rerun()

    # Filter display
    if st.session_state.get('filter', 'All') == 'All':
        display_df = df
    elif st.session_state.get('filter', 'All') == '✅ Within SLA':
        display_df = within_sla_df
    else:
        display_df = breached_df

    # --- Use st.dataframe (Unchanged from last version) ---
    table_cols = ["Ticket", "Ticket Link", "SLA Timer", "status", "assignee", "request_type", "created", "campaign_start_date"]
    table_df = display_df[table_cols].copy()
    
    # Format dates
    table_df['created'] = table_df['created'].dt.strftime('%d%b%Y %H:%M')
    table_df['campaign_start_date'] = table_df['campaign_start_date'].dt.strftime('%d%b%Y')

    if table_df.empty:
        st.info("No tickets found for this filter.")
    else:
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ticket": st.column_config.TextColumn(
                    "TKTS",
                    help="Jira Ticket Key"
                ),
                "Ticket Link": st.column_config.LinkColumn(
                    "",
                    help="Click to open Jira ticket",
                    display_text="Open ↗"
                ),
                "SLA Timer": "SLA Status",
                "status": "Status",
                "assignee": "Assignee",
                "request_type": "Request Type",
                "created": "Created (UTC)",
                "campaign_start_date": st.column_config.TextColumn(
                    "Start Date",
                    help="Campaign Start Date (Main or China)"
                )
            }
        )

    # --- LAYOUT CHANGE: Today's Snapshot moved here ---
    st.divider()
    st.header(f"Today’s Highlights ({today.strftime('%d-%b-%Y')})")

    # --- NEW: Add a custom class wrapper ---
    st.markdown('<div class="highlights-container">', unsafe_allow_html=True)
    
    # --- THIS IS THE CORRECTED LAYOUT BLOCK ---
    with st.container(border=True):
        col_created, col_resolved = st.columns(2)

        # --- Column 1: Top 5 Created Request Types (NOW INDENTED) ---
        with col_created:
            st.subheader(f"Top 5 Requests type")
            
            # Filter df_all for tickets created today
            created_today_df = df_all[df_all["created_date"] == today]
            
            if created_today_df.empty:
                st.info("No tickets created so far today.")
            else:
                # --- NEW LOGIC ---
                # 1. Get ALL request type counts
                all_request_counts = created_today_df['request_type'].value_counts()
                
                # 2. Define the request type(s) to exclude
                exclude_request_types = ["China - Outbound"]
                
                # 3. Drop the excluded types. 'errors=ignore' prevents errors if it's not in the list
                filtered_request_counts = all_request_counts.drop(
                    labels=exclude_request_types, errors='ignore'
                )
                
                # 4. NOW get the top 5 from the filtered list
                top_5_requests = filtered_request_counts.head(5)
                # --- END NEW LOGIC ---

                # Check if the list is empty *after* filtering
                if top_5_requests.empty:
                    st.info("No tickets created today (after exclusions).")
                else:
                    # Build one string for a tight list (no change here)
                    request_list_items = []
                    for request, count in top_5_requests.items():
                        request_list_items.append(f"- **{request}:** {count} ticket(s)")
                    st.markdown("\n".join(request_list_items))


        # --- Column 2: Top 3 Assignees (REVERTED TO SIMPLE LIST) ---
        with col_resolved:
            st.subheader(f"Top 3 Assignees")
            
            try:
                # 1. Call the new function to get the list of dicts
                newly_assigned_list = load_newly_assigned_tickets()
                
                if not newly_assigned_list:
                    st.info("No tickets have been assigned so far today.")
                else:
                    # 2. Convert to DataFrame for easy counting
                    assigned_df = pd.DataFrame(newly_assigned_list)
                    
                    if assigned_df.empty:
                        # This check is good practice
                        st.info("No tickets have been assigned so far today.")
                    else:
                        new_ticket_counts = assigned_df['assignee'].value_counts()

                        # 3. Exclude the assignees
                        exclude_assignees = ["Adops-EA Group", "Ganesh Balasaheb Zaware"]
                        new_ticket_counts = new_ticket_counts.drop(labels=exclude_assignees, errors='ignore')
                        
                        if new_ticket_counts.empty:
                            st.info("No tickets assigned today (after exclusions).")
                        else:
                            # Sort by count and get the top 3
                            top_3_assignees = new_ticket_counts.sort_values(ascending=False).head(3)

                            # --- Simplified Display (Name and Count only) ---
                            assignee_list_items = []
                            for assignee, total_count in top_3_assignees.items():
                                assignee_list_items.append(f"- **{assignee}:** {int(total_count)} ticket(s)")
                            
                            st.markdown("\n".join(assignee_list_items))

            except Exception as e:
                st.error(f"Could not load assignee data: {e}")

    # --- NEW: Close the custom class wrapper ---
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.divider()
    
    # --- Ticket Breakdown Charts (Now after Snapshot) ---
    st.header("TKTS Overview")
    # --- UPDATED: New 3-column layout ---
    with st.container(border=True):
        
        # Only show charts if there are active tickets to plot
        if not df.empty:
            col_status, col_assignee, col_request = st.columns(3) 

            # --- UPDATED: Bar Chart for Status ---
            with col_status:
                st.subheader("TKTS/Status")
                source_status = df['status'].value_counts().reset_index()
                source_status.columns = ['status', 'Count']
                
                chart_status = alt.Chart(source_status).mark_bar(size=15).encode( # Added size=15
                    y=alt.Y('status:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300)), # Added labelLimit
                    x=alt.X('Count:Q', title='Count', axis=alt.Axis(format='d')), # Format X-axis as integer
                    tooltip=['status', 'Count']
                ).interactive()
                st.altair_chart(chart_status, use_container_width=True)

            # --- UPDATED: Bar Chart for Assignee ---
            with col_assignee:
                st.subheader("TKTS/Assignee")
                source = df['assignee'].value_counts().reset_index()
                source.columns = ['assignee', 'Count']
                
                chart = alt.Chart(source).mark_bar(size=15).encode( # Added size=15
                    y=alt.Y('assignee:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300)), # Added labelLimit
                    x=alt.X('Count:Q', title='Count', axis=alt.Axis(format='d')), # Format X-axis as integer
                    tooltip=['assignee', 'Count']
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            # --- UPDATED: Bar Chart for Request Type ---
            with col_request:
                st.subheader("TKTS/Request type")
                source_request_type = df['request_type'].value_counts().reset_index()
                source_request_type.columns = ['request_type', 'Count']
                
                chart_request_type = alt.Chart(source_request_type).mark_bar(size=15).encode( # Added size=1Readability */
}
/* --- End Header CSS --- */

/* --- FIX: This is the rule that makes the table full-width --- */
table {
    width: 100% !important;
}

/* Remove rounded corners from all containers, tabs, and blocks */
div[data-testid="stContainer"],
div[data-testid="stTabs"],
div[data-testid="stMarkdownContainer"],
div[data-testid="stHorizontalBlock"],
div[data-testid="stVerticalBlock"],
div[data-testid="stExpander"],
div[data-testid="stMetric"],
section.main div.block-container,
div[data-testid="stBorderedStContainer"],
div[data-testid="stDataFrame"],
div[data-baseweb="data-table"], /* <-- ✅ NEW: Targets inner dataframe */
div[data-testid="stAlert"] {      /* <-- ✅ NEW: Targets st.info/st.error */
    border-radius: 0px !important;
}

/* --- FIX: Make all standard buttons sharp-edged --- */
button[kind="primary"],
button[kind="secondary"],
div[data-testid="stButton"] > button,
button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primary"] {
    border-radius: 0px !important;
}

/* --- NEW: Make selectbox sharp --- */
div[data-testid="stSelectbox"] div[data-baseweb="select"] {
    border-radius: 0px !important;
}

/* Make tab headers flat */
button[role="tab"] {
    border-radius: 0px !important;
}

/* Tab border for clarity */
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 1px solid rgba(49, 51, 63, 0.2);
}

/* Center metric labels and values */
div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"] {
    display: flex;
    justify-content: center;
}

/* Center text globally if wrapped in <div style='text-align:center;'> */
.text-center {
    text-align: center !important;
}

/* Make markdown table headers bold and centered */
table th {
    text-align: center !important;
    font-weight: 600 !important; /* Kept at 600 (SemiBold) for readability */
}

</style>
""", unsafe_allow_html=True)

# --- 7. Header (Unchanged) ---
st.markdown(
    """
    <div class="header-container">
        <div class="header-text">TKTS Dashboard</div>
    </div>
    """,
    unsafe_allow_html=True
)


# --- 8. Load Data (UPDATED FOR GMAIL) ---
# Define default empty DataFrames
df = pd.DataFrame(columns=[
    "key", "status", "assignee", "created", "request_type", 
    "breach_time_api", "campaign_start_main", "campaign_start_china",
    "campaign_start_date" 
])
# --- UPDATED: Default df_all with new columns ---
df_all = pd.DataFrame(columns=["key", "created", "resolutiondate", "status", "assignee", "request_type"])

# --- Block 1: Load Active Tickets ---
try:
    df = load_jira_data()
    if df.empty:
        st.info("Data loaded. No active tickets found.")

except RetryError as e:
    last_exception = e.last_attempt.exception()
    error_details = f"Error: {last_exception}"
    if isinstance(last_exception, requests.HTTPError):
        response = last_exception.response
        error_details = (
            f"HTTP Error {response.status_code} ({response.reason}). "
            f"Check Secrets/Permissions. Response: {response.text[:200]}..."
        )
    st.error(f"Failed to fetch ACTIVE tickets: {error_details}", icon="🚨")
except Exception as e:
    st.error(f"Error loading ACTIVE tickets: {e}", icon="🚨")


# --- Block 2: Load All-Time Metrics ---
try:
    df_all = load_all_jira_data()
except RetryError as e:
    last_exception = e.last_attempt.exception()
    error_details = f"Error: {last_exception}"
    if isinstance(last_exception, requests.HTTPError):
        response = last_exception.response
        error_details = (
            f"HTTP Error {response.status_code} ({response.reason}). "
            f"Response: {response.text[:200]}..."
        )
    st.error(f"Failed to fetch DAILY metrics: {error_details}", icon="📉")
except Exception as e:
    st.error(f"Error loading DAILY metrics: {e}", icon="📉")

# --- START OF NEW SECTION (Gmail) ---
# --- Block 3: Load Priority Tickets ---
priority_count = 0 # Default value
gmail_service = get_gmail_service()
if gmail_service is None:
    # Show a visible warning on the app if the service failed to build
    st.warning("Could not connect to Gmail API. 'Priority TKTS' count will be 0. Check GMAIL_TOKEN secret.", icon="📧")
else:
    try:
        # Use UTC for a consistent "today"
        today_str = datetime.now(timezone.utc).strftime('%Y/%m/%d')
        priority_count = get_priority_ticket_count(gmail_service, today_str)
    except Exception as e:
        # Catch-all to ensure the app never crashes from Gmail
        st.warning(f"Could not fetch priority ticket count: {e}", icon="📧")
# --- END OF NEW SECTION ---


# --- Stop only if BOTH fail and we have no data at all ---
if df.empty and df_all.empty:
    st.error("All data sources failed to load. Please check secrets and JIRA connection.")
    st.stop()


# --- 9. Compute SLA & Daily Metrics ---
now = pd.Timestamp.now(tz='UTC')

df['breach_time'] = df['breach_time_api'] 
df['time_diff'] = df['breach_time'] - now

df['SLA Timer'] = df['time_diff'].apply(format_time_remaining)

def assign_sla_status(time_diff):
    if pd.isna(time_diff):
        return "⚪ N/A"
    if time_diff.total_seconds() < 0:
        return "🚨 Breached"
    return "✅ Within SLA"

df['SLA_Status'] = df['time_diff'].apply(assign_sla_status)

df['Ticket'] = df['key'] # Column for display
df['Ticket Link'] = df['key'].apply(lambda key: f"{JIRA_DOMAIN}/browse/{key}") # Column for URL

total_tickets = len(df)
breached_df = df[df['SLA_Status'] == '🚨 Breached']
within_sla_df = df[df['SLA_Status'] == '✅ Within SLA']
breached_count = len(breached_df)
within_sla_count = len(within_sla_df)

# --- NEW: Daily Metrics ---
today = pd.Timestamp.now(tz='UTC').date()

df_all["created_date"] = df_all["created"].dt.date
df_all["resolved_date"] = df_all["resolutiondate"].dt.date

created_today_count = len(df_all[df_all["created_date"] == today])
closed_today_count = len(df_all[df_all["resolved_date"] == today])
# --- End of New Metrics ---


# --- 10. Tabs Layout (UPDATED with new tab) ---
tab_dashboard, tab_explorer, tab_lookup = st.tabs(["SUMMARY", "EXPLORE", "TICKET LOOKUP"])

# --- THIS IS THE CORRECTED, FULL TAB_DASHBOARD BLOCK ---
with tab_dashboard:
    # --- UPDATED: Metrics Section with centered content ---
    with st.container(border=True):
        # --- UPDATED: Create 8 columns for 6 metrics ---
        _, col1, col2, col3, col4, col5, col6, _ = st.columns([1, 2, 2, 2, 2, 2, 2, 1])
        
        # --- UPDATED MARKDOWN: Wrapped in a single centered div ---
        col1.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:orange; margin-bottom:0px; padding-bottom:0px;'>{total_tickets}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Active</p>
        </div>
        """, unsafe_allow_html=True)
        
        col2.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:green; margin-bottom:0px; padding-bottom:0px;'>{within_sla_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Within SLA</p>
        </div>
        """, unsafe_allow_html=True)

        col3.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:red; margin-bottom:0px; padding-bottom:0px;'>{breached_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Breached</p>
        </div>
        """, unsafe_allow_html=True)

        col4.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:blue; margin-bottom:0px; padding-bottom:0px;'>{created_today_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Created Today</p>
        </div>
        """, unsafe_allow_html=True)

        col5.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:purple; margin-bottom:0px; padding-bottom:0px;'>{closed_today_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>TKTS Closed Today</p>
        </div>
        """, unsafe_allow_html=True)
        
        # --- NEW: Priority Ticket Metric ---
        col6.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:#FFC300; margin-bottom:0px; padding-bottom:0px;'>{priority_count}</h3>
            <p style='margin-top:0px; padding-top:0px;'>Priority TKTS Today</p>
        </div>
        """, unsafe_allow_html=True)


    # --- Filter Buttons (Unchanged) ---
    st.markdown("### Real-Time TKTS Summary")
    col_b1, col_b2, col_b3, _ = st.columns([1, 1, 1, 3])

    all_type = "primary" if st.session_state.get('filter', 'All') == 'All' else "secondary"
    sla_type = "primary" if st.session_state.get('filter', 'All') == '✅ Within SLA' else "secondary"
    breached_type = "primary" if st.session_state.get('filter', 'All') == '🚨 Breached' else "secondary"

    if col_b1.button(f"All ({total_tickets})", use_container_width=True, type=all_type):
        st.session_state.filter = 'All'
        st.rerun()
    if col_b2.button(f"✅ Within SLA ({within_sla_count})", use_container_width=True, type=sla_type):
        st.session_state.filter = '✅ Within SLA'
        st.rerun()
    if col_b3.button(f"🚨 Breached ({breached_count})", use_container_width=True, type=breached_type):
        st.session_state.filter = '🚨 Breached'
        st.rerun()

    # Filter display
    if st.session_state.get('filter', 'All') == 'All':
        display_df = df
    elif st.session_state.get('filter', 'All') == '✅ Within SLA':
        display_df = within_sla_df
    else:
        display_df = breached_df

    # --- Use st.dataframe (Unchanged from last version) ---
    table_cols = ["Ticket", "Ticket Link", "SLA Timer", "status", "assignee", "request_type", "created", "campaign_start_date"]
    table_df = display_df[table_cols].copy()
    
    # Format dates
    table_df['created'] = table_df['created'].dt.strftime('%d%b%Y %H:%M')
    table_df['campaign_start_date'] = table_df['campaign_start_date'].dt.strftime('%d%b%Y')

    if table_df.empty:
        st.info("No tickets found for this filter.")
    else:
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ticket": st.column_config.TextColumn(
                    "TKTS",
                    help="Jira Ticket Key"
                ),
                "Ticket Link": st.column_config.LinkColumn(
                    "",
                    help="Click to open Jira ticket",
                    display_text="Open ↗"
                ),
                "SLA Timer": "SLA Status",
                "status": "Status",
                "assignee": "Assignee",
                "request_type": "Request Type",
                "created": "Created (UTC)",
                "campaign_start_date": st.column_config.TextColumn(
                    "Start Date",
                    help="Campaign Start Date (Main or China)"
                )
            }
        )

    # --- LAYOUT CHANGE: Today's Snapshot moved here ---
    st.divider()
    st.header(f"Today’s Highlights ({today.strftime('%d-%b-%Y')})")

    # --- NEW: Add a custom class wrapper ---
    st.markdown('<div class="highlights-container">', unsafe_allow_html=True)
    
    # --- THIS IS THE CORRECTED LAYOUT BLOCK ---
    with st.container(border=True):
        col_created, col_resolved = st.columns(2)

        # --- Column 1: Top 5 Created Request Types (NOW INDENTED) ---
        with col_created:
            st.subheader(f"Top 5 Requests type")
            
            # Filter df_all for tickets created today
            created_today_df = df_all[df_all["created_date"] == today]
            
            if created_today_df.empty:
                st.info("No tickets created so far today.")
            else:
                # --- NEW LOGIC ---
                # 1. Get ALL request type counts
                all_request_counts = created_today_df['request_type'].value_counts()
                
                # 2. Define the request type(s) to exclude
                exclude_request_types = ["China - Outbound"]
                
                # 3. Drop the excluded types. 'errors=ignore' prevents errors if it's not in the list
                filtered_request_counts = all_request_counts.drop(
                    labels=exclude_request_types, errors='ignore'
                )
                
                # 4. NOW get the top 5 from the filtered list
                top_5_requests = filtered_request_counts.head(5)
                # --- END NEW LOGIC ---

                # Check if the list is empty *after* filtering
                if top_5_requests.empty:
                    st.info("No tickets created today (after exclusions).")
                else:
                    # Build one string for a tight list (no change here)
                    request_list_items = []
                    for request, count in top_5_requests.items():
                        request_list_items.append(f"- **{request}:** {count} ticket(s)")
                    st.markdown("\n".join(request_list_items))


        # --- Column 2: Top 3 Assignees (REVERTED TO SIMPLE LIST) ---
        with col_resolved:
            st.subheader(f"Top 3 Assignees")
            
            try:
                # 1. Call the new function to get the list of dicts
                newly_assigned_list = load_newly_assigned_tickets()
                
                if not newly_assigned_list:
                    st.info("No tickets have been assigned so far today.")
                else:
                    # 2. Convert to DataFrame for easy counting
                    assigned_df = pd.DataFrame(newly_assigned_list)
                    
                    if assigned_df.empty:
                        # This check is good practice
                        st.info("No tickets have been assigned so far today.")
                    else:
                        new_ticket_counts = assigned_df['assignee'].value_counts()

                        # 3. Exclude the assignees
                        exclude_assignees = ["Adops-EA Group", "Ganesh Balasaheb Zaware"]
                        new_ticket_counts = new_ticket_counts.drop(labels=exclude_assignees, errors='ignore')
                        
                        if new_ticket_counts.empty:
                            st.info("No tickets assigned today (after exclusions).")
                        else:
                            # Sort by count and get the top 3
                            top_3_assignees = new_ticket_counts.sort_values(ascending=False).head(3)

                            # --- Simplified Display (Name and Count only) ---
                            assignee_list_items = []
                            for assignee, total_count in top_3_assignees.items():
                                assignee_list_items.append(f"- **{assignee}:** {int(total_count)} ticket(s)")
                            
                            st.markdown("\n".join(assignee_list_items))

            except Exception as e:
                st.error(f"Could not load assignee data: {e}")

    # --- NEW: Close the custom class wrapper ---
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.divider()
    
    # --- Ticket Breakdown Charts (Now after Snapshot) ---
    st.header("TKTS Overview")
    # --- UPDATED: New 3-column layout ---
    with st.container(border=True):
        
        # Only show charts if there are active tickets to plot
        if not df.empty:
            col_status, col_assignee, col_request = st.columns(3) 

            # --- UPDATED: Bar Chart for Status ---
            with col_status:
                st.subheader("TKTS/Status")
                source_status = df['status'].value_counts().reset_index()
                source_status.columns = ['status', 'Count']
                
                chart_status = alt.Chart(source_status).mark_bar(size=15).encode( # Added size=15
                    y=alt.Y('status:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300)), # Added labelLimit
                    x=alt.X('Count:Q', title='Count', axis=alt.Axis(format='d')), # Format X-axis as integer
                    tooltip=['status', 'Count']
                ).interactive()
                st.altair_chart(chart_status, use_container_width=True)

            # --- UPDATED: Bar Chart for Assignee ---
            with col_assignee:
                st.subheader("TKTS/Assignee")
                source = df['assignee'].value_counts().reset_index()
                source.columns = ['assignee', 'Count']
                
                chart = alt.Chart(source).mark_bar(size=15).encode( # Added size=15
                    y=alt.Y('assignee:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300)), # Added labelLimit
                    x=alt.X('Count:Q', title='Count', axis=alt.Axis(format='d')), # Format X-axis as integer
                    tooltip=['assignee', 'Count']
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            # --- UPDATED: Bar Chart for Request Type ---
            with col_request:
                st.subheader("TKTS/Request type")
                source_request_type = df['request_type'].value_counts().reset_index()
                source_request_type.columns = ['request_type', 'Count']
                
                chart_request_type = alt.Chart(source_request_type).mark_bar(size=15).encode( # Added size=15
                    y=alt.Y('request_type:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300)), # Added labelLimit
                    x=alt.X('Count:Q', title='Count', axis=alt.Axis(format='d')), # Format X-axis as integer
                    tooltip=['request_type', 'Count']
                ).interactive()
                
                st.altair_chart(chart_request_type, use_container_width=True)
        else:
            st.info("No active tickets to display in charts.")

# --- END OF TAB_DASHBOARD BLOCK ---


# --- === MODIFIED tab_explorer (Using User's New Idea) === ---
with tab_explorer:
    
    # --- Section 1: Existing Active Ticket Explorer ---
    st.header("Active Ticket Explorer")
    with st.container(border=True):
        # Check if df is empty before trying to access 'assignee'
        if not df.empty:
            assignee_list = sorted(df['assignee'].unique())
            
            selected_assignee = st.selectbox(
                "Select an assignee to view their ACTIVE tickets:", 
                assignee_list, 
                key="assignee_select",
                label_visibility="collapsed"
            )
            
            if selected_assignee:
                assignee_df = df[df['assignee'] == selected_assignee].sort_values(by='created')
                
                table_cols_assignee = ["Ticket", "Ticket Link", "SLA Timer", "status", "request_type", "created", "campaign_start_date"]
                table_df_assignee = assignee_df[table_cols_assignee].copy()
                
                # Format dates
                table_df_assignee['created'] = table_df_assignee['created'].dt.strftime('%d%b%Y %H:%M')
                table_df_assignee['campaign_start_date'] = table_df_assignee['campaign_start_date'].dt.strftime('%d%b%Y')

                st.dataframe(
                    table_df_assignee,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Ticket": st.column_config.TextColumn("TKTS", help="Jira Ticket Key"),
                        "Ticket Link": st.column_config.LinkColumn("", help="Click to open Jira ticket", display_text="Open ↗"),
                        "SLA Timer": "SLA Status",
                        "status": "Status",
                        "assignee": "Assignee",
                        "request_type": "Request Type",
                        "created": "Created (UTC)",
                        "campaign_start_date": st.column_config.TextColumn("Start Date", help="Campaign Start Date (Main or China)")
                    }
                )
        else:
            st.info("No active tickets to explore.")
            
    st.divider()

    # --- Section 2: NEW Daily Closed Ticket Report (Using User's Idea) ---
    st.header(f"Today's Closed Tickets ({today.strftime('%d-%b-%Y')})")
    st.caption("This report uses the 30-day data cache and refreshes every 5 minutes.")
    
    with st.container(border=True):
        if df_all.empty:
            st.info("No 30-day ticket data available to build a report.")
        else:
            # 1. Filter df_all for today's date
            daily_closed_df = df_all[df_all["resolved_date"] == today]
            
            # 2. Exclude assignees
            exclude_assignees = ["Adops-EA Group", "Ganesh Balasaheb Zaware"]
            filtered_df = daily_closed_df[~daily_closed_df['assignee'].isin(exclude_assignees)]

            if filtered_df.empty:
                st.info(f"No tickets were closed today (after exclusions).")
            else:
                # 3. Get the list of assignees who closed tickets
                assignee_list = sorted(filtered_df['assignee'].unique())
                
                # 4. Create the selectbox
                selected_assignee_report = st.selectbox(
                    "Select an assignee to view their closed tickets:",
                    assignee_list,
                    key="closed_assignee_select",
                    label_visibility="collapsed"
                )
                
                if selected_assignee_report:
                    # 5. Filter for the selected assignee
                    report_df = filtered_df[filtered_df['assignee'] == selected_assignee_report].copy()
                    
                    st.metric(
                        label=f"Tickets Closed by {selected_assignee_report}",
                        value=len(report_df)
                    )
                    
                    # 6. Display their tickets in a dataframe
                    report_df['Ticket Link'] = report_df['key'].apply(lambda key: f"{JIRA_DOMAIN}/browse/{key}")
                    display_cols = ['key', 'request_type', 'Ticket Link']
                    
                    st.dataframe(
                        report_df[display_cols],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "key": "Ticket ID",
                            "request_type": "Request Type",
                            "Ticket Link": st.column_config.LinkColumn(
                                "",
                                help="Click to open Jira ticket",
                                display_text="Open ↗"
                            )
                        }
                    )


# --- NEW: Ticket Lookup Tab ---
with tab_lookup:
    search_query = st.text_input(
        "Enter Ticket ID (e.g., 'TKTS-1234' or just '1234')", 
        key="ticket_search_input"
    )
    
    if st.button("Search", key="search_button", type="primary", use_container_width=True):
        if not search_query.strip():
            st.warning("Please enter a ticket ID to search.")
        else:
            with st.spinner(f"Searching for '{search_query}'..."):
                try:
                    # Call the new helper function
                    ticket_data = get_ticket_details(search_query.strip())
                    
                    st.success(f"Found ticket: **{ticket_data['Ticket ID']}**")
                    
                    # --- UPDATED: Display results with st.markdown ---
                    st.markdown(f"""
                    - **Status:** `{ticket_data['Status']}`
                    - **Assignee:** {ticket_data['Assignee']}
                    - **Request Type:** {ticket_data['Request Type']}
                    - **Created:** {ticket_data['Created']}
                    - **Resolved:** {ticket_data['Resolved']}
                    - **Link:** [Open in Jira ↗]({ticket_data['Link']})
                    """)

                except FileNotFoundError as e:
                    st.error(f"Not Found: {e}", icon="🚫")
                except ValueError as e:
                    st.error(f"Invalid Input: {e}", icon="⚠️")
                except requests.HTTPError as e:
                    if e.response.status_code == 401:
                        st.error("Authentication Error. Check your API token.", icon="🔒")
                    else:
                        st.error(f"HTTP Error: {e}", icon="🔥")
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}", icon="🔥")


# --- 11. Footer w/ Auto-Refresh ---
st.divider()
auto_refresh = st.toggle("Auto-refresh (every 5 minutes)", value=True)

if auto_refresh:
    # Interval is in milliseconds. 300 * 1000 = 5 minutes (matches cache ttl)
    st_autorefresh(interval=300 * 1000, key="data_refresher") # <-- ⭐️ FIX: Removed 'st.'

if 'last_fetch_time' in st.session_state:
    st.caption(f"Data last refreshed: {st.session_state['last_fetch_time'].strftime('%Y-%m-%d %H:%M:%S')}")
