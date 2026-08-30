"""Visual system for the Ninja console.

One place for colour, type and chrome, so the Streamlit UI and the Plotly charts
are demonstrably the same design rather than two things that happen to sit on the
same page.

Typography: SF Pro where it exists (macOS, iOS, or a Windows machine that has it
installed), falling back to Inter — the open UI face designed in that same
lineage — so the console looks the same everywhere. Numbers everywhere use
tabular figures, because a monitoring readout whose digits shift width as they
update reads as sloppy.

The severity palette is imported from ``components`` rather than redefined: it is
the same scale the twin reasons with, and duplicating it here is how the two
quietly drift apart.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# --------------------------------------------------------------------- tokens

BG = "#0B0E13"          # page
BG_ELEV = "#12161D"     # cards, expanders
BG_INPUT = "#161B23"    # form controls
BG_HOVER = "#1A2029"
BORDER = "#1F2630"      # hairlines
BORDER_STRONG = "#2C3644"

TEXT = "#E8ECF1"
TEXT_DIM = "#8D9AAB"
TEXT_MUTE = "#5B6B7A"

ACCENT = "#6E9FE0"      # interactive chrome only — never a severity signal
ACCENT_DIM = "#3E5F87"

# Severity colours live in components.py; re-exported so callers have one import.
from .components import SEVERITY_SCALE, UNSEEN_OUTLINE  # noqa: E402

HEALTHY = SEVERITY_SCALE[0][1]
CRITICAL = SEVERITY_SCALE[-1][1]

FONT_SANS = ('"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, '
             '"Inter", "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif')
FONT_MONO = ('ui-monospace, "SF Mono", "SFMono-Regular", "JetBrains Mono", '
             '"Cascadia Mono", Consolas, monospace')

GRID = "#1A212B"

PLOTLY_TEMPLATE = "ninja"


# ------------------------------------------------------------------ plotly

def register_plotly_template() -> str:
    """Register the dark chart template and return its name."""
    template = go.layout.Template()
    template.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT_SANS, "size": 12.5, "color": TEXT_DIM},
        title={"font": {"family": FONT_SANS, "size": 15, "color": TEXT}},
        xaxis={
            "gridcolor": GRID, "zerolinecolor": BORDER, "linecolor": BORDER,
            "tickfont": {"size": 11.5, "color": TEXT_MUTE},
            "title": {"font": {"size": 12, "color": TEXT_DIM}},
            "showline": True, "ticks": "outside", "tickcolor": BORDER, "ticklen": 4,
        },
        yaxis={
            "gridcolor": GRID, "zerolinecolor": BORDER, "linecolor": BORDER,
            "tickfont": {"size": 11.5, "color": TEXT_MUTE},
            "title": {"font": {"size": 12, "color": TEXT_DIM}},
            "showline": False, "ticks": "",
        },
        legend={
            "font": {"size": 11.5, "color": TEXT_DIM},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
        },
        hoverlabel={
            "bgcolor": BG_ELEV, "bordercolor": BORDER_STRONG,
            "font": {"family": FONT_SANS, "size": 12, "color": TEXT},
        },
        colorway=[ACCENT, HEALTHY, SEVERITY_SCALE[2][1], SEVERITY_SCALE[3][1],
                  CRITICAL, UNSEEN_OUTLINE],
        margin={"l": 56, "r": 24, "t": 28, "b": 44},
    )
    pio.templates[PLOTLY_TEMPLATE] = template
    return PLOTLY_TEMPLATE


# --------------------------------------------------------------------- css

def _css() -> str:
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
  --nj-bg: {BG}; --nj-elev: {BG_ELEV}; --nj-input: {BG_INPUT};
  --nj-border: {BORDER}; --nj-border-strong: {BORDER_STRONG};
  --nj-text: {TEXT}; --nj-dim: {TEXT_DIM}; --nj-mute: {TEXT_MUTE};
  --nj-accent: {ACCENT}; --nj-accent-dim: {ACCENT_DIM};
  --nj-hover: {BG_HOVER};
  --nj-sans: {FONT_SANS};
  --nj-mono: {FONT_MONO};
}}

html, body, [data-testid="stApp"], .stApp {{
  background: var(--nj-bg);
  font-family: var(--nj-sans);
  color: var(--nj-text);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-feature-settings: "cv05" 1, "ss03" 1;
}}

/* Tabular figures everywhere a number is read, so digits never shift width. */
[data-testid="stMetricValue"], [data-testid="stSliderThumbValue"],
[data-testid="stSliderTickBar"], code, pre, .nj-num, table {{
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}}

/* ---- chrome ---------------------------------------------------------- */
[data-testid="stHeader"] {{ background: transparent; height: 2.4rem; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stAppDeployButton"] {{ display: none; }}
[data-testid="stMainBlockContainer"] {{
  padding: 1.6rem 3rem 5rem 3rem;
  max-width: 1560px;
}}

/* ---- sidebar --------------------------------------------------------- */
[data-testid="stSidebar"] {{
  background: #090C11;
  border-right: 1px solid var(--nj-border);
}}
[data-testid="stSidebarUserContent"] {{ padding-top: 1.2rem; }}
[data-testid="stSidebar"] hr {{
  border-color: var(--nj-border); margin: 1.1rem 0;
}}

/* ---- typography ------------------------------------------------------ */
h1, h2, h3, h4 {{ font-family: var(--nj-sans); color: var(--nj-text); }}
[data-testid="stMain"] h1 {{
  font-size: 1.42rem; font-weight: 600; letter-spacing: -0.015em;
  padding: 0 0 0.15rem 0;
}}
/* Section headings read as instrument-panel labels, not document headings. */
[data-testid="stMain"] h2, [data-testid="stMain"] h3 {{
  font-size: 0.715rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.105em; color: var(--nj-dim);
  padding: 1.75rem 0 0.5rem 0; margin: 0 0 0.75rem 0;
  border-bottom: 1px solid var(--nj-border);
}}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
  color: var(--nj-mute); font-size: 0.795rem; line-height: 1.55;
}}
[data-testid="stMarkdownContainer"] p {{ font-size: 0.885rem; line-height: 1.62; }}
[data-testid="stMarkdownContainer"] strong {{ color: var(--nj-text); font-weight: 600; }}
code {{
  font-family: var(--nj-mono) !important; font-size: 0.79rem !important;
  background: var(--nj-input) !important; color: #9CC4F0 !important;
  border: 1px solid var(--nj-border); border-radius: 4px; padding: 0.08rem 0.34rem;
}}

/* ---- metrics --------------------------------------------------------- */
[data-testid="stMetric"] {{
  background: var(--nj-elev);
  border: 1px solid var(--nj-border);
  border-radius: 10px;
  padding: 0.85rem 1rem 0.9rem 1rem;
}}
[data-testid="stMetricLabel"] p {{
  font-size: 0.7rem !important; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.075em; color: var(--nj-mute) !important;
}}
[data-testid="stMetricValue"] {{
  font-size: 1.95rem; font-weight: 600; letter-spacing: -0.03em;
  color: var(--nj-text); line-height: 1.15;
}}

/* ---- tabs ------------------------------------------------------------ */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: 0.35rem; border-bottom: 1px solid var(--nj-border);
  background: transparent; padding-bottom: 0;
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  height: 2.5rem; padding: 0 0.95rem; background: transparent;
  font-size: 0.845rem; font-weight: 500; color: var(--nj-mute);
  border-radius: 6px 6px 0 0;
}}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {{
  color: var(--nj-text); background: var(--nj-elev);
}}
[data-testid="stTabs"] [aria-selected="true"] {{ color: var(--nj-text) !important; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background: var(--nj-accent); height: 2px; }}
[data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none; }}

/* ---- expanders (the alert feed) -------------------------------------- */
[data-testid="stExpander"] {{
  background: var(--nj-elev);
  border: 1px solid var(--nj-border);
  border-radius: 9px;
  margin-bottom: 0.42rem;
  overflow: hidden;
}}
[data-testid="stExpander"] summary {{
  padding: 0.62rem 0.9rem; font-size: 0.815rem; font-weight: 450;
  color: var(--nj-dim);
}}
[data-testid="stExpander"] summary:hover {{ background: var(--nj-hover); color: var(--nj-text); }}
[data-testid="stExpanderDetails"] {{ border-top: 1px solid var(--nj-border); padding-top: 0.7rem; }}

/* ---- json / evidence blocks ------------------------------------------ */
[data-testid="stJson"] {{
  background: #0D1117 !important; border: 1px solid var(--nj-border);
  border-radius: 8px; font-family: var(--nj-mono) !important; font-size: 0.775rem !important;
}}

/* ---- inputs ---------------------------------------------------------- */
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
  background: var(--nj-input); border: 1px solid var(--nj-border);
  border-radius: 8px; font-size: 0.845rem; color: var(--nj-text);
}}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:hover,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:hover {{
  border-color: var(--nj-border-strong);
}}
[data-testid="stWidgetLabel"] p {{
  font-size: 0.715rem !important; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.07em; color: var(--nj-mute) !important;
}}
[data-baseweb="tag"] {{
  background: #24374F !important; color: #CFE0F5 !important;
  border-radius: 5px !important; font-size: 0.76rem !important;
}}

/* ---- buttons --------------------------------------------------------- */
[data-testid="stBaseButton-secondary"] {{
  background: var(--nj-input); border: 1px solid var(--nj-border);
  color: var(--nj-dim); border-radius: 7px; font-size: 0.8rem; font-weight: 500;
  transition: border-color .12s ease, color .12s ease;
}}
[data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--nj-accent); color: var(--nj-text); background: var(--nj-input);
}}
[data-testid="stBaseButton-primary"] {{
  background: var(--nj-accent); border: none; color: #06090D;
  border-radius: 7px; font-size: 0.83rem; font-weight: 600;
}}
[data-testid="stBaseButton-primary"]:hover {{ background: #8AB4EA; color: #06090D; }}

/* ---- charts ---------------------------------------------------------- */
[data-testid="stPlotlyChart"] {{
  background: var(--nj-elev); border: 1px solid var(--nj-border);
  border-radius: 10px; padding: 0.45rem 0.3rem 0.2rem 0.3rem;
}}

/* ---- dataframes ------------------------------------------------------ */
[data-testid="stDataFrame"] {{ border: 1px solid var(--nj-border); border-radius: 9px; }}

/* ---- scrollbars ------------------------------------------------------ */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: #232C38; border-radius: 6px; border: 2px solid var(--nj-bg); }}
::-webkit-scrollbar-thumb:hover {{ background: #303B4A; }}

/* ---- custom components ----------------------------------------------- */
.nj-brand {{ display: flex; align-items: baseline; gap: .5rem; margin-bottom: .1rem; }}
.nj-brand-mark {{ font-size: 1.15rem; color: var(--nj-accent); }}
.nj-brand-name {{ font-size: 1.05rem; font-weight: 600; letter-spacing: -0.01em; color: var(--nj-text); }}

.nj-title {{ margin: 0 0 .15rem 0; }}
.nj-title-main {{
  font-size: 1.32rem; font-weight: 600; letter-spacing: -.022em; color: var(--nj-text);
}}
.nj-title-meta {{
  font-size: .765rem; color: var(--nj-mute); margin-top: .28rem;
  display: flex; gap: .55rem; flex-wrap: wrap; align-items: center;
}}
.nj-chip {{
  border: 1px solid var(--nj-border-strong); border-radius: 5px;
  padding: .07rem .4rem; font-size: .705rem; color: var(--nj-dim);
  font-variant-numeric: tabular-nums;
}}

.nj-cards {{ display: flex; gap: .6rem; margin: .2rem 0 .5rem 0; }}
.nj-cards > * {{ flex: 1 1 0; min-width: 0; }}
.nj-card {{
  background: var(--nj-elev); border: 1px solid var(--nj-border);
  border-radius: 10px; padding: .8rem .95rem .85rem .95rem; position: relative; overflow: hidden;
}}
.nj-card::before {{
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 2px;
  background: transparent;
}}
.nj-t-healthy::before  {{ background: {SEVERITY_SCALE[0][1]}; }}
.nj-t-caution::before  {{ background: {SEVERITY_SCALE[1][1]}; }}
.nj-t-warning::before  {{ background: {SEVERITY_SCALE[2][1]}; }}
.nj-t-elevated::before {{ background: {SEVERITY_SCALE[3][1]}; }}
.nj-t-critical::before {{ background: {SEVERITY_SCALE[4][1]}; }}
.nj-t-unseen::before   {{ background: {UNSEEN_OUTLINE}; }}
.nj-card-label {{
  font-size: .675rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .085em; color: var(--nj-mute); margin-bottom: .34rem;
}}
.nj-card-value {{
  font-size: 1.85rem; font-weight: 600; letter-spacing: -.032em;
  color: var(--nj-text); line-height: 1.1; font-variant-numeric: tabular-nums;
}}
.nj-card-sub {{ font-size: .715rem; color: var(--nj-mute); margin-top: .28rem; }}

.nj-pill {{
  display: inline-block; padding: .09rem .42rem; border-radius: 4px;
  font-size: .665rem; font-weight: 600; letter-spacing: .05em;
  text-transform: uppercase; border: 1px solid currentColor; opacity: .95;
}}
.nj-note {{
  border-left: 2px solid var(--nj-border-strong); padding: .1rem 0 .1rem .75rem;
  color: var(--nj-mute); font-size: .78rem; line-height: 1.55;
}}
"""


