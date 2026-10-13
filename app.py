"""
Currans Homes - Call Insights portal.

A password-protected Streamlit portal that pulls call records straight from the customer's Grandstream UCM
(no uploads) and shows the call handling dashboard, user assessment and PDF reports.
Configuration lives in Streamlit secrets - see .streamlit/secrets.toml.example.
"""
from __future__ import annotations

import hmac
import time as time_mod
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

import cdr_engine as ce
from ucm_client import UCMClient, UCMConfig, UCMError
from ui import FULL_WIDTH, ICON_PHONE, chip, esc, inject_css, render_html, render_results, run_analysis, section_header

PORTAL = dict(st.secrets.get("portal", {}))
CUSTOMER = PORTAL.get("customer", "Currans Homes")
BRAND = PORTAL.get("brand", "SY Communications")
TZ = ZoneInfo(PORTAL.get("timezone", "Europe/London"))

st.set_page_config(page_title=f"{CUSTOMER} · Call Insights", page_icon="📞", layout="wide")
inject_css()
render_html("""<style>
.pe-live{display:inline-flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--border);
border-radius:999px;padding:8px 16px 8px 12px;font-size:.84rem;font-weight:600;color:var(--text)}
.pe-live .dot{width:9px;height:9px;border-radius:50%;background:var(--good);box-shadow:0 0 0 4px rgba(52,211,153,.18)}
.pe-live.bad .dot{background:var(--bad);box-shadow:0 0 0 4px rgba(248,113,113,.18)}
.pe-live .m{color:var(--muted);font-weight:500}
.pe-step-row{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border);font-size:.88rem}
.pe-step-row:last-child{border-bottom:none}
.pe-step-row .ok{color:var(--good);font-weight:800}.pe-step-row .no{color:var(--bad);font-weight:800}
</style>""")


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Login (fails closed if no users are configured)
# --------------------------------------------------------------------------- #
def _users() -> dict:
    return {str(k).lower(): str(v) for k, v in dict(st.secrets.get("portal_users", {})).items()}


def login_gate():
    users = _users()
    if not users:
        st.error("This portal hasn't been set up yet (no users configured). Please contact SY Communications.")
        st.stop()
    if st.session_state.get("auth_user") in users:
        return st.session_state["auth_user"]
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        render_html(f'<div class="pe-login-head" style="text-align:center;margin:8vh 0 22px">'
                    f'<div class="pe-logo" style="width:54px;height:54px;margin:0 auto 16px;border-radius:16px">'
                    f'{ICON_PHONE}</div><div style="font-size:1.6rem;font-weight:800;letter-spacing:-.03em;'
                    f'color:var(--text)">{esc(CUSTOMER)}</div><div style="color:var(--muted);font-size:.92rem;'
                    f'margin-top:6px">Call Insights portal · provided by {esc(BRAND)}</div></div>')
        with st.container(key="card-login"):
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                go_ = st.form_submit_button("Sign in", type="primary", **FULL_WIDTH)
            if go_:
                fails = st.session_state.get("fails", 0)
                if fails >= 3:
                    time_mod.sleep(min(10, 2 * fails))  # slow down repeated guessing
                expected = users.get(u.strip().lower())
                if expected is not None and hmac.compare_digest(p.encode(), expected.encode()):
                    st.session_state["auth_user"] = u.strip().lower()
                    st.session_state["fails"] = 0
                    st.rerun()
                st.session_state["fails"] = fails + 1
                st.error("That username or password isn't right.")
    st.stop()


user = login_gate()
is_admin = user in [str(a).lower() for a in PORTAL.get("admins", [])]

class _Logo:
    """Optional logo for the PDFs: put the file in the repo and set portal.logo = "assets/logo.png"."""
    def __init__(self, path):
        self.path = path

    def getvalue(self):
        with open(self.path, "rb") as f:
            return f.read()


LOGO = None
if PORTAL.get("logo"):
    import os
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), PORTAL["logo"])
    LOGO = _Logo(_p) if os.path.exists(_p) else None

# --------------------------------------------------------------------------- #
# Live data from the UCM
# --------------------------------------------------------------------------- #
UCM_CFG = dict(st.secrets.get("ucm", {}))


