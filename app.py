import streamlit as st
import requests
import pandas as pd
import altair as alt
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone, timedelta
import json
import re
import os.path
import base64
import time

# --- External Libraries ---
from streamlit_autorefresh import st_autorefresh
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type, RetryError

# --- Google / Gmail Imports ---
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# --- 1. Page Configuration ---
st.set_page_config(
    page_title="TKTS Dashboard",
    page_icon="",
    layout="wide",
)

# --- 2. Altair Global Theme ---
def set_altair_theme():
    """Sets a global Altair theme to use 'Manrope' font."""
    font = "Manrope"
    
    @alt.theme.register("my_theme", enable=True)
    def my_theme():
        return {
            "config": {
                "font": font,
                "title": {"font": font, "fontSize": 14},
                "header": {"font": font, "labelFont": font},
                "axis": {"font": font, "labelFont": font, "titleFont": font},
                "legend": {"font": font, "labelFont": font, "titleFont": font},
                "text": {"font": font},
            }
        }

set_altair_theme()


# --- 3. Authentication (JIRA) ---
try:
    JIRA_DOMAIN = st.secrets["JIRA_DOMAIN"]
    JIRA_USER_EMAIL = st.secrets["JIRA_USER_EMAIL"]
    JIRA_API_TOKEN = st.secrets["JIRA_API_TOKEN"]
    JIRA_AUTH = HTTPBasicAuth(JIRA_USER_EMAIL, JIRA_API_TOKEN)
except Exception:
    st.error("Secrets not configured. Please add JIRA_DOMAIN, JIRA_USER_EMAIL, and JIRA_API_TOKEN to your Streamlit secrets.")
    st.stop()


# --- 4. Helper Functions (Formatting & UI) ---
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

def build_html_table(df, columns, link_column_key=None, link_text_col_key=None):
    """Builds a scrollable HTML table with Manrope font."""
    html = """
    <div class="table-container">
        <table class="custom-table">
            <thead>
                <tr>
    """
    for col_name in columns.values():
        html += f"<th>{col_name}</th>"
    html += "</tr></thead><tbody>"
    
    for index, row in df.iterrows():
        html += "<tr>"
        for col_key, col_name in columns.items():
            if col_key == link_column_key:
                url = row[col_key]
                text = row[link_text_col_key]
                html += f'<td><a href="{url}" target="_blank">{text}</a></td>'
            else:
                html += f"<td>{row[col_key]}</td>"
        html += "</tr>"
        
    html += "</tbody></table></div>"
    return html


# --- 5. Jira Data Loading Functions ---