def apply(page_title: str = "Ninja") -> str:
    """Inject the stylesheet and register the chart template. Call once, first."""
    st.markdown(f"<style>{_css()}</style>", unsafe_allow_html=True)
    return register_plotly_template()


# ------------------------------------------------------------- components

TONES = ("healthy", "caution", "warning", "elevated", "critical", "unseen")


def metric_cards(cards: list[dict]) -> None:
    """A row of headline figures.

    Each card is ``{"label", "value", "sub"?, "tone"?}`` where ``tone`` is one of
    :data:`TONES`, rendered as a thin left rule. Severity is carried by that rule
    rather than by colouring the number, so the figure stays legible and the page
    does not turn into a traffic light.

    Tone is applied as a CSS class, not an inline style: Streamlit's markdown
    sanitiser strips ``style`` attributes, so inline custom properties silently
    do nothing.
    """
    html = ['<div class="nj-cards">']
    for card in cards:
        tone = card.get("tone")
        cls = f"nj-card nj-t-{tone}" if tone in TONES else "nj-card"
        sub = f'<div class="nj-card-sub">{card["sub"]}</div>' if card.get("sub") else ""
        html.append(
            f'<div class="{cls}">'
            f'<div class="nj-card-label">{card["label"]}</div>'
            f'<div class="nj-card-value">{card["value"]}</div>{sub}</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def page_title(title: str, chips: list[str] | None = None) -> None:
    """The run header. Distinct from section headings, which render as labels."""
    parts = [f'<div class="nj-title"><div class="nj-title-main">{title}</div>']
    if chips:
        pills = "".join(f'<span class="nj-chip">{c}</span>' for c in chips)
        parts.append(f'<div class="nj-title-meta">{pills}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def note(text: str) -> None:
    """A quiet aside, for methodology caveats that should not shout."""
    st.markdown(f'<div class="nj-note">{text}</div>', unsafe_allow_html=True)


def brand() -> None:
    st.markdown(
        '<div class="nj-brand"><span class="nj-brand-mark">◧</span>'
        '<span class="nj-brand-name">Ninja</span></div>',
        unsafe_allow_html=True,
    )
