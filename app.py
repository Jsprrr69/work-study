import json
import sqlite3
import time
from datetime import date, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Work & Study Log", page_icon="⏱️", layout="centered")

DB_PATH = "worklog.db"
STUDY_COLOR, WORK_COLOR = "#2f5bea", "#b86e0c"


# ---------- database ----------
def _con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def run(sql, params=()):
    con = _con()
    con.execute(sql, params)
    con.commit()
    con.close()


def query(sql, params=()):
    con = _con()
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    return rows


def init_db():
    con = _con()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT, subject TEXT, mins REAL, day TEXT);
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, type TEXT, due TEXT, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS checks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT, done INTEGER DEFAULT 0, day TEXT);
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
        """
    )
    con.commit()
    con.close()


init_db()


# ---------- optional password (set APP_PASSWORD in Streamlit secrets) ----------
def check_password():
    try:
        required = st.secrets.get("APP_PASSWORD")
    except Exception:
        required = None
    if not required:
        return
    if st.session_state.get("authed"):
        return
    pw = st.text_input("Password", type="password")
    if pw:
        if pw == required:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


check_password()


# ---------- helpers ----------
def fmt(mins):
    mins = round(mins)
    h, m = divmod(mins, 60)
    return f"{h}h {m}m".replace(" 0m", "") if h else f"{m}m"


def get_running():
    rows = query("SELECT value FROM state WHERE key='running'")
    return json.loads(rows[0]["value"]) if rows else None


def set_running(data):
    if data is None:
        run("DELETE FROM state WHERE key='running'")
    else:
        run("INSERT OR REPLACE INTO state(key,value) VALUES('running',?)", (json.dumps(data),))


def toggle_check(cid, key):
    run("UPDATE checks SET done=? WHERE id=?", (int(st.session_state[key]), cid))


def toggle_task(tid, key):
    run("UPDATE tasks SET done=? WHERE id=?", (int(st.session_state[key]), tid))


today = date.today().isoformat()

st.title("Work & Study Log")
st.caption(date.today().strftime("%A, %B %d"))

tab_today, tab_tasks, tab_week = st.tabs(["Today", "Tasks", "This week"])

# ---------- TODAY ----------
with tab_today:
    running = get_running()

    kind_label = st.radio(
        "Type",
        ["Study", "Work"],
        horizontal=True,
        index=0 if (running or {}).get("type", "study") == "study" else 1,
        disabled=bool(running),
        key="kind_radio",
    )
    kind = kind_label.lower()
    subject = st.text_input(
        "What are you working on?",
        value=(running or {}).get("subject", ""),
        placeholder="e.g. Thesis",
        disabled=bool(running),
        key="subject_input",
    )

    def _clock():
        r = get_running()
        secs = int(time.time() - r["start"]) if r else 0
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        st.markdown(
            f"<div style='font-size:4rem;font-weight:700;font-variant-numeric:tabular-nums'>"
            f"{h}:{m:02d}:{s:02d}</div>",
            unsafe_allow_html=True,
        )

    clock = st.fragment(_clock, run_every=1) if running else st.fragment(_clock)
    clock()

    if not running:
        if st.button("Start timer", type="primary", use_container_width=True):
            set_running({"start": time.time(), "type": kind, "subject": subject.strip()})
            st.rerun()
    else:
        if st.button("Stop and save", type="primary", use_container_width=True):
            mins = (time.time() - running["start"]) / 60
            if mins >= 0.5:
                run(
                    "INSERT INTO sessions(type,subject,mins,day) VALUES(?,?,?,?)",
                    (running["type"], running["subject"] or "General", mins, today),
                )
            set_running(None)
            st.rerun()

    with st.expander("Add a past session"):
        with st.form("past_session", clear_on_submit=True):
            p_subject = st.text_input("Subject")
            p_mins = st.number_input("Minutes", min_value=1, max_value=1440, value=30)
            if st.form_submit_button("Add session"):
                run(
                    "INSERT INTO sessions(type,subject,mins,day) VALUES(?,?,?,?)",
                    (kind, p_subject.strip() or "General", p_mins, today),
                )
                st.rerun()

    # checklist (unfinished items carry over)
    st.subheader("Work checklist")
    with st.form("add_check", clear_on_submit=True):
        c1, c2 = st.columns([5, 1])
        new_item = c1.text_input("Add a checklist item", label_visibility="collapsed",
                                 placeholder="Add a checklist item")
        if c2.form_submit_button("Add") and new_item.strip():
            run("INSERT INTO checks(text,done,day) VALUES(?,0,?)", (new_item.strip(), today))
            st.rerun()

    items = query(
        "SELECT * FROM checks WHERE day=? OR (done=0 AND day<?) ORDER BY id", (today, today)
    )
    if items:
        done_n = sum(i["done"] for i in items)
        st.caption(f"{done_n} of {len(items)} done")
    else:
        st.caption("Nothing on the list. Add what you need to finish today.")
    for it in items:
        a, b = st.columns([9, 1])
        key = f"chk_{it['id']}"
        label = it["text"] + ("  (carried over)" if it["day"] < today else "")
        a.checkbox(label, value=bool(it["done"]), key=key,
                   on_change=toggle_check, args=(it["id"], key))
        if b.button("✕", key=f"delchk_{it['id']}", help="Delete item"):
            run("DELETE FROM checks WHERE id=?", (it["id"],))
            st.rerun()

    # today's sessions
    st.subheader("Today’s sessions")
    sessions = query("SELECT * FROM sessions WHERE day=? ORDER BY id DESC", (today,))
    if not sessions:
        st.caption("No sessions yet. Pick Study or Work and start the timer.")
    for s in sessions:
        a, b, c = st.columns([6, 2, 1])
        a.write(f"**{s['subject']}** · {s['type'].capitalize()}")
        b.write(fmt(s["mins"]))
        if c.button("✕", key=f"dels_{s['id']}", help="Delete session"):
            run("DELETE FROM sessions WHERE id=?", (s["id"],))
            st.rerun()
    if sessions:
        st.write(f"**Total today: {fmt(sum(s['mins'] for s in sessions))}**")

# ---------- TASKS ----------
with tab_tasks:
    with st.form("add_task", clear_on_submit=True):
        t_title = st.text_input("New task")
        c1, c2 = st.columns(2)
        t_type = c1.selectbox("Type", ["Study", "Work"])
        t_due = c2.date_input("Due date", value=None)
        if st.form_submit_button("Add task") and t_title.strip():
            run(
                "INSERT INTO tasks(title,type,due,done) VALUES(?,?,?,0)",
                (t_title.strip(), t_type.lower(), t_due.isoformat() if t_due else "", ),
            )
            st.rerun()

    def render_tasks(rows, empty_msg):
        if not rows:
            st.caption(empty_msg)
        for t in rows:
            a, b = st.columns([9, 1])
            key = f"task_{t['id']}"
            due = ""
            if t["due"]:
                late = (not t["done"]) and t["due"] < today
                due = f" · {'Overdue, ' if late else 'Due '}{t['due']}"
            a.checkbox(f"{t['title']} ({t['type'].capitalize()}){due}",
                       value=bool(t["done"]), key=key,
                       on_change=toggle_task, args=(t["id"], key))
            if b.button("✕", key=f"deltask_{t['id']}", help="Delete task"):
                run("DELETE FROM tasks WHERE id=?", (t["id"],))
                st.rerun()

    st.subheader("To do")
    render_tasks(
        query("SELECT * FROM tasks WHERE done=0 ORDER BY CASE WHEN due='' THEN 1 ELSE 0 END, due"),
        "Nothing due. Add a task above.",
    )
    st.subheader("Done")
    render_tasks(query("SELECT * FROM tasks WHERE done=1 ORDER BY id DESC"),
                 "Finished tasks show up here.")

# ---------- WEEK ----------
with tab_week:
    days = [(date.today() - timedelta(days=i)) for i in range(6, -1, -1)]
    keys = [d.isoformat() for d in days]
    rows = query(
        f"SELECT * FROM sessions WHERE day IN ({','.join('?' * len(keys))})", tuple(keys)
    )
    df = pd.DataFrame(0.0, index=[d.strftime("%a %d") for d in days], columns=["Study", "Work"])
    by_subject = {}
    for r in rows:
        label = date.fromisoformat(r["day"]).strftime("%a %d")
        df.loc[label, r["type"].capitalize()] += r["mins"] / 60
        by_subject[r["subject"]] = by_subject.get(r["subject"], 0) + r["mins"]

    m1, m2 = st.columns(2)
    m1.metric("Study this week", fmt(df["Study"].sum() * 60))
    m2.metric("Work this week", fmt(df["Work"].sum() * 60))
    st.bar_chart(df, color=[STUDY_COLOR, WORK_COLOR], y_label="Hours")

    st.subheader("Time by subject")
    if by_subject:
        for name, mins in sorted(by_subject.items(), key=lambda x: -x[1]):
            a, b = st.columns([4, 1])
            a.write(name)
            b.write(f"**{fmt(mins)}**")
    else:
        st.caption("Log a session to see your breakdown.")