@st.cache_data(ttl=300)
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3), retry=retry_if_exception_type(requests.RequestException))
def load_jira_data():
    """Loads ACTIVE tickets based on specific JQL."""
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    # --- QA CHECK: Includes 'ORDER BY created DESC' and Excludes 'Sub-task' ---
    jql_query = """
        project = TKTS AND 
        issuetype NOT IN ("Sub-task") AND
        issuetype in ("ANZ - Advanced Pixels", "ANZ - Audio Creatives", "ANZ - Bespoke Requests", "ANZ - Brand Lift Study Creatives", "ANZ - CTV and BVOD Creatives", "ANZ - Celtra Creatives", "ANZ - DCO Creatives", "ANZ - DOOH Creatives", "ANZ - Display Creatives", "ANZ - HTML5 Hosted Creatives", "ANZ - Native Creatives", "ANZ - Rejected Creatives", "ANZ - Social Boost Creatives", "ANZ - Standard Pixels", "ANZ - Troubleshooting - Creatives", "ANZ - Troubleshooting - Pixels", "ANZ - Video Creatives", "DE - Audio Creatives", "DE - Bespoke Requests", "DE - CTV Creatives", "DE - Celtra Creatives", "DE - Display Creatives", "DE - Native Creatives", "DE - Troubleshooting Creatives", "DE - Video Creatives", "IN - Audio Creatives", "IN - Bespoke Requests", "IN - Brand Lift Study Creatives", "IN - CTV/OTT Creatives", "IN - DCO Creatives", "IN - Display Creatives", "IN - Native Creatives", "IN - Troubleshooting Requests", "IN - Video Creatives", "Lenovo - Bespoke Request", "Lenovo - Display Creatives", "Lenovo - Trackers", "Lenovo - Troubleshooting", "Lenovo - Video Creatives", "MENA - Bespoke Requests", "MENA - Display Creatives", "MENA - Native Creatives", "MENA - Troubleshooting Creatives", "MENA - Video Creatives", "SEA - Audio Creatives", "SEA - Bespoke Requests", "SEA - Celtra Creatives", "SEA - DOOH Creatives", "SEA - Display Creatives", "SEA - Native Creatives", "SEA - Troubleshooting Creatives", "SEA - Video Creatives", "SEA - OMG/Assembly Creatives", "UK - Ad-Lib Creatives", "UK - Audio Creatives", "UK - Bespoke Requests", "UK - CTV Creatives", "UK - Celtra Creatives", "UK - Customer Match Creatives", "UK - Display Creatives", "UK - Native Creatives", "UK - Skin Creatives", "UK - Stories Creatives", "UK - THG - Creatives and Trackers", "UK - Troubleshooting Creatives", "UK - Video Creatives", "China - Bespoke Request", "China - Inbound", "MENA - Celtra Creatives", "IN - Customer Match Creatives", "ANZ - SeenThis Creatives - Self-serve only", "SEA - SeenThis Creatives - Self-serve only", "IN - SeenThis Creatives - Self-serve only", "UK - SeenThis Creatives - Self-serve only", "MENA - SeenThis Creatives - Self-serve only", "SEA - DCO Creatives", "MENA - CTV Creatives", "SEA - OTT Creatives") AND 
        status in ("In Progress", "Open", "Reopened", "Waiting for customer", "Waiting for support")
        ORDER BY created DESC
    """
    
    fields_to_request = ["status", "assignee", "created", "project", "issuetype", "customfield_10704", "customfield_10522", "customfield_16020"]

    payload = json.dumps({"jql": jql_query, "fields": fields_to_request, "maxResults": 1000})
    response = requests.post(url, headers=headers, data=payload, auth=JIRA_AUTH, timeout=10)
    response.raise_for_status()
    data = response.json()

    issues_list = []
    for issue in data.get('issues', []):
        request_type = "N/A"
        if issue['fields'].get('issuetype'):
            request_type = issue['fields']['issuetype']['name']
        
        breach_time = pd.NaT 
        sla_field = issue['fields'].get('customfield_10704') 
        
        if sla_field: 
            try:
                breach_time = sla_field['ongoingCycle']['breachTime']['iso8601']
            except (KeyError, TypeError, AttributeError):
                try:
                    breach_time = sla_field['completedCycles'][-1]['breachTime']['iso8601']
                except (KeyError, TypeError, AttributeError, IndexError):
                    pass 
        
        issues_list.append({
            "key": issue['key'],
            "status": issue['fields']['status']['name'],
            "assignee": (issue['fields']['assignee']['displayName'] if issue['fields']['assignee'] else "Unassigned"),
            "created": issue['fields']['created'],
            "request_type": request_type, 
            "breach_time_api": breach_time,
            "campaign_start_main": issue['fields'].get("customfield_10522"),
            "campaign_start_china": issue['fields'].get("customfield_16020")
        })

    st.session_state['last_fetch_time'] = datetime.now()

    if not issues_list:
        return pd.DataFrame(columns=["key", "status", "assignee", "created", "request_type", "breach_time_api", "campaign_start_main", "campaign_start_china"])

    df = pd.DataFrame(issues_list)
    df['created'] = pd.to_datetime(df['created'], utc=True)
    df['breach_time_api'] = pd.to_datetime(df['breach_time_api'], utc=True)
    df['campaign_start_main'] = pd.to_datetime(df['campaign_start_main'], utc=True, errors='coerce')
    df['campaign_start_china'] = pd.to_datetime(df['campaign_start_china'], utc=True, errors='coerce')
    df['campaign_start_date'] = df['campaign_start_china'].fillna(df['campaign_start_main'])

    if not df.empty:
        df = df[~df['status'].str.lower().isin(["closed", "done", "resolved", "cancelled", "rejected"])]

    return df


