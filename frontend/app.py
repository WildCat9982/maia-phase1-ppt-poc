"""Maia for PowerPoint POC: Streamlit UI.

Run:  streamlit run frontend/app.py
The backend URL comes from MAIA_BACKEND_URL (default http://localhost:8000).
"""

import json
import os

import httpx
import pandas as pd
import streamlit as st

BACKEND = os.getenv("MAIA_BACKEND_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(300.0, connect=10.0)
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

st.set_page_config(page_title="Maia for PowerPoint POC", page_icon="📊", layout="wide")


# ---- Backend calls --------------------------------------------------------------

def call(method: str, path: str, **kwargs) -> httpx.Response | None:
    try:
        resp = httpx.request(method, f"{BACKEND}{path}", timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"Cannot reach the backend at {BACKEND}: {exc}")
        return None
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text
        st.error(f"Backend error {resp.status_code}: {detail}")
        return None
    return resp


def show_usage(usage: dict | None):
    if not usage:
        return
    cols = st.columns(5)
    cols[0].metric("Model", usage["model"])
    cols[1].metric("LLM calls", usage["calls"])
    cols[2].metric("Prompt tokens", f"{usage['prompt_tokens']:,}")
    cols[3].metric("Output tokens", f"{usage['completion_tokens']:,}")
    cols[4].metric("LLM time", f"{usage['latency_ms'] / 1000:.1f} s")


def cited(points: list[dict]) -> str:
    return "\n".join(
        f"- {p['text']}" + (f"  *(slides {', '.join(map(str, p['slides']))})*" if p["slides"] else "")
        for p in points)


# ---- Sidebar ----------------------------------------------------------------------

with st.sidebar:
    st.title("Maia for PowerPoint")
    st.caption("Proof of concept · Phase 1 features")
    health = call("GET", "/health")
    if health is not None:
        h = health.json()
        st.success(f"Backend connected\n\n**{h['provider']}** · `{h['model']}`")
        st.caption(f"Endpoint: {h['base_url']}  \nPII masking: {'on' if h['mask_pii'] else 'off'}")
    st.divider()
    st.caption("Uploaded files are processed in memory and not stored. Use sanitised decks only "
               "while the POC runs against a public API.")

tab_sum, tab_notes, tab_gen = st.tabs(["1.1 Summarise a deck", "1.3 Speaker notes", "1.2 Prompt to deck"])


# ---- Shared deck upload -------------------------------------------------------

def deck_uploader(key: str):
    upload = st.file_uploader("PowerPoint deck (.pptx)", type=["pptx"], key=key)
    if upload is None:
        return None, None
    data = upload.getvalue()
    cache_key = f"deck::{upload.name}::{len(data)}"
    if st.session_state.get("deck_key") != cache_key:
        resp = call("POST", "/api/ppt/extract", files={"file": (upload.name, data, PPTX_MIME)})
        if resp is None:
            return None, None
        st.session_state.update(deck_key=cache_key, deck=resp.json(), deck_bytes=data,
                                deck_name=upload.name, summary=None, notes=None)
    deck = st.session_state["deck"]
    with st.expander(f"Extracted content: {deck['slide_count']} slides", expanded=False):
        st.dataframe(pd.DataFrame([{
            "Slide": s["index"], "Title": s["title"], "Layout": s["layout"],
            "Body lines": len(s["body"]), "Tables": len(s["tables"]),
            "Has notes": bool(s["notes"]), "Images": s["has_images"]} for s in deck["slides"]]),
            hide_index=True, use_container_width=True)
    return deck, data


# ---- 1.1 Summarise ------------------------------------------------------------------

with tab_sum:
    st.subheader("Summarise a deck")
    st.write("Executive summary, key points, decisions and actions. Every point cites its slides.")
    deck, _ = deck_uploader("sum_upload")
    if deck and st.button("Summarise", type="primary"):
        with st.spinner("Reading the deck…"):
            resp = call("POST", "/api/ppt/summarise", json=deck)
        if resp is not None:
            st.session_state["summary"] = resp.json()
    result = st.session_state.get("summary")
    if deck and result:
        s = result["summary"]
        st.markdown("#### Executive summary")
        st.write(s["executive_summary"])
        for label, key in [("Key points", "key_points"), ("Decisions", "decisions"),
                           ("Action items", "action_items"), ("Open questions", "open_questions")]:
            if s[key]:
                st.markdown(f"#### {label}")
                st.markdown(cited(s[key]))
        st.divider()
        show_usage(result["usage"])


# ---- 1.3 Speaker notes --------------------------------------------------------------

with tab_notes:
    st.subheader("Automatic speaker notes")
    st.write("Generate notes, review and edit them, then download a copy of the deck with the notes added.")
    deck, deck_bytes = deck_uploader("notes_upload")
    if deck:
        c1, c2, c3 = st.columns(3)
        seconds = c1.slider("Seconds per slide", 15, 180, 60, step=15)
        audience = c2.text_input("Audience", "senior management")
        tone = c3.selectbox("Tone", ["Professional", "Friendly", "Collaborative"])
        overwrite = st.checkbox("Replace notes that already exist", value=False)
        if st.button("Generate notes", type="primary"):
            body = {"deck": deck, "seconds_per_slide": seconds, "audience": audience,
                    "tone": tone, "overwrite_existing": overwrite}
            with st.spinner(f"Writing notes for {deck['slide_count']} slides…"):
                resp = call("POST", "/api/ppt/notes", json=body)
            if resp is not None:
                st.session_state["notes"] = resp.json()

        result = st.session_state.get("notes")
        if result:
            titles = {s["index"]: s["title"] for s in deck["slides"]}
            df = pd.DataFrame([{"Slide": n["index"], "Title": titles.get(n["index"], ""),
                                "Notes": n["notes"], "Kept existing": n["skipped"]}
                               for n in result["notes"]])
            st.caption("Edit any note below before writing them into the deck.")
            edited = st.data_editor(
                df, hide_index=True, use_container_width=True, disabled=["Slide", "Title", "Kept existing"],
                column_config={"Notes": st.column_config.TextColumn(width="large")}, key="notes_editor")
            show_usage(result["usage"])
            if st.button("Write notes into a copy of the deck"):
                payload = {str(r["Slide"]): r["Notes"] for r in edited.to_dict("records")}
                resp = call("POST", "/api/ppt/notes/apply",
                            files={"file": (st.session_state["deck_name"], deck_bytes, PPTX_MIME)},
                            data={"notes_json": json.dumps(payload)})
                if resp is not None:
                    st.session_state["notes_file"] = resp.content
            if st.session_state.get("notes_file"):
                name = st.session_state["deck_name"].rsplit(".", 1)[0] + "-with-notes.pptx"
                st.download_button("Download deck with notes", st.session_state["notes_file"],
                                   file_name=name, mime=PPTX_MIME)


# ---- 1.2 Prompt to deck ---------------------------------------------------------------

with tab_gen:
    st.subheader("Prompt to presentation")
    st.write("Describe the deck, review the outline, then render it on your template.")
    prompt = st.text_area("What should the deck cover?",
                          "Brief senior management on extending Maia into PowerPoint")
    with st.expander("Optional: source material (email or document text to ground the deck)"):
        source_text = st.text_area("Source text", height=180, label_visibility="collapsed")
    c1, c2 = st.columns(2)
    count = c1.slider("Content slides", 3, 15, 6)
    audience = c2.text_input("Audience ", "senior management")

    if st.button("Generate outline", type="primary"):
        with st.spinner("Drafting the outline…"):
            resp = call("POST", "/api/ppt/outline", json={
                "prompt": prompt, "source_text": source_text, "slide_count": count, "audience": audience})
        if resp is not None:
            st.session_state["outline"] = resp.json()
            st.session_state.pop("rendered", None)

    result = st.session_state.get("outline")
    if result:
        outline = result["outline"]
        q = result["quality"]
        issues = []
        if q["bullets_over_limit"]:
            issues.append(f"more than 5 bullets on slides {q['bullets_over_limit']}")
        if q["long_bullets"]:
            issues.append(f"bullets over 12 words on slides {q['long_bullets']}")
        if q["empty_slides"]:
            issues.append(f"empty content slides {q['empty_slides']}")
        (st.warning if issues else st.success)(
            "Outline check: " + ("; ".join(issues) if issues else "within the bullet and length limits"))

        st.markdown("#### Review the outline")
        title = st.text_input("Deck title", outline["title"])
        subtitle = st.text_input("Subtitle", outline.get("subtitle", ""))
        edited_slides = []
        for i, s in enumerate(outline["slides"]):
            with st.expander(f"Slide {i + 2}: {s['title']}", expanded=False):
                keep = st.checkbox("Include this slide", True, key=f"keep{i}")
                layout = st.selectbox("Layout", ["bullets", "section"],
                                      index=0 if s["layout"] == "bullets" else 1, key=f"lay{i}")
                s_title = st.text_input("Title", s["title"], key=f"t{i}")
                bullets = st.text_area("Bullets (one per line)", "\n".join(s["bullets"]), key=f"b{i}")
                notes = st.text_area("Speaker notes", s["notes"], key=f"n{i}")
                if keep:
                    edited_slides.append({"layout": layout, "title": s_title, "notes": notes,
                                          "bullets": [b.strip() for b in bullets.splitlines() if b.strip()]})
        show_usage(result["usage"])

        template = st.file_uploader("Template (.potx or .pptx, optional; default is a blank theme)",
                                    type=["potx", "pptx"], key="template")
        if st.button("Render deck"):
            files = {}
            if template is not None:
                files["template"] = (template.name, template.getvalue(), "application/octet-stream")
            final = {"title": title, "subtitle": subtitle, "slides": edited_slides}
            with st.spinner("Building the slides…"):
                resp = call("POST", "/api/ppt/render", data={"outline_json": json.dumps(final)},
                            files=files or None)
            if resp is not None:
                st.session_state["rendered"] = (resp.content, f"{title[:60] or 'deck'}.pptx")
        if st.session_state.get("rendered"):
            content, name = st.session_state["rendered"]
            st.download_button("Download deck", content, file_name=name, mime=PPTX_MIME)
