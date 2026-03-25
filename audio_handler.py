import streamlit as st
import tempfile
import os
from transcriber import transcribe_audio
from summarizer import generate_summary
from storage import save_meeting


def render_upload_tab():
    st.subheader("Upload Meeting Audio")
    st.write("Upload an audio file from a recorded meeting.")
    title = st.text_input("Meeting title:", placeholder="e.g. Weekly Team Standup")
    uploaded_file = st.file_uploader(
        "Choose an audio file",
        type=["mp3", "wav", "m4a", "mp4", "webm", "ogg", "flac"],
        key="audio_upload"
    )
    if uploaded_file and title:
        st.audio(uploaded_file, format=uploaded_file.type)
        if st.button("Transcribe and Summarize", type="primary", use_container_width=True):
            suffix = os.path.splitext(uploaded_file.name)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            with st.spinner("Transcribing audio..."):
                transcript = transcribe_audio(tmp_path)
            if transcript:
                st.success("Transcription complete!")
                with st.expander("Full Transcript", expanded=True):
                    st.text_area("", transcript, height=250, disabled=True)
                with st.spinner("Generating summary..."):
                    summary = generate_summary(transcript)
                st.markdown("### Summary and Action Items")
                st.markdown(summary)
                save_meeting(
                    title=title,
                    audio_path=tmp_path,
                    transcript=transcript,
                    summary=summary
                )
                st.success("Meeting saved!")
            else:
                st.error("Transcription failed. Check your audio file and API key.")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    elif uploaded_file and not title:
        st.warning("Please enter a meeting title before transcribing.")


def render_record_tab():
    st.subheader("Record from Microphone")
    st.info(
        "To use live recording, install streamlit-webrtc. "
        "For now, use the Upload tab to upload a pre-recorded meeting file."
    )
    st.write(
        "Tip: Record your Zoom or Google Meet call using the built-in "
        "recording feature, then upload the file here."
    )