@st.cache_data(ttl=300)
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3), retry=retry_if_exception_type(requests.RequestException))
def load_all_jira_data():
    """Loads tickets CREATED or RESOLVED today."""
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    # --- QA CHECK: Excludes Sub-tasks & Sorts by Date ---
    jql_query = 'project = TKTS AND issuetype NOT IN ("Sub-task") AND (created >= startOfDay() OR resolutiondate >= startOfDay()) ORDER BY created DESC'
    
    fields_to_request = ["key", "status", "created", "resolutiondate", "assignee", "issuetype"]

    payload = json.dumps({"jql": jql_query, "fields": fields_to_request, "maxResults": 1000})
    response = requests.post(url, headers=headers, data=payload, auth=JIRA_AUTH, timeout=15)
    response.raise_for_status()
    data = response.json()

    issues = []
    for issue in data.get("issues", []):
        fields = issue["fields"]
        assignee = fields.get('assignee')['displayName'] if fields.get('assignee') else "Unassigned"
        request_type = fields.get('issuetype')['name'] if fields.get('issuetype') else "N/A"
        
        issues.append({
            "key": issue["key"],
            "created": fields["created"],
            "resolutiondate": fields.get("resolutiondate"),
            "status": fields["status"]["name"],
            "assignee": assignee,
            "request_type": request_type
        })
    
    if not issues:
        df = pd.DataFrame(columns=["key", "created", "resolutiondate", "status", "assignee", "request_type"])
        df["created"] = pd.to_datetime(df["created"], utc=True)
        df["resolutiondate"] = pd.to_datetime(df["resolutiondate"], utc=True)
        return df

    df = pd.DataFrame(issues)
    df["created"] = pd.to_datetime(df["created"], utc=True)
    df["resolutiondate"] = pd.to_datetime(df["resolutiondate"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=300)
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3), retry=retry_if_exception_type(requests.RequestException))
def load_newly_assigned_tickets():
    """Fetches tickets where assignee CHANGED today."""
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    # --- QA CHECK: Excludes Sub-tasks & Sorts by Date ---
    jql_query = 'project = TKTS AND issuetype NOT IN ("Sub-task") AND assignee CHANGED during (startOfDay(), now()) ORDER BY updated DESC'
    
    fields_to_request = ["assignee", "key"] 

    payload = json.dumps({"jql": jql_query, "fields": fields_to_request, "maxResults": 1000})
    response = requests.post(url, headers=headers, data=payload, auth=JIRA_AUTH, timeout=15)
    response.raise_for_status()
    data = response.json()
    
    assigned_tickets_list = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {})
        assignee = fields.get('assignee')['displayName'] if fields.get('assignee') else "Unassigned"
        assigned_tickets_list.append({"key": issue.get("key"), "assignee": assignee})
    
    return assigned_tickets_list


@st.cache_data(ttl=60)
def get_ticket_details(ticket_key):
    """Fetches single ticket details."""
    if re.fullmatch(r'\d+', ticket_key):
        ticket_key = f"TKTS-{ticket_key}"
    if not re.fullmatch(r'TKTS-\d+', ticket_key, re.IGNORECASE):
        raise ValueError(f"Invalid ticket format.")

    url = f"{JIRA_DOMAIN}/rest/api/3/issue/{ticket_key.upper()}"
    headers = {"Accept": "application/json"}
    params = {"fields": "status,assignee,created,resolutiondate,issuetype"}

    response = requests.get(url, headers=headers, params=params, auth=JIRA_AUTH, timeout=10)
    if response.status_code == 404:
        raise FileNotFoundError(f"Ticket '{ticket_key.upper()}' not found.")
    response.raise_for_status()
    
    data = response.json()
    fields = data.get("fields", {})
    
    return {
        "Ticket ID": data['key'],
        "Link": f"{JIRA_DOMAIN}/browse/{data['key']}",
        "Status": fields.get('status', {}).get('name', "N/A"),
        "Assignee": fields.get('assignee', {}).get('displayName', "Unassigned") if fields.get('assignee') else "Unassigned",
        "Request Type": fields.get('issuetype', {}).get('name', "N/A"),
        "Created": pd.to_datetime(fields.get('created')).strftime('%d-%b-%Y %H:%M'),
        "Resolved": pd.to_datetime(fields.get('resolutiondate')).strftime('%d-%b-%Y %H:%M') if fields.get('resolutiondate') else "Not yet resolved"
    }