@st.cache_data(ttl=int(PORTAL.get("refresh_minutes", 10)) * 60, show_spinner=False)
def fetch_calls(start_iso: str, end_iso: str, nonce: int):
    client = UCMClient(UCMConfig.from_secrets(UCM_CFG))
    res = client.fetch(datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso))
    df = ce.grandstream_from_table(res.table)
    df["provider"] = "grandstream"
    return df, res.calls, res.method, now_local()


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
REPORT = dict(st.secrets.get("report", {}))
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _t(txt, default):
    try:
        h, m = str(txt).split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return default


with st.sidebar:
    render_html(f'<div class="pe-brand"><div class="pe-logo">{ICON_PHONE}</div><div><div class="n">{esc(CUSTOMER)}'
                f'</div><div class="tg">Call Insights · by {esc(BRAND)}</div></div></div>')
    status_box = st.empty()
    if st.button("Refresh now", **FULL_WIDTH, help="Pull the latest calls from the phone system"):
        st.session_state["nonce"] = st.session_state.get("nonce", 0) + 1
        fetch_calls.clear()
    st.markdown("**Opening hours**")
    slots = [time(h, m) for h in range(24) for m in (0, 15, 30, 45)]
    o_def, c_def = _t(REPORT.get("open", "08:30"), time(8, 30)), _t(REPORT.get("close", "17:30"), time(17, 30))
    c1, c2 = st.columns(2)
    open_t = c1.selectbox("Open", slots, index=slots.index(o_def), format_func=lambda t: t.strftime("%H:%M"))
    close_t = c2.selectbox("Close", slots, index=slots.index(c_def), format_func=lambda t: t.strftime("%H:%M"))
    open_days = st.multiselect("Open days", DAY_NAMES, default=list(REPORT.get("days", DAY_NAMES[:5])))
    with st.expander("Targets & rules"):
        target = st.slider("Answer-rate target %", 70, 100, int(REPORT.get("answer_target", 90)))
        cb_target = st.select_slider("Call-back target", options=[15, 30, 60, 120, 240, 480],
                                     value=int(REPORT.get("callback_target_minutes", 60)),
                                     format_func=lambda m: f"{m} min" if m < 60 else f"{m // 60} hr")
        short_ab = st.number_input("Ignore hang-ups under (seconds)", 0, 30, int(REPORT.get("ignore_hangups_under", 5)))
        excl_txt = st.text_area("Numbers to exclude (one per line)",
                                value="\n".join(REPORT.get("exclude_numbers", [])))
    pdf_style = st.radio("PDF style", ["Portal (dark)", "Print-friendly (light)"])
    st.divider()
    st.caption(f"Signed in as **{esc(user)}**")
    if st.button("Log out", **FULL_WIDTH):
        st.session_state.pop("auth_user", None)
        st.rerun()

settings_tuple = (
    open_t, close_t, tuple(DAY_NAMES.index(d) for d in open_days), int(short_ab), float(target), int(cb_target), 4,
    tuple(x.strip() for x in excl_txt.splitlines() if x.strip()), False,
)

# --------------------------------------------------------------------------- #
# Hero
# --------------------------------------------------------------------------- #
hero = st.empty()

# --------------------------------------------------------------------------- #
# 01 Period
# --------------------------------------------------------------------------- #
today = now_local().date()
with st.container(key="card-period"):
    section_header("01", "Reporting period", "Calls are pulled live from your phone system")
    presets = ["This month", "Last month", "Last 7 days", "Last 30 days", "Today", "Custom"]
    preset = st.radio("Period", presets, horizontal=True, label_visibility="collapsed")
    if preset == "This month":
        p_start, p_end = today.replace(day=1), today
    elif preset == "Last month":
        last = today.replace(day=1) - timedelta(days=1)
        p_start, p_end = last.replace(day=1), last
    elif preset == "Last 7 days":
        p_start, p_end = today - timedelta(days=6), today
    elif preset == "Last 30 days":
        p_start, p_end = today - timedelta(days=29), today
    elif preset == "Today":
        p_start = p_end = today
    else:
        rng = st.date_input("Custom range", (today - timedelta(days=13), today), max_value=today,
                            min_value=today - timedelta(days=int(PORTAL.get("max_history_days", 400))),
                            format="DD/MM/YYYY")
        p_start, p_end = rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (today, today)
    render_html(chip(f"Reporting {p_start:%d %b %Y} → {p_end:%d %b %Y}", "accent")
                + chip("Call-backs are tracked for up to 7 days after the period"))

# pull the period plus up to 7 days after it, so later call-backs are found
f_start = datetime.combine(p_start, time(0, 0))
f_end = datetime.combine(min(today, p_end + timedelta(days=7)), time(23, 59, 59))

