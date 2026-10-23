"""Your public website. Run it locally from the project folder:

    streamlit run app/streamlit_app.py

This starter works before anything is configured, so you can test it during Week 1 Setup.
You'll extend it with your AI agent: data views in Week 4, the chatbot in Week 5,
and the agent in Week 6. Read every change before you accept it.

Two rules this file follows, and yours must keep following:
  * It connects ONLY as the read-only role (APP_DATABASE_URL), never as the owner.
  * Anything that spends money (the chatbot) or acts (the agent) sits behind the sign-in.
"""

import hmac
import os
from datetime import datetime, timezone

import psycopg
import streamlit as st
from dotenv import load_dotenv

# Locally, secrets come from .env. On Render they come from the service's environment settings.
load_dotenv()

# Your Week 3 freshness guarantee: older data than this triggers a visible warning.
FRESHNESS_HOURS = float(os.environ.get("FRESHNESS_HOURS", "24"))

st.set_page_config(page_title="My BSAD 6153 Project", page_icon=":bar_chart:")


@st.cache_data(ttl=600)  # Re-check every 10 minutes. Keep the TTL shorter than your sync interval.
def _query_latest_successful_sync():
    # Streamlit caches only successful results, never errors, so a brief database
    # outage doesn't stay on screen for the whole TTL.
    with psycopg.connect(os.environ["APP_DATABASE_URL"], connect_timeout=10) as conn:
        # The value goes in as a parameter (%s), never pasted into the SQL text.
        row = conn.execute(
            "select max(finished_at) from sync_runs where status = %s", ("success",)
        ).fetchone()
    return row[0]


def latest_successful_sync():
    """Return (finished_at, state). state explains what happened, so the page can say it plainly."""
    if not os.environ.get("APP_DATABASE_URL"):
        return None, "not_configured"
    try:
        return _query_latest_successful_sync(), "ok"
    except psycopg.errors.UndefinedTable:
        return None, "no_sync_runs"
    except psycopg.Error:
        # Never show the raw error to visitors: it can reveal details about your database.
        return None, "db_error"


def freshness_banner():
    finished_at, state = latest_successful_sync()
    if state == "not_configured":
        st.info("Database not connected yet. Add APP_DATABASE_URL to your .env file (Week 2).")
    elif state == "no_sync_runs":
        st.info("No sync history yet. You'll create the sync_runs table in Week 3.")
    elif state == "db_error":
        st.warning("The data is unavailable right now. Please try again in a minute.")
    elif finished_at is None:
        st.warning("The data has never been synced successfully.")
    else:
        hours_old = (datetime.now(timezone.utc) - finished_at).total_seconds() / 3600
        message = f"Data last updated {finished_at:%Y-%m-%d %H:%M} UTC ({hours_old:.1f} hours ago)."
        if hours_old > FRESHNESS_HOURS:
            st.warning("This data may be out of date. " + message)
        else:
            st.success(message)


def signed_in():
    """Simple password sign-in for the parts of the site that spend money or take actions.

    The password lives in the APP_PASSWORD environment variable, never in code. Share it
    with the instructors privately. An alternative is Streamlit's built-in st.login(),
    which signs people in with an identity provider such as Google; it needs extra setup.
    """
    if st.session_state.get("signed_in"):
        return True
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        st.info("Sign-in isn't set up yet. Add APP_PASSWORD to your environment (Week 5).")
        return False
    with st.form("sign_in"):
        attempt = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            # compare_digest avoids leaking information through timing differences.
            if hmac.compare_digest(attempt.encode(), expected.encode()):
                st.session_state["signed_in"] = True
                st.rerun()
            else:
                st.error("That password is incorrect.")
    return False


st.title("My BSAD 6153 Project")
st.caption("Replace this title and caption with what your site helps you decide.")

freshness_banner()

st.header("Data")
st.write("Your Week 4 views go here: at least two views that answer your own questions.")

st.header("Assistant")
if signed_in():
    st.write("Your Week 5 chatbot goes here, and your Week 6 agent after it.")
    if st.button("Sign out"):
        st.session_state["signed_in"] = False
        st.rerun()

with st.expander("About this site"):
    st.write(
        "A student project for BSAD 6153 AI Implementations at Newman University. "
        "Say what the data is, where it comes from (with the attribution your API requires), "
        "and how often it's updated. On Render's free tier the site sleeps when idle, "
        "so the first visit can take about a minute."
    )