# --- 6. Gmail Functions (Robust Error Handling & Time Fix) ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

@st.cache_resource
def get_gmail_service():
    """Builds and returns a Gmail API service object."""
    creds = None
    if 'GMAIL_TOKEN' not in st.secrets:
        st.error("❌ 'GMAIL_TOKEN' is missing from secrets.toml")
        return None

    try:
        creds_json = st.secrets['GMAIL_TOKEN']
        if isinstance(creds_json, str):
            creds_info = json.loads(creds_json)
        else:
            creds_info = creds_json    
        creds = Credentials.from_authorized_user_info(creds_info, SCOPES)
    except Exception as e:
        st.error(f"❌ JSON Parsing Error: {e}")
        return None

    if not creds:
        st.error("❌ Credentials object could not be created.")
        return None
    
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            st.error(f"❌ Token Refresh Failed: {e}. Generate a new token.")
            return None 

    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        st.error(f"❌ Service Build Error: {e}")
        return None

def get_email_body(payload):
    """Recursively gets email body."""
    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            body += get_email_body(part)
    elif payload.get('mimeType') == 'text/plain':
        data = payload.get('body', {}).get('data')
        if data:
            body += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return body

@st.cache_data(ttl=300)
@retry(
    wait=wait_fixed(2), 
    stop=stop_after_attempt(3), 
    retry=retry_if_exception_type((HttpError, TimeoutError, Exception))
)
def get_priority_ticket_set(_service, start_timestamp):
    """
    Searches Gmail for priority tickets since Local Midnight.
    """
    if not _service: 
        return set()

    # --- QA CHECK: Use strict 'after' timestamp (No rolling 24h) ---
    query = f'("adops-ea@miqdigital.com" OR "adops-emea@miqdigital.com") ("priority" OR "prioritise" OR "prioritize" OR "Urgent") after:{start_timestamp}'
    
    print(f"DEBUG: Gmail Query = {query}") 
    
    results = _service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("DEBUG: No emails found matching criteria.")
        return set()

    unique_ticket_ids = set()
    ticket_regex = re.compile(r'TKTS\s*-\s*\d+', re.IGNORECASE)
    
    batch = _service.new_batch_http_request()
    
    def add_tickets_to_set(request_id, response, exception):
        if exception is None:
            subject = ""
            snippet = response.get('snippet', '')
            headers = response.get('payload', {}).get('headers', [])
            for h in headers:
                if h['name'].lower() == 'subject':
                    subject = h['value']
                    break
            
            # --- QA CHECK: Check Subject first (to avoid Footer matches) ---
            found_in_subject = ticket_regex.findall(subject)
            if found_in_subject:
                for ticket in found_in_subject:
                    normalized_ticket = ticket.replace(" ", "").upper()
                    unique_ticket_ids.add(normalized_ticket)
            else:
                # Only check body if not found in subject
                payload = response.get('payload', {})
                body = get_email_body(payload)
                search_text = f"{body} {snippet}"
                found_tickets = ticket_regex.findall(search_text)
                if found_tickets:
                    for ticket in found_tickets:
                        normalized_ticket = ticket.replace(" ", "").upper()
                        unique_ticket_ids.add(normalized_ticket)
        else:
            print(f"Warning: Failed to get specific email: {exception}")

    for message in messages[:50]: 
        batch.add(_service.users().messages().get(userId='me', id=message['id'], format='full'), callback=add_tickets_to_set)
    
    batch.execute()
    
    return unique_ticket_ids


