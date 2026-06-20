"""CRM ontology definition for the auto-parts selling scenario (predicate dictionary + helper functions).

This is the schema for Maxx's own graph. Unlike Cala (external facts), this also
carries private CRM data: email exchanges with a company, conversation records,
sales status -- i.e. long-term memory.
"""

from __future__ import annotations

# ---- Object properties (relationships between entities) ----
WORKS_AT = "works_at"          # person -> company
IN_INDUSTRY = "in_industry"    # company -> industry
REPORTS_TO = "reports_to"      # person -> person (decision chain)
HAS_EMAIL_THREAD = "has_email_thread"  # company -> email_thread
SENT_BY = "sent_by"            # email_thread -> person (our sender / their recipient)
ABOUT_PERSON = "about_person"  # email_thread -> person / deal -> person (the contacted person)
INTERESTED_IN = "interested_in"  # company -> product

# ---- Employment history (current vs past employer; powers warm-lead traversal) ----
WORKED_AT = "worked_at"        # person -> company (FORMER employer; works_at is current)

# ---- Trade / deal history (highest-value CRM extension) ----
HAS_DEAL = "has_deal"          # company -> deal
DEAL_PRODUCT = "deal_product"  # deal -> product
WON_BY = "won_by"              # deal -> employee (our rep who closed it)

# ---- Our own sales reps + email attribution (who contacted which company) ----
ACCOUNT_OWNER = "account_owner"  # company -> employee (who owns this account)
HANDLED_BY = "handled_by"        # email_thread -> employee (our reps who touched the thread)

# ---- Competitor / incumbent-supplier intelligence (displacement selling) ----
BUYS_FROM = "buys_from"        # company -> company (their current supplier / our competitor)

# ---- Interaction / activity log (calls, meetings, events -- beyond email) ----
HAS_ACTIVITY = "has_activity"  # company|person -> activity

# ---- Data properties (entity fields, object is a literal) ----
# person
FULL_NAME = "full_name"
JOB_TITLE = "job_title"
EMAIL = "email"
PHONE = "phone"
# company
COMPANY_NAME = "company_name"
EMPLOYEE_COUNT = "employee_count"
COUNTRY = "country"
WEBSITE = "website"
REVENUE = "revenue"
FOUNDED_YEAR = "founded_year"

# ---- email_thread / CRM conversation record fields (core of long-term memory) ----
THREAD_STATUS = "thread_status"        # cold / sent / replied / closed
MESSAGE_COUNT = "message_count"        # number of exchanged emails
LAST_CONTACT = "last_contact_date"
SENT_BY_EMPLOYEE = "sent_by_employee"  # which of our employees sent it (e.g. "Tim")
EMAIL_SUBJECT = "subject"
EMAIL_BODY = "body"
EMAIL_DIRECTION = "direction"          # outbound / inbound
PENDING_REPLY = "pending_reply"        # AI-drafted reply awaiting human confirm {subject, body}

# ---- deal fields (subject = deal node) ----
DEAL_STAGE = "deal_stage"              # lead / qualified / quoted / won / lost
DEAL_VALUE = "deal_value"              # e.g. "EUR 420,000"
QUOTED_PRICE = "quoted_price"          # unit / total quoted price
QUANTITY = "quantity"                  # order volume
ORDER_DATE = "order_date"
DELIVERY_DATE = "delivery_date"

# ---- employee fields (subject = employee node, our own rep) ----
EMPLOYEE_NAME = "employee_name"

# ---- competitor / supplier intel (subject = company node) ----
CURRENT_SUPPLIER = "current_supplier"  # incumbent supplier name (literal)
CONTRACT_END_DATE = "contract_end_date"
SHARE_OF_WALLET = "share_of_wallet"    # e.g. "60%"
CONNECTION_STRENGTH = "connection_strength"  # very_strong/strong/good/weak/very_weak/none -- CRM relationship signal (Attio-style)
NEXT_STEP = "next_step"                # free-text next action / next-meeting label

# ---- activity fields (subject = activity node) ----
ACTIVITY_TYPE = "activity_type"        # call / meeting / event / linkedin / note
ACTIVITY_DATE = "activity_date"
ACTIVITY_SUMMARY = "activity_summary"
ACTIVITY_OUTCOME = "activity_outcome"
NEXT_FOLLOWUP = "next_followup_date"

# Sales lead status enumeration
THREAD_STATUSES = ("cold", "sent", "replied", "closed")

# Deal pipeline stages
DEAL_STAGES = ("lead", "qualified", "quoted", "won", "lost")

# Activity types
ACTIVITY_TYPES = ("call", "meeting", "event", "linkedin", "note")

# Which predicates' object points to another node (used for front-end edges)
OBJECT_PROPERTIES = {
    WORKS_AT,
    WORKED_AT,
    IN_INDUSTRY,
    REPORTS_TO,
    HAS_EMAIL_THREAD,
    SENT_BY,
    ABOUT_PERSON,
    INTERESTED_IN,
    HAS_DEAL,
    DEAL_PRODUCT,
    WON_BY,
    ACCOUNT_OWNER,
    HANDLED_BY,
    BUYS_FROM,
    HAS_ACTIVITY,
}


def is_object_property(predicate: str) -> bool:
    return predicate in OBJECT_PROPERTIES
