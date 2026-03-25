import streamlit as st
import os
from dotenv import load_dotenv
from audio_handler import render_upload_tab, render_record_tab
from storage import get_all_meetings, load_meeting
from summarizer import generate_summary

load_dotenv()

st.set_page_config(
    page_title="MeetScribe - Meeting Summarizer",
    page_icon="🎙️",
    layout="wide"
)

st.title("🎙️ MeetScribe")
st.caption("Record or upload meeting audio → Get transcripts, summaries & action items")

with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-...",
        help="Get your API key from platform.openai.com/api-keys"
    )
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        st.success("API key set!")

    existing_key = os.getenv("OPENAI_API_KEY")
    if not existing_key:
        try:
            existing_key = st.secrets.get("OPENAI_API_KEY")
            if existing_key:
                os.environ["OPENAI_API_KEY"] = existing_key
        except Exception:
            pass

    if not os.getenv("OPENAI_API_KEY"):
        st.warning("Please enter your OpenAI API key to use the app.")

if "consent_given" not in st.session_state:
    st.session_state.consent_given = False

if not st.session_state.consent_given:
    st.warning("⚠️ **Recording Consent Required**")
    st.write(
        "This app records and transcribes audio. By proceeding, you confirm that "
        "all meeting participants have given consent to be recorded."
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ All participants consent - proceed", type="primary", use_container_width=True):
            st.session_state.consent_given = True
            st.rerun()
    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.stop()
    st.stop()

tab1, tab2, tab3 = st.tabs(["📤 Upload Audio", "🎤 Record Live", "📁 Past Meetings"])

with tab1:
    render_upload_tab()

with tab2:
    render_record_tab()

with tab3:
    st.subheader("📁 Past Meetings")
    meetings = get_all_meetings()
    if not meetings:
        st.info("No meetings saved yet. Upload or record your first meeting!")
    else:
        selected = st.selectbox("Select a meeting:", meetings, format_func=lambda x: x["title"])
        if selected:
            meeting = load_meeting(selected["path"])
            st.markdown(f"**Date:** {meeting['date']}")
            with st.expander("📝 Full Transcript", expanded=False):
                st.text_area("Transcript", meeting.get("transcript", ""), height=300, disabled=True)
            if meeting.get("summary"):
                st.markdown("### 📋 Summary")
                st.markdown(meeting["summary"])
            else:
                if st.button("Generate Summary", key=f"sum_{selected['path']}"):
                    with st.spinner("Generating summary and action items..."):
                        summary = generate_summary(meeting.get("transcript", ""))
                        from storage import save_summary
                        save_summary(selected["path"], summary)
                        st.markdown("### 📋 Summary")
                        st.markdown(summary)