# --- 7. CSS Styling ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@200;400;500;600&display=swap');
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');

html, body, [class*="st-"] { font-family: 'Manrope', Arial, sans-serif; font-weight: 200; }
h1, h2, h3, h4, h5, h6 { font-family: 'Manrope', Arial, sans-serif !important; }

.table-container { height: 400px; overflow-y: auto; border-radius: 0px; }
.custom-table { width: 100%; border-collapse: collapse; }
.custom-table th, .custom-table td { padding: 6px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.2); text-align: left; font-weight: 400; font-size: 0.9rem; }
.custom-table th { font-weight: 600; background-color: #0E1117; color: #FFFFFF; position: sticky; top: 0; }
.custom-table a { color: #58C0ED; text-decoration: none; font-weight: 600; }
.custom-table a:hover { text-decoration: underline; }

.highlights-container [data-testid="stVerticalBlock"] { text-align: center; }
.highlights-container [data-testid="stVerticalBlock"] ul { text-align: left; display: inline-block; }

div[data-testid="stSelectbox"] [data-testid="stSvgIcon"] { font-family: 'Material Icons' !important; font-weight: 400 !important; font-size: 24px !important; }

.header-container { padding: 2rem; background-image: url('https://i.ibb.co/nMTJF4B9/vj-HZbu8-Imgur.jpg'); background-size: cover; background-position: center; margin-bottom: 1rem; border-radius: 0px !important; }
.header-text { color: white; text-align: center; font-size: 2.0rem; font-weight: 500; }

div[data-testid="stContainer"], div[data-testid="stTabs"], div[data-testid="stMarkdownContainer"], div[data-testid="stVerticalBlock"], div[data-testid="stMetric"] { border-radius: 0px !important; }
button { border-radius: 0px !important; }
</style>
""", unsafe_allow_html=True)


# --- 8. Header ---
st.markdown("""<div class="header-container"><div class="header-text">TKTS Dashboard</div></div>""", unsafe_allow_html=True)


# --- 9. Load Data ---
# Initialize Empty
df = pd.DataFrame(columns=["key", "status", "assignee", "created", "request_type", "breach_time_api", "campaign_start_main", "campaign_start_china", "campaign_start_date"])
df_all = pd.DataFrame(columns=["key", "created", "resolutiondate", "status", "assignee", "request_type"])

# Block 1: Active Tickets
try:
    df = load_jira_data()
except RetryError as e:
    st.error(f"Failed to fetch ACTIVE tickets: {e.last_attempt.exception()}", icon="🚨")
except Exception as e:
    st.error(f"Error loading ACTIVE tickets: {e}", icon="🚨")

# Block 2: Daily Metrics
try:
    df_all = load_all_jira_data()
except RetryError as e:
    st.error(f"Failed to fetch DAILY metrics: {e.last_attempt.exception()}", icon="📉")
except Exception as e:
    st.error(f"Error loading DAILY metrics: {e}", icon="📉")

# Block 3: Priority Tickets
priority_ticket_set = set()
priority_display_value = "0"
priority_is_error = False

gmail_service = get_gmail_service()

if gmail_service is None:
    priority_display_value = "⚠️"
    priority_is_error = True
else:
    try:
        # --- QA CHECK: Calculate LOCAL Midnight (User's computer time) ---
        local_now = datetime.now()
        local_midnight = datetime(local_now.year, local_now.month, local_now.day)
        midnight_timestamp = int(local_midnight.timestamp())
        
        priority_ticket_set = get_priority_ticket_set(gmail_service, midnight_timestamp)
        priority_display_value = str(len(priority_ticket_set))
    except RetryError as e:
        st.error(f"Gmail Connection Timeout: {e}")
        priority_display_value = "⚠️"
        priority_is_error = True
    except Exception as e:
        st.error(f"Gmail Search Error: {e}")
        priority_display_value = "⚠️"
        priority_is_error = True

priority_count = len(priority_ticket_set)

# Stop if critical data missing
if df.empty and df_all.empty:
    st.error("All data sources failed to load. Please check secrets.")
    st.stop()


# --- 10. Compute Metrics ---
now = pd.Timestamp.now(tz='UTC')
df['breach_time'] = df['breach_time_api'] 
df['time_diff'] = df['breach_time'] - now
df['SLA Timer'] = df['time_diff'].apply(format_time_remaining)
df['SLA_Status'] = df['time_diff'].apply(lambda x: "🚨 Breached" if (not pd.isna(x) and x.total_seconds() < 0) else "✅ Within SLA")
df['Ticket'] = df['key']
df['Ticket Link'] = df['key'].apply(lambda key: f"{JIRA_DOMAIN}/browse/{key}")

total_tickets = len(df)
breached_count = len(df[df['SLA_Status'] == '🚨 Breached'])
within_sla_count = len(df[df['SLA_Status'] == '✅ Within SLA'])

today = pd.Timestamp.now(tz='UTC').date()
df_all["created_date"] = df_all["created"].dt.date
df_all["resolved_date"] = df_all["resolutiondate"].dt.date

created_today_count = len(df_all[(df_all["created_date"] == today) & (df_all['request_type'] != "China - Outbound")])
closed_today_count = len(df_all[(df_all["resolved_date"] == today) & (df_all['request_type'] != "China - Outbound")])


# --- 11. Tabs Layout ---
tab_dashboard, tab_explorer, tab_lookup = st.tabs(["SUMMARY", "EXPLORE", "TKTS LOOKUP"])

# === TAB 1: DASHBOARD (ALIGNMENT FIXED) ===
with tab_dashboard:
    with st.container(border=True):
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        col1.markdown(f"<div style='text-align:center;'><h3 style='color:orange; margin:0;'>{total_tickets}</h3><p style='margin:0;'>TKTS Active</p></div>", unsafe_allow_html=True)
        col2.markdown(f"<div style='text-align:center;'><h3 style='color:green; margin:0;'>{within_sla_count}</h3><p style='margin:0;'>TKTS Within SLA</p></div>", unsafe_allow_html=True)
        col3.markdown(f"<div style='text-align:center;'><h3 style='color:red; margin:0;'>{breached_count}</h3><p style='margin:0;'>TKTS Breached</p></div>", unsafe_allow_html=True)
        col4.markdown(f"<div style='text-align:center;'><h3 style='color:blue; margin:0;'>{created_today_count}</h3><p style='margin:0;'>TKTS Created Today</p></div>", unsafe_allow_html=True)
        col5.markdown(f"<div style='text-align:center;'><h3 style='color:purple; margin:0;'>{closed_today_count}</h3><p style='margin:0;'>TKTS Closed Today</p></div>", unsafe_allow_html=True)
        
        # PRIORITY CARD
        col6.markdown(f"""
        <div style='text-align:center;'>
            <h3 style='color:#FFC300; margin:0;'>{priority_display_value}*</h3>
            <p style='margin:0;'>Priority TKTS Today</p>
        </div>""", unsafe_allow_html=True)
        
    st.caption("*Priority TKTS Today — count may vary.")

    # Filters
    st.markdown("### Real-Time TKTS Summary")
    col_b1, col_b2, col_b3, _ = st.columns([1, 1, 1, 3])
    
    if col_b1.button(f"All ({total_tickets})", use_container_width=True, type="primary" if st.session_state.get('filter', 'All') == 'All' else "secondary"):
        st.session_state.filter = 'All'
        st.rerun()
    if col_b2.button(f"✅ Within SLA ({within_sla_count})", use_container_width=True, type="primary" if st.session_state.get('filter') == '✅ Within SLA' else "secondary"):
        st.session_state.filter = '✅ Within SLA'
        st.rerun()
    if col_b3.button(f"🚨 Breached ({breached_count})", use_container_width=True, type="primary" if st.session_state.get('filter') == '🚨 Breached' else "secondary"):
        st.session_state.filter = '🚨 Breached'
        st.rerun()

    # Table Data
    filter_val = st.session_state.get('filter', 'All')
    display_df = df if filter_val == 'All' else df[df['SLA_Status'] == filter_val]

    table_df = display_df.copy()
    if not table_df.empty:
        table_df['created_str'] = table_df['created'].dt.strftime('%d%b%Y %H:%M')
        table_df['start_str'] = table_df['campaign_start_date'].dt.strftime('%d%b%Y')
        table_df["Link_Text"] = "Open ↗"
        
        html_cols = {'key': 'TKTS-No', 'Ticket Link': '', 'SLA Timer': 'SLA', 'status': 'Status', 'assignee': 'Assignee', 'request_type': 'Request Type', 'created_str': 'Created (UTC)', 'start_str': 'Start Date'}
        st.markdown(build_html_table(table_df, html_cols, "Ticket Link", "Link_Text"), unsafe_allow_html=True)
    else:
        st.info("No tickets found for this filter.")

    # Highlights
    st.divider()
    st.header(f"Today’s Highlights ({today.strftime('%d-%b-%Y')})")
    st.markdown('<div class="highlights-container">', unsafe_allow_html=True)
    with st.container(border=True):
        col_created, col_resolved = st.columns(2)
        
        with col_created:
            st.subheader("Top 5 Requests types")
            created_today_df = df_all[df_all["created_date"] == today]
            counts = created_today_df['request_type'].value_counts().drop(["China - Outbound"], errors='ignore').head(5)
            if counts.empty: st.info("No tickets created today.")
            else: st.markdown("\n".join([f"- **{k}:** {v} ticket(s)" for k, v in counts.items()]))

        with col_resolved:
            st.subheader("Top 3 Assignees")
            new_assign_list = load_newly_assigned_tickets()
            if not new_assign_list: st.info("No tickets assigned today.")
            else:
                assign_df = pd.DataFrame(new_assign_list)
                counts = assign_df['assignee'].value_counts().drop(["Adops-EA Group", "Ganesh Balasaheb Zaware"], errors='ignore').head(3)
                if counts.empty: st.info("No tickets assigned today.")
                else: st.markdown("\n".join([f"- **{k}:** {int(v)} ticket(s)" for k, v in counts.items()]))
    st.markdown('</div>', unsafe_allow_html=True)
    st.divider()
    
    # Charts
    st.header("TKTS Overview")
    with st.container(border=True):
        if not df.empty:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.subheader("TKTS/Status")
                src = df['status'].value_counts().reset_index()
                src.columns=['status','Count']
                st.altair_chart(alt.Chart(src).mark_bar(size=15).encode(y=alt.Y('status:N', sort='-x', title=None), x='Count:Q', tooltip=['status', 'Count']).interactive(), use_container_width=True)
            with c2:
                st.subheader("TKTS/Assignee")
                src = df['assignee'].value_counts().reset_index()
                src.columns=['assignee','Count']
                st.altair_chart(alt.Chart(src).mark_bar(size=15).encode(y=alt.Y('assignee:N', sort='-x', title=None), x='Count:Q', tooltip=['assignee', 'Count']).interactive(), use_container_width=True)
            with c3:
                st.subheader("TKTS/Request type")
                src = df['request_type'].value_counts().reset_index()
                src.columns=['request_type','Count']
                st.altair_chart(alt.Chart(src).mark_bar(size=15).encode(y=alt.Y('request_type:N', sort='-x', title=None), x='Count:Q', tooltip=['request_type', 'Count']).interactive(), use_container_width=True)
        else:
            st.info("No active tickets.")


# === TAB 2: EXPLORE ===
with tab_explorer:
    # Active Filter
    st.header("Filter Open TKTS by Assignee")
    with st.container(border=True):
        if not df.empty:
            sel = st.selectbox("Select assignee:", sorted(df['assignee'].unique()), label_visibility="collapsed")
            if sel:
                sub_df = df[df['assignee'] == sel].copy()
                sub_df['created_str'] = sub_df['created'].dt.strftime('%d%b%Y %H:%M')
                sub_df['start_str'] = sub_df['campaign_start_date'].dt.strftime('%d%b%Y')
                sub_df["Link_Text"] = "Open ↗"
                cols = {'key':'TKTS-No','Ticket Link':'', 'SLA Timer':'SLA', 'status':'Status','request_type':'Request Type','created_str':'Created','start_str':'Start Date'}
                st.markdown(build_html_table(sub_df, cols, "Ticket Link", "Link_Text"), unsafe_allow_html=True)
        else:
            st.info("No active tickets.")

    st.divider()
    
    # Closed Today
    st.header(f"Closed TKTS by Assignee on ({today.strftime('%d-%b-%Y')})")
    with st.container(border=True):
        closed_today = df_all[(df_all["resolved_date"] == today) & (~df_all['assignee'].isin(["Adops-EA Group", "Ganesh Balasaheb Zaware"])) & (df_all['request_type'] != "China - Outbound")]
        if closed_today.empty:
            st.info("No tickets closed today.")
        else:
            sel_closed = st.selectbox("Select assignee (Closed):", sorted(closed_today['assignee'].unique()), label_visibility="collapsed")
            if sel_closed:
                rep_df = closed_today[closed_today['assignee'] == sel_closed].copy()
                st.metric(f"Tickets Closed by {sel_closed}", len(rep_df))
                rep_df['Link'] = rep_df['key'].apply(lambda k: f"{JIRA_DOMAIN}/browse/{k}")
                rep_df['Link_Text'] = "Open ↗"
                cols = {'key':'TKTS-No', 'request_type':'Request Type', 'Link':''}
                st.markdown(build_html_table(rep_df, cols, "Link", "Link_Text"), unsafe_allow_html=True)

    st.divider()
    
    # Priority Details
    st.header(f"Priority TKTS Details ({today.strftime('%d-%b-%Y')})")
    with st.container(border=True):
        if not priority_ticket_set:
            st.info("No priority tickets found.")
        else:
            master_df = pd.concat([df, df_all]).drop_duplicates('key')
            p_df = master_df[master_df['key'].isin(priority_ticket_set)].copy()
            if p_df.empty:
                st.warning(f"Found IDs {priority_ticket_set}, but not in JIRA data.")
            else:
                p_df['Link'] = p_df['key'].apply(lambda k: f"{JIRA_DOMAIN}/browse/{k}")
                p_df['Link_Text'] = "Open ↗"
                cols = {'key':'TKTS-No', 'Link':'', 'assignee':'Assignee', 'request_type':'Request Type', 'status':'Status'}
                st.markdown(build_html_table(p_df, cols, "Link", "Link_Text"), unsafe_allow_html=True)


# === TAB 3: LOOKUP ===
with tab_lookup:
    query = st.text_input("Enter TKTS-ID (e.g., '1234')")
    if st.button("Search", type="primary", use_container_width=True) and query:
        with st.spinner("Searching..."):
            try:
                d = get_ticket_details(query.strip())
                st.success(f"Found: **{d['Ticket ID']}**")
                st.markdown(f"""
                - **Status:** `{d['Status']}`
                - **Assignee:** {d['Assignee']}
                - **Request Type:** {d['Request Type']}
                - **Created:** {d['Created']}
                - **Resolved:** {d['Resolved']}
                - **Link:** [Open in Jira ↗]({d['Link']})
                """)
            except Exception as e:
                st.error(f"Error: {e}")


# --- 12. Footer ---
st.divider()
if st.toggle("Auto-refresh (every 5 minutes)", value=True):
    st_autorefresh(interval=300 * 1000, key="data_refresher")

if 'last_fetch_time' in st.session_state:
    st.caption(f"Data last refreshed: {st.session_state['last_fetch_time'].strftime('%Y-%m-%d %H:%M:%S')}")