df = err = fetched_at = None
n_calls, method = 0, ""
with st.spinner("Pulling calls from your phone system..."):
    try:
        df, n_calls, method, fetched_at = fetch_calls(f_start.isoformat(), f_end.isoformat(),
                                                      st.session_state.get("nonce", 0))
    except UCMError as e:
        err = str(e)
    except Exception as e:  # noqa: BLE001
        err = f"Unexpected error while reading the call records ({e.__class__.__name__}: {e})"

if fetched_at is not None:
    status_box.markdown(f'<div class="pe-live"><span class="dot"></span>Live<span class="m">updated '
                        f'{fetched_at:%H:%M}</span></div>', unsafe_allow_html=True)
else:
    status_box.markdown('<div class="pe-live bad"><span class="dot"></span>Not connected</div>',
                        unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Connection problems / admin tools
# --------------------------------------------------------------------------- #
if err:
    with st.container(key="card-source"):
        section_header("!", "Couldn't reach the phone system", "The report will appear as soon as the connection works")
        st.error(err)
        if not is_admin:
            st.caption(f"Please contact {BRAND} - we'll check the connection for you.")

if is_admin:
    with st.expander("Admin · phone system connection", expanded=bool(err)):
        cfg_view = {k: ("•••••••" if k == "password" else v) for k, v in UCM_CFG.items()}
        st.caption("Settings come from the app's Secrets (the [ucm] section).")
        st.json(cfg_view, expanded=False)
        b1, b2, b3 = st.columns(3)
        steps = None
        if b1.button("Run connection test", **FULL_WIDTH):
            try:
                steps = UCMClient(UCMConfig.from_secrets(UCM_CFG)).test(now_local())
            except Exception as e:  # noqa: BLE001
                steps = [("Configuration", False, f"{e.__class__.__name__}: {e}")]
        if b2.button("Deep check (no login attempts)", **FULL_WIDTH):
            try:
                steps = UCMClient(UCMConfig.from_secrets(UCM_CFG)).diagnose()
            except Exception as e:  # noqa: BLE001
                steps = [("Configuration", False, f"{e.__class__.__name__}: {e}")]
        if b3.button("Try other login formats (4 attempts)", **FULL_WIDTH,
                     help="Each failed attempt can count towards the phone system's lock-out - use sparingly."):
            try:
                steps = UCMClient(UCMConfig.from_secrets(UCM_CFG)).try_login_variants()
            except Exception as e:  # noqa: BLE001
                steps = [("Configuration", False, f"{e.__class__.__name__}: {e}")]
        if steps:
            render_html("".join(f'<div class="pe-step-row"><span class="{"ok" if ok else "no"}">'
                                f'{"✓" if ok else "✕"}</span><div><b>{esc(name)}</b><br>'
                                f'<span style="color:var(--muted)">{esc(msg)}</span></div></div>'
                                for name, ok, msg in steps))
        if fetched_at is not None:
            st.caption(f"Last pull: {n_calls:,} calls via the {'HTTPS API' if method == 'https_api' else 'legacy CDR API'} "
                       f"at {fetched_at:%H:%M}.")
        up = st.file_uploader("Or upload a CDR export instead (admin only)", accept_multiple_files=True)
        if up:
            df = ce.load_many([f.getvalue() for f in up], "grandstream")
            err = None

# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
a = None
if df is not None:
    if df.empty:
        st.info("No calls found for this period yet.")
    else:
        with st.spinner("Analysing calls..."):
            a = run_analysis(df, p_start, p_end, settings_tuple)
        render_results(df, a, p_start, p_end, settings_tuple, CUSTOMER, BRAND, None, LOGO, pdf_style, portal=True,
                       first_num=2)

# --------------------------------------------------------------------------- #
# Hero (rendered last so it shows live status)
# --------------------------------------------------------------------------- #
live = (f'<div class="pe-live"><span class="dot"></span>Live from your phone system'
        f'<span class="m">updated {fetched_at:%H:%M}</span></div>' if fetched_at is not None and not err
        else '<div class="pe-live bad"><span class="dot"></span>Phone system not connected</div>')
render_html(f'<div class="pe-hero"><div><div class="pe-eyebrow"><span class="dot"></span>Call Insights</div>'
            f'<div class="pe-title">{esc(CUSTOMER)} <span>call handling</span></div>'
            f'<div class="pe-sub">How your calls are being answered, which callers were missed, who has been called '
            f'back - and who hasn\'t.</div></div>{live}</div>', hero)
