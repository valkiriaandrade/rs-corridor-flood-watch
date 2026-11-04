"""Visual system for the executive app: corporate light palette (navy, slate, muted status)."""
import html

import streamlit as st

C = {
    'bg': '#F4F6F9', 'panel': '#FFFFFF', 'panel2': '#EEF2F7', 'border': '#DCE3EB',
    'text': '#0F1B2D', 'muted': '#5B6B7F', 'accent': '#1F3A5F', 'accent2': '#2E5E8C', 'header': '#0F1B2D',
    'normal': '#3F8A6B', 'atencao': '#D3961E', 'alerta': '#B83A3A', 'nodata': '#B8C2CE',
    'ECMWF': '#1F6FB2', 'GFS': '#7A4FB3', 'merge': '#0F1B2D',
}
LEVEL_COLOR = [C['normal'], C['atencao'], C['alerta']]
LEVEL_TEXT = ['#FFFFFF', '#0F1B2D', '#FFFFFF']
LEVEL_NAME = ['Normal', 'Atenção', 'Alerta']
LEVEL_RGB = [[63, 138, 107], [211, 150, 30], [184, 58, 58]]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background:{C['bg']}; color:{C['text']};
  font-family:'Inter',system-ui,sans-serif; }}
[data-testid="stHeader"] {{ background:{C['header']}; }}
[data-testid="stHeader"] a, [data-testid="stHeader"] span, [data-testid="stHeader"] p {{ color:#FFFFFF !important; }}
.block-container {{ padding-top:3.6rem; padding-bottom:2rem; max-width:1480px; }}
h1,h2,h3,h4,p,span,label,li,td,th {{ color:{C['text']}; }}
.muted {{ color:{C['muted']} !important; }}
.topbar {{ display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap;
          background:{C['panel']}; border:1px solid {C['border']}; border-top:4px solid {C['accent']};
          border-radius:10px; padding:14px 18px; margin-bottom:14px; }}
.topbar .title {{ font-size:1.35rem; font-weight:700; color:{C['accent']}; letter-spacing:.1px; }}
.topbar .sub {{ color:{C['muted']}; font-size:.86rem; margin-top:2px; }}
.badges {{ display:flex; gap:8px; flex-wrap:wrap; }}
.badge {{ border:1px solid {C['border']}; background:{C['panel2']}; border-radius:999px; padding:3px 10px;
          font-size:.76rem; color:{C['muted']}; white-space:nowrap; }}
.badge b {{ color:{C['text']}; font-weight:600; }}
.badge {{ white-space:normal; max-width:100%; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-bottom:14px; }}
.kpi {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:10px; padding:12px 14px;
        box-shadow:0 1px 2px rgba(15,27,45,.04); }}
.kpi .k {{ color:{C['muted']}; font-size:.72rem; text-transform:uppercase; letter-spacing:.6px; font-weight:600; }}
.kpi .v {{ font-size:1.65rem; font-weight:700; line-height:1.15; margin-top:3px; color:{C['accent']}; }}
.kpi .s {{ color:{C['muted']}; font-size:.78rem; }}
.kpis {{ align-items:start; }}
details.more > summary {{ list-style:none; cursor:pointer; }}
details.more > summary::-webkit-details-marker {{ display:none; }}
details.more {{ transition:box-shadow .15s, border-color .15s; }}
details.more:hover {{ border-color:{C['accent2']}; box-shadow:0 2px 8px rgba(15,27,45,.10); }}
details.more .hint {{ display:inline-block; margin-top:6px; font-size:.72rem; font-weight:600; color:{C['accent2']}; }}
details.more .hint::after {{ content:' ▾'; }}
details.more[open] .hint::after {{ content:' ▴'; }}
details.more[open] .hint {{ color:{C['muted']}; }}
details.more .d {{ border-top:1px solid {C['border']}; margin-top:8px; padding-top:8px; font-size:.8rem; color:{C['text']}; }}
details.more .d p {{ margin:0 0 6px 0; font-size:.8rem !important; line-height:1.45; color:{C['muted']}; }}
details.more .d p b {{ color:{C['text']}; }}
details.more .d .row {{ font-size:.8rem; padding:1px 0; }}
details.more .d .row {{ align-items:flex-start; line-height:1.35; padding:3px 0 !important; }}
details.more .d .row {{ flex-wrap:wrap; column-gap:10px; row-gap:0; }}
details.more .d .row > span:first-child {{ flex:1 1 9em; min-width:9em; white-space:normal; overflow-wrap:normal; word-break:normal; }}
details.more .d .row > b {{ flex:0 1 auto; max-width:100%; white-space:normal; display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-left:auto; text-align:right; }}
details.card.more > summary .row:first-child {{ margin-bottom:2px; }}
.dayradio {{ position:absolute; opacity:0; pointer-events:none; width:0; height:0; }}
.daystrip {{ display:flex; gap:3px; margin-bottom:4px; }}
.daychip {{ flex:1; text-align:center; font-size:.7rem; font-weight:600; padding:4px 0; border-radius:3px; cursor:pointer;
            transition:transform .1s; user-select:none; }}
.daychip:hover {{ transform:translateY(-1px); box-shadow:0 1px 4px rgba(15,27,45,.25); }}
.daypanel {{ display:none; }}
/* language switch lives inside the fixed top bar */
.st-key-_lang_choice {{ position:fixed !important; top:13px; right:22px; z-index:1000002; width:auto !important; }}
.st-key-_lang_choice button {{ background:transparent !important; border:1px solid rgba(255,255,255,.35) !important;
  min-height:30px !important; padding:2px 12px !important; }}
.st-key-_lang_choice button p {{ color:#C9D5E3 !important; font-size:.78rem !important; font-weight:600; }}
.st-key-_lang_choice button[aria-checked="true"] {{ background:rgba(255,255,255,.16) !important; border-color:rgba(255,255,255,.7) !important; }}
.st-key-_lang_choice button[aria-checked="true"] p {{ color:#FFFFFF !important; }}
.daychip.sel {{ outline:2px solid {C['accent']}; outline-offset:1px; }}
a.daychip {{ text-decoration:none !important; }}
.card {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:10px; padding:12px 14px; margin-bottom:10px;
         box-shadow:0 1px 2px rgba(15,27,45,.04); }}
.card h4 {{ margin:0 0 4px 0; font-size:1rem; color:{C['accent']}; }}
.corr {{ border-left:5px solid var(--lvl); }}
.chip {{ display:inline-block; border-radius:5px; padding:2px 9px; font-size:.73rem; font-weight:600;
         color:var(--fg); background:var(--lvl); }}
.row {{ display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:.83rem; color:{C['muted']}; }}
.row h4 {{ margin:0 !important; padding:0 !important; }}
.chip {{ line-height:1.5; align-self:center; flex:0 0 auto; }}
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"], [data-testid="stToolbarActions"] {{ display:none !important; }}
.row b {{ color:{C['text']}; font-weight:600; }}
.action {{ margin-top:8px; font-size:.82rem; background:{C['panel2']}; border-radius:6px; padding:7px 9px; color:{C['text']}; }}
.feed-item {{ display:grid; grid-template-columns:86px 1fr auto; gap:10px; align-items:center;
              border-bottom:1px solid {C['border']}; padding:7px 2px; font-size:.84rem; }}
.feed-item:last-child {{ border-bottom:none; }}
.section {{ font-size:.74rem; text-transform:uppercase; letter-spacing:.8px; color:{C['accent2']}; font-weight:600; margin:8px 0 6px 0; }}
.legend {{ display:flex; gap:14px; flex-wrap:wrap; font-size:.78rem; color:{C['muted']}; margin-top:6px; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:middle; }}
.headline {{ background:{C['accent']}; border-radius:10px; padding:16px 18px; margin-bottom:14px; }}
.headline .q {{ color:#B9C7D8; font-size:.74rem; text-transform:uppercase; letter-spacing:.7px; font-weight:600; }}
.headline .a {{ font-size:1.1rem; font-weight:600; margin-top:4px; color:#FFFFFF; }}
table.t {{ width:100%; border-collapse:collapse; font-size:.84rem; background:{C['panel']}; }}
table.t th {{ color:{C['muted']}; font-weight:600; text-align:left; border-bottom:2px solid {C['border']}; padding:7px 6px; }}
table.t td {{ border-bottom:1px solid {C['border']}; padding:7px 6px; }}
table.t tr.best td {{ background:#E8EFF7; }}
.note {{ color:{C['muted']}; font-size:.8rem; }}
code {{ color:{C['accent2']}; background:{C['panel2']}; white-space:nowrap !important; word-break:keep-all !important; overflow-wrap:normal !important; }}
[data-testid="stTabs"] button p {{ color:{C['muted']}; font-weight:500; }}
[data-testid="stTabs"] button[aria-selected="true"] p {{ color:{C['accent']}; font-weight:600; }}
.stDownloadButton button, .stButton button {{ background:{C['accent']}; color:#FFFFFF; border:1px solid {C['accent']}; }}
.stDownloadButton button p, .stButton button p {{ color:#FFFFFF; }}
.stDownloadButton button:hover, .stButton button:hover {{ background:{C['accent2']}; border-color:{C['accent2']}; color:#FFFFFF; }}
details.more .d table.t {{ font-size:.78rem; }}
details.more .d table.t th, details.more .d table.t td {{ padding:5px 4px; }}
@media (max-width: 700px) {{ table.t {{ display:block; overflow-x:auto; white-space:nowrap; }} details.more .d table.t, table.t.wrap {{ display:table; white-space:normal; font-size:.74rem; }} table.t.wrap th, table.t.wrap td {{ padding:5px 3px; }} .kpi .v {{ font-size:1.3rem; }} .feed-item {{ grid-template-columns:70px 1fr; }} }}
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)


def lang():
    """Current UI language: 'pt' (default) or 'en'."""
    return st.session_state.get('lang', 'pt')


def tr(pt, en):
    """Pick the string for the current language."""
    return en if lang() == 'en' else pt


LEVEL_NAME_EN = ['Normal', 'Watch', 'Warning']


def level_names():
    return LEVEL_NAME_EN if lang() == 'en' else LEVEL_NAME


def nodata_name():
    return tr('Sem dado', 'No data')


def esc(x):
    return html.escape(str(x), quote=True)


def num(x, digits=1, sign=False):
    """Number format of the current language (pt: 1.234,5 · en: 1,234.5)."""
    if x is None or x != x:
        return '–'
    if round(x, digits) == 0:
        x = 0.0  # never print "-0,00"
    s = f'{x:+,.{digits}f}' if sign and x != 0 else f'{x:,.{digits}f}'
    if lang() == 'en':
        return s
    return s.replace(',', '§').replace('.', ',').replace('§', '.')


def kpis(items):
    """items: list of (label, value, sub) or (label, value, sub, detail_html); with detail the card opens on click."""
    cells = ''
    for it in items:
        k, v, s = it[:3]
        body = f'<div class="k">{esc(k)}</div><div class="v">{v}</div><div class="s">{esc(s)}</div>'
        if len(it) > 3 and it[3]:
            cells += (f'<details class="kpi more"><summary>{body}<span class="hint">{tr("ver detalhes", "view details")}</span></summary>'
                      f'<div class="d">{it[3]}</div></details>')
        else:
            cells += f'<div class="kpi">{body}</div>'
    st.markdown(f'<div class="kpis">{cells}</div>', unsafe_allow_html=True)


def detail_rows(pairs):
    """Small key/value list for card details: [(label, value_html), ...]."""
    return ''.join(f'<div class="row"><span>{esc(a)}</span><b>{b}</b></div>' for a, b in pairs)


def s2id_vs_rivers(s2id, river, n_mun):
    """Card detail: the same rule scored against S2iD records and against gauged river floods (n_mun municipalities with a gauge)."""
    if not river:
        return ''
    pct = lambda x, d=0: num(x * 100, d) + '%'
    rows = [(tr('Detecção', 'Detection'), 'POD', 0), (tr('Alarme falso', 'False alarm'), 'POFD', 1)]
    body = ''.join(f'<tr><td>{n}</td><td>{pct(s2id[k], d)}</td><td>{pct(river[k], d)}</td></tr>' for n, k, d in rows)
    body += f'<tr><td>TSS</td><td>{num(s2id["TSS"], 2)}</td><td>{num(river["TSS"], 2)}</td></tr>'
    head = tr('<tr><th></th><th>S2iD</th><th>Rios (ANA)</th></tr>', '<tr><th></th><th>S2iD</th><th>Rivers (ANA)</th></tr>')
    note = tr(f'<p class="note">Mesma regra, dois gabaritos. <b>S2iD</b>: evento = registro de desastre da Defesa Civil, todos os municípios dos corredores, '
              f'limiares escolhidos sem o ano testado. <b>Rios</b>: evento = cota de uma estação da ANA acima da mediana dos máximos anuais, '
              f'{n_mun} municípios com estação, limiares congelados. A detecção é maior nos rios porque o rio só sobe depois de dias de chuva '
              f'acumulada, o que o índice mede; muitos registros do S2iD vêm de chuva forte localizada (alagamento urbano, deslizamento), que o índice não vê. '
              f'Detalhes na aba <b>Nível dos rios</b>.</p>',
              f'<p class="note">Same rule, two answer keys. <b>S2iD</b>: event = Civil Defence disaster record, all corridor municipalities, '
              f'thresholds chosen without the tested year. <b>Rivers</b>: event = an ANA gauge stage above its median annual maximum, '
              f'{n_mun} municipalities with a gauge, frozen thresholds. Detection is higher for rivers because a river only rises after days of '
              f'accumulated rain, which is what the index measures; many S2iD records come from local downpours (urban flooding, landslides), which the index cannot see. '
              f'Details in the <b>River levels</b> tab.</p>')
    return f'<table class="t wrap">{head}{body}</table>{note}'


def level_name(level):
    return level_names()[level] if level >= 0 else nodata_name()


def level_color(level):
    return LEVEL_COLOR[level] if level >= 0 else C['nodata']


def chip(level):
    fg = LEVEL_TEXT[level] if level >= 0 else C['text']
    return f'<span class="chip" style="--lvl:{level_color(level)};--fg:{fg}">{level_name(level)}</span>'


def legend():
    st.markdown('<div class="legend">' + ''.join(
        f'<span><i style="background:{c}"></i>{n}</span>' for c, n in zip(LEVEL_COLOR + [C['nodata']], level_names() + [nodata_name()]))
        + f'<span><i style="background:{C["accent"]}"></i>{tr("Corredor federal", "Federal corridor")}</span>'
        + f'<span>● {tr("Polo logístico/industrial (referência pública)", "Logistics/industrial hub (public reference)")}</span></div>', unsafe_allow_html=True)


WEEKDAYS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
WEEKDAYS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def day_label(d):
    """Short weekday + date in the current language, independent of OS locale."""
    import pandas as pd
    t = pd.Timestamp(d)
    if lang() == 'en':
        return f'{WEEKDAYS_EN[t.weekday()]} {t:%d %b}'
    return f'{WEEKDAYS[t.weekday()]} {t:%d/%m}'
