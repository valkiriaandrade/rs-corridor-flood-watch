"""Page 1 · Corridor flood-potential forecast (executive)."""
import json

import altair as alt
import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st

from . import ui_theme as T
from .exposure import ACTIONS, ACTIONS_EN, NODES

from .rules import run_rules
from .paths import ROOT, STUDY, FORECAST as FC, SPATIAL
CORRIDORS = ['116', '386', '290']
CORRIDOR_SHARE = 0.20


def model_hit_rate():
    """Share of heavy-rain days (>= 20 mm) each model forecast correctly, mean of D+1..D+3 (forecast_skill.json)."""
    path = ROOT / 'data' / 'processed' / 'forecast_skill' / 'forecast_skill.json'
    if not path.exists():
        return {}
    r = json.loads(path.read_text(encoding='utf-8'))['primary']['by_model_lead']
    names = {'ECMWF IFS': 'ECMWF', 'GFS': 'GFS'}
    return {names.get(m, m): sum(r[m][n]['POD20'] for n in ('1', '2', '3')) / 3 for m in r}


def view_options():
    """Scenario labels in the current language -> internal scenario values (ECMWF first: best verified model)."""
    hit = model_hit_rate()
    lab = lambda m: f'{m} ({T.num(hit[m] * 100, 0)}%)' if m in hit else m
    return {lab('ECMWF'): 'ECMWF', lab('GFS'): 'GFS',
            T.tr('Consenso (ambos os modelos)', 'Consensus (both models)'): 'consensus'}


def rule_skill(results, ix):
    """Out-of-sample skill of the operational rule (index + frozen 3-day trigger, second_trigger.json) or, if the
    trigger test has not been run, of the index alone (results.json). Returns (scores, with_trigger, 2025 descriptive)."""
    path = STUDY / 'second_trigger.json'
    if path.exists():
        g = json.loads(path.read_text(encoding='utf-8'))
        t25 = g.get('test_2025_descriptive', {}).get(ix, {}).get('with_P3')
        return g['designs']['LOYO'][ix]['with_P3'], True, t25
    return results['out_of_sample']['LOYO'][ix], False, None


def river_skill(ix, with_trigger):
    """Same rule scored against gauged river floods (river_validation.json): (scores, municipalities) or (None, None)."""
    path = STUDY / 'river_validation.json'
    if not path.exists():
        return None, None
    v = json.loads(path.read_text(encoding='utf-8'))
    return v['scores'].get(f'{ix}_bacia_rule' if with_trigger else f'{ix}_bacia'), v['municipalities']


def rule_text(thr, fv, ix):
    """'EDI ≥ 1,26 ou chuva de 3 dias ≥ 61 mm' (Watch condition) in the current language."""
    base = f'{ix} ≥ {fv(thr["attention"])}'
    if thr.get('trigger_p3_mm') is None:
        return base
    return base + T.tr(f' ou chuva de 3 dias ≥ {T.num(thr["trigger_p3_mm"], 0)} mm', f' or 3-day rain ≥ {T.num(thr["trigger_p3_mm"], 0)} mm')


def index_labels():
    return {'EDI': 'EDI', 'API': 'API'}


def fmt_index(v, ix, refs=None):
    """EDI is dimensionless (2 decimals); the API is in mm (1 decimal).

    refs = {'attention': thr, 'alert': thr}: a value below a threshold that rounds to it (122.435 vs a 122.446 mm
    Warning, both '122,4') is flagged as just below it, so the number never contradicts the level shown next to it."""
    if pd.isna(v):
        return '–'
    d = 1 if ix == 'API' else 2
    s = f'{T.num(v, d)} mm' if ix == 'API' else T.num(v, d)
    for name, r in (refs or {}).items():
        if r is not None and v < r and round(v, d) >= round(r, d):
            s += (T.tr(' (logo abaixo do limiar de alerta)', ' (just below the Warning threshold)') if name == 'alert'
                  else T.tr(' (logo abaixo do limiar de atenção)', ' (just below the Watch threshold)'))
    return s


def model_skill_section():
    """Which forecast model was more accurate (archived runs 2024-2026 vs MERGE observed rainfall)."""
    path = ROOT / 'data' / 'processed' / 'forecast_skill' / 'forecast_skill.json'
    if not path.exists():
        return
    r = json.loads(path.read_text(encoding='utf-8'))['primary']
    best = r['ranking'][0]
    other = [m for m in r['models'] if m != best][0]
    d = r['best_vs_others'][other]
    sus = r.get('suspect', {})
    p0, p1 = (pd.Timestamp(x) for x in r['period'])
    sig = r['best_is_significant']
    head = T.tr(f'Qual modelo acertou mais · {p0:%m/%Y}–{p1:%m/%Y}', f'Which model was more accurate · {p0:%b %Y}–{p1:%b %Y}')
    st.markdown(f'<div class="section">{head}</div>', unsafe_allow_html=True)
    rows = ''
    for n in ['1', '2', '3', '4', '5']:
        cells = ''
        for m in r['models']:
            x = r['by_model_lead'][m][n]
            if n in sus.get(m, {}):
                cells += '<td class="muted">–*</td><td class="muted">–*</td><td class="muted">–*</td>'
                continue
            cells += (f'<td><b>{T.num(x["ETS20"], 2)}</b></td><td>{T.num(x["POD20"]*100, 0)}%</td>'
                      f'<td>{T.num(x["bias"]*100 - 100, 0, True)}%</td>')
        rows += f'<tr><td>D+{n}</td>{cells}</tr>'
    hdr = ''.join(f'<th colspan="3">{m}</th>' for m in r['models'])
    sub = ''.join(T.tr('<th>ETS</th><th>Detecção ≥20 mm</th><th>Viés</th>', '<th>ETS</th><th>Detection ≥20 mm</th><th>Bias</th>')
                  for _ in r['models'])
    ev = r['event_days']
    # 3 decimals: means and difference must add up on screen (0,345 − 0,286 = 0,059)
    verdict = (T.tr(f'<b>{best}</b> acertou mais a chuva forte (≥ 20 mm/dia) de D+1 a D+3: ETS {T.num(r["primary"][best], 3)} '
                    f'contra {T.num(r["primary"][other], 3)} do {other} (diferença {T.num(d["diff"], 3, True)}; IC95% '
                    f'{T.num(d["CI95"][0], 3, True)} a {T.num(d["CI95"][1], 3, True)}).',
                    f'<b>{best}</b> forecast heavy rain (≥ 20 mm/day) better from D+1 to D+3: ETS {T.num(r["primary"][best], 3)} '
                    f'versus {T.num(r["primary"][other], 3)} for {other} (difference {T.num(d["diff"], 3, True)}; 95% CI '
                    f'{T.num(d["CI95"][0], 3, True)} to {T.num(d["CI95"][1], 3, True)}).') if sig else
               T.tr(f'Sem diferença comprovada entre {best} e {other} (diferença {T.num(d["diff"], 3, True)}; IC95% '
                    f'{T.num(d["CI95"][0], 3, True)} a {T.num(d["CI95"][1], 3, True)}).',
                    f'No proven difference between {best} and {other} (difference {T.num(d["diff"], 3, True)}; 95% CI '
                    f'{T.num(d["CI95"][0], 3, True)} to {T.num(d["CI95"][1], 3, True)}).'))
    e1b, e1o = ev[best]['1'], ev[other]['1']
    a, b = st.columns([1.25, 1])
    with a:
        st.markdown(f'<div class="card"><table class="t"><tr><th rowspan="2">{T.tr("Antecedência", "Lead")}</th>{hdr}</tr>'
                    f'<tr>{sub}</tr>{rows}</table></div>', unsafe_allow_html=True)
    with b:
        st.markdown(
            f'<div class="card"><p>{verdict}</p><p>' + T.tr(
                f'Nos dias com registro oficial de inundação, os dois subestimaram a chuva de 3 dias: o {best} previu '
                f'{T.num(e1b["fc3_over_obs3"]*100, 0)}% da chuva observada e o {other}, {T.num(e1o["fc3_over_obs3"]*100, 0)}% (D+1). '
                f'O {best} tem viés úmido no total, mas detecta mais os dias de chuva forte. '
                f'<b>Uso sugerido:</b> {best} como referência principal; o {other} como segunda opinião.',
                f'On days with an official flood record, both underestimated the 3-day rainfall: {best} forecast '
                f'{T.num(e1b["fc3_over_obs3"]*100, 0)}% of the observed rain and {other} {T.num(e1o["fc3_over_obs3"]*100, 0)}% (D+1). '
                f'{best} has a wet bias in totals but detects more heavy-rain days. '
                f'<b>Suggested use:</b> {best} as the main reference; {other} as a second opinion.') + '</p>'
            + '<p class="note">' + T.tr(
                f'Rodadas arquivadas (Open-Meteo, rodadas anteriores) × chuva observada MERGE, {r["boxes"]} caixas de 0,5° sobre os corredores, '
                f'dia 12–12 UTC. ETS = escore equitativo de acerto (0 = sorte, 1 = perfeito). IC por bootstrap em blocos mensais. '
                f'Critério registrado antes dos resultados. ECMWF na saída aberta de 0,25°. *GFS D+5: série do arquivo incompleta, não interpretada. '
                f'Avalia a chuva prevista, não os níveis de inundação.',
                f'Archived runs (Open-Meteo previous runs) vs MERGE observed rainfall, {r["boxes"]} 0.5° boxes over the corridors, '
                f'12–12 UTC day. ETS = equitable threat score (0 = chance, 1 = perfect). CI from monthly block bootstrap. '
                f'Criterion registered before the results. ECMWF as the 0.25° open-data output. *GFS D+5: incomplete archive series, not interpreted. '
                f'This scores forecast rainfall, not flood levels.') + '</p></div>', unsafe_allow_html=True)


def dm(d):
    """Short day/month for display in the current language."""
    return pd.Timestamp(d).strftime(T.tr('%d/%m', '%d %b'))


def dmy(d):
    return pd.Timestamp(d).strftime(T.tr('%d/%m/%Y', '%d %b %Y'))


@st.cache_data(show_spinner=False)
def load(run_key):
    run = ROOT / json.loads((FC / 'latest.json').read_text(encoding='utf-8'))['run']
    meta = json.loads((run / 'metadata.json').read_text(encoding='utf-8'))
    df = pd.read_csv(run / 'municipal_levels.csv', parse_dates=['date'], dtype={'codarea': str})
    units = gpd.read_file(STUDY / 'units.geojson')
    units['codarea'] = units.codarea.astype(str)
    roads = gpd.read_file(SPATIAL / 'snv202404_corridors_rs.geojson')
    results = json.loads((STUDY / 'results.json').read_text(encoding='utf-8'))
    return meta, df, units, roads, results


def combine(df, view):
    # forecast days plus the last observed day (usually today: MERGE day D ends 12 UTC = 09h Brasília of D)
    last_obs = df.loc[df.source == 'observado', 'date'].max()
    f = df[(df.source == 'previsão') | (df.date == last_obs)]
    if view in ('ECMWF', 'GFS'):
        return f[f.model == view][['date', 'codarea', 'nome', 'corridors', 'level', 'P3', 'VAL']]
    piv = f.pivot_table(index=['date', 'codarea', 'nome', 'corridors'], columns='model', values='level').reset_index()
    agg = piv[['ECMWF', 'GFS']].min(axis=1) if view == 'consensus' else piv[['ECMWF', 'GFS']].max(axis=1)
    piv['level'] = agg.fillna(-1).astype(int)
    # values shown next to the level follow the same scenario (min for consensus, max for worst case)
    extra = f.groupby(['date', 'codarea'])[['P3', 'VAL']].agg('min' if view == 'consensus' else 'max').reset_index()
    return piv.merge(extra, on=['date', 'codarea'])


def corridor_table(levels):
    rows = []
    for br in CORRIDORS:
        sub = levels[levels.corridors.str.split('/').apply(lambda x: br in x)]
        for day, g in sub.groupby('date'):
            # Display rule (not validated): highest level present in >= 20% of the corridor municipalities.
            valid = g[g.level >= 0]
            share_att, share_alert = (valid.level >= 1).mean(), (valid.level == 2).mean()
            level = -1 if valid.empty else (2 if share_alert >= CORRIDOR_SHARE else (1 if share_att >= CORRIDOR_SHARE else 0))
            rows.append({'BR': 'BR-' + br, 'date': day, 'level': level,
                         'n_att': int((g.level >= 1).sum()), 'n_alert': int((g.level == 2).sum()), 'n': len(g)})
    return pd.DataFrame(rows)


def deck(units, roads, levels_day, nodes, ix='EDI', refs=None):
    u = units.merge(levels_day[['codarea', 'level', 'P3', 'VAL']], on='codarea', how='left')
    u['level'] = u.level.fillna(-1).astype(int)
    u['fill'] = u.level.map(lambda l: T.LEVEL_RGB[l] + [165] if l >= 0 else [184, 194, 206, 90])
    u['nivel'] = u.level.map(lambda l: T.level_names()[l] if l >= 0 else T.nodata_name().lower())
    u['P3t'] = u.P3.map(lambda v: f'{T.num(v,0)} mm' if pd.notna(v) else '–')
    u['EDIt'] = u.VAL.map(lambda v: fmt_index(v, ix, refs))
    geo = json.loads(u[['nome', 'corridors', 'nivel', 'P3t', 'EDIt', 'fill', 'geometry']].to_json())
    paths = [{'path': [list(c) for c in (g.coords if g.geom_type == 'LineString' else [p for l in g.geoms for p in l.coords])],
              'br': 'BR-' + br} for g, br in zip(roads.geometry, roads.Codigo_BR)]
    layers = [
        pdk.Layer('GeoJsonLayer', geo, pickable=True, stroked=True, filled=True, get_fill_color='properties.fill',
                  get_line_color=[255, 255, 255, 230], line_width_min_pixels=0.7),
        pdk.Layer('PathLayer', paths, get_path='path', get_color=[31, 58, 95, 235], width_min_pixels=2.4, pickable=False),
        pdk.Layer('ScatterplotLayer', nodes, get_position='[lon, lat]', get_radius=4200, radius_min_pixels=5,
                  get_fill_color=[15, 27, 45, 235], get_line_color=[255, 255, 255], stroked=True, line_width_min_pixels=1.2,
                  pickable=True),
    ]
    tooltip = {'html': '<b>{nome}</b> {municipio}<br/>{nivel} {tipo}<br/>P3: {P3t} · ' + ix + ': {EDIt}<br/>{corridors} {rota}',
               'style': {'backgroundColor': T.C['panel'], 'color': T.C['text'], 'fontSize': '12px'}}
    view = pdk.ViewState(latitude=-30.0, longitude=-52.6, zoom=5.9, pitch=0)
    return pdk.Deck(layers=layers, initial_view_state=view, tooltip=tooltip,
                    map_style='https://basemaps.cartocdn.com/gl/positron-gl-style/style.json')


def timeline(ctab_by_model):
    data = pd.concat([t.assign(model=m) for m, t in ctab_by_model.items()])
    data['nivel'] = data.level.map(T.level_name)
    data['dia'] = data.date.map(dm)
    data['linha'] = data.BR + ' · ' + data.model
    day_order = list(dict.fromkeys(data.sort_values('date').dia))
    chart = alt.Chart(data).mark_rect(cornerRadius=3, stroke=T.C['bg'], strokeWidth=2).encode(
        x=alt.X('dia:O', title=None, sort=day_order,
                axis=alt.Axis(labelColor=T.C['muted'], labelAngle=0)),
        y=alt.Y('linha:N', title=None, axis=alt.Axis(labelColor=T.C['text'], labelLimit=160)),
        color=alt.Color('nivel:N', scale=alt.Scale(domain=T.level_names() + [T.nodata_name()], range=T.LEVEL_COLOR + [T.C['nodata']]), legend=None),
        tooltip=[alt.Tooltip('linha:N', title=T.tr('Corredor · modelo', 'Corridor · model')),
                 alt.Tooltip('dia:O', title=T.tr('Dia (12 UTC)', 'Day (12 UTC)')),
                 alt.Tooltip('nivel:N', title=T.tr('Nível', 'Level')),
                 alt.Tooltip('n_att:Q', title=T.tr('Municípios ≥ atenção', 'Municipalities ≥ Watch')),
                 alt.Tooltip('n_alert:Q', title=T.tr('Municípios em alerta', 'Municipalities at Warning'))])
    text = chart.mark_text(fontSize=11, fontWeight='bold').encode(
        text=alt.Text('n_att:Q'), color=alt.condition(alt.datum.nivel == T.level_names()[1], alt.value('#0F1B2D'), alt.value('#FFFFFF')))
    return (chart + text).properties(height=34 * data.linha.nunique()).configure_view(stroke=None).configure(background=T.C['panel']).configure_axis(labelColor=T.C['text'], domain=False, ticks=False)


def render():
    T.apply()
    if not (FC / 'latest.json').exists():
        st.warning(T.tr('Previsão por corredor ainda não gerada. Rode `python -m floodwatch.forecast`.',
                        'Corridor forecast not generated yet. Run `python -m floodwatch.forecast`.'))
        return
    meta, df, units, roads, results = load(str((FC / 'latest.json').stat().st_mtime))
    # index: EDI or API; runs made before the API was added only have the EDI
    rules = run_rules(meta)
    has_api = 'level_api' in df and 'API' in rules
    if '_ix' not in st.session_state:
        st.session_state['_ix'] = 'API' if str(st.query_params.get('ix', '')) == 'API' and has_api else 'EDI'
    ix = st.session_state['_ix'] if has_api else 'EDI'
    if ix == 'API':
        df = df.assign(level=df.level_api, VAL=df.API)
    else:
        df = df.assign(VAL=df.EDI)
    thr = rules[ix]
    fv = lambda v: fmt_index(v, ix, {'attention': thr['attention'], 'alert': thr['alert']})
    created = pd.Timestamp(meta['created_utc'])
    age_h = (pd.Timestamp.now(tz='UTC') - created).total_seconds() / 3600
    if age_h > 36:
        st.warning(T.tr(f'Previsão gerada há {age_h:.0f} h ({created:%d/%m %H:%M} UTC). Atualize com: python -m floodwatch.forecast',
                        f'Forecast generated {age_h:.0f} h ago ({created:%d %b %H:%M} UTC). Update with: python -m floodwatch.forecast'))
    states = meta.get('antecedent_product_last_30d', {})
    weak = {k: n for k, n in states.items() if k not in ('final', 'late')}
    missing = 30 - sum(states.values())
    # The newest 1-2 days are normally still 'early' (CPTEC replaces them with 'late' later): that is not worth a warning.
    if sum(weak.values()) > 2 or set(weak) - {'early'} or missing > 0:
        days_word = lambda n: T.tr('dia' if n == 1 else 'dias', 'day' if n == 1 else 'days')
        parts = ([f'{n} {days_word(n)} {k}' for k, n in weak.items()]
                 + ([f'{missing} {days_word(missing)} {T.tr("sem dado", "missing")}'] if missing > 0 else []))
        st.info(T.tr('Chuva observada dos últimos 30 dias incompleta ou muito preliminar (', 'Observed rainfall of the last 30 days is incomplete or very preliminary (')
                + ', '.join(parts) + T.tr('). Os níveis podem mudar quando o CPTEC publicar a versão consolidada.',
                                          '). Levels may change when CPTEC publishes the consolidated version.'))
    oos, with_trigger, rule25 = rule_skill(results, ix)
    river, n_river = river_skill(ix, with_trigger)
    v25 = (json.loads((STUDY / 'validation_2025.json').read_text(encoding='utf-8')).get(f'{ix}_attention')
           if (STUDY / 'validation_2025.json').exists() else None)  # pre-registered 2025 test (index threshold only)

    run_fmt = T.tr('%d/%m %H UTC', '%d %b %H UTC')
    st.markdown(
        f'<div class="topbar"><div><div class="title">{T.tr("Monitor de Potencial de Inundação · Corredores Rodoviários RS", "Flood Potential Monitor · RS Highway Corridors")}</div>'
        f'<div class="sub">BR-116 · BR-386 · BR-290 · {len(units)} {T.tr("municípios · próximos dias", "municipalities · coming days")}</div></div>'
        f'<div class="badges"><span class="badge">ECMWF <b>{pd.Timestamp(meta["runs"]["ECMWF"]).strftime(run_fmt)}</b></span>'
        f'<span class="badge">GFS <b>{pd.Timestamp(meta["runs"]["GFS"]).strftime(run_fmt)}</b></span>'
        f'<span class="badge" title="{T.tr("Último arquivo diário MERGE/CPTEC publicado (12 UTC a 12 UTC). Depois disso, a página usa a previsão.", "Last published MERGE/CPTEC daily file (12 UTC to 12 UTC). After that, the page uses the forecast.")}">'
        f'{T.tr("Chuva observada até", "Observed rainfall up to")} <b>{dm(meta["observed_cutoff"])} 12 UTC</b></span>'
        f'<span class="badge">{T.tr("Atenção", "Watch")} <b>{rule_text(thr, fv, ix)}</b> · {T.tr("Alerta", "Warning")} <b>{ix} ≥ {fv(thr["alert"])}</b></span></div></div>', unsafe_allow_html=True)

    VIEW = view_options()
    c1, c2 = st.columns([1.2, 1])
    vals = list(VIEW.values())
    asked_view = str(st.query_params.get('cen', ''))
    if has_api:
        c1.radio(T.tr('Índice de potencial de inundação', 'Flood-potential index'), ['EDI', 'API'], key='_ix',
                 format_func=index_labels().get, horizontal=True,
                 help=T.tr('EDI: Effective Drought Index (Byun & Wilhite, 1999), baseado na precipitação efetiva, memória de 365 dias. '
                           'API: índice de precipitação antecedente (Kohler & Linsley, 1951), memória de cerca de um mês. '
                           'Os dois são calculados com a chuva observada até o último dia MERGE e, depois, com a chuva prevista pelo modelo escolhido.',
                           'EDI: Effective Drought Index (Byun & Wilhite, 1999), based on effective precipitation, 365-day memory. '
                           'API: antecedent precipitation index (Kohler & Linsley, 1951), memory of about one month. '
                           'Both use observed rainfall up to the last MERGE day and then the rainfall forecast by the chosen model.'))
    view_label = c1.radio(T.tr('Modelo de previsão meteorológica (chuva prevista)', 'Weather forecast model (forecast rainfall)'),
                          list(VIEW), horizontal=True,
                          index=vals.index(asked_view) if asked_view in vals else 0,
                          help=T.tr('ECMWF IFS (centro europeu) e NOAA GFS (EUA): modelos globais determinísticos, rodada das 12 UTC, via Open-Meteo. '
                                    'Fornecem a chuva prevista para os próximos dias, somada na janela de 12 a 12 UTC e agregada na bacia a '
                                    'montante de cada município. Consenso = menor nível entre os dois modelos (só alerta se ambos indicarem). '
                                    'O % é o acerto histórico de cada modelo nos dias de chuva forte; o ECMWF acertou mais na verificação de 2024–2026.',
                                    'ECMWF IFS (European centre) and NOAA GFS (USA): deterministic global models, 12 UTC run, via Open-Meteo. '
                                    'They provide the forecast rainfall for the coming days, summed over the 12-12 UTC window and aggregated over '
                                    'each municipality’s upstream basin. Consensus = the lower level of the two models (warns only if both agree). '
                                    'The % is each model’s historical hit rate on heavy-rain days; ECMWF scored better in the 2024–2026 verification.'))
    if model_hit_rate():
        c1.caption(T.tr('% = acerto histórico dos dias de chuva forte (≥ 20 mm), D+1 a D+3, rodadas de 2024–2026 × chuva observada.',
                        '% = historical hit rate on heavy-rain days (≥ 20 mm), D+1 to D+3, 2024–2026 runs vs observed rainfall.'))
    levels = combine(df, VIEW[view_label])
    days = sorted(levels.date.unique())
    ctab = corridor_table(levels)

    peak = ctab.groupby('BR')['level'].max()
    worst_day = ctab.sort_values(['level', 'n_att'], ascending=False).iloc[0] if len(ctab) else None
    mun_peak = levels.groupby('codarea')['level'].max()
    share = f'{T.num(CORRIDOR_SHARE*100, 0)}%'

    def corridor_detail(min_level):
        pairs = []
        for br in CORRIDORS:
            t = ctab[ctab.BR == 'BR-' + br]
            hit = t[t.level >= min_level]
            if len(hit):
                d0, d1 = dm(hit.date.min()), dm(hit.date.max())
                span = d0 if d0 == d1 else f'{d0}–{d1}'
                n = len(hit)
                txt = f'{T.chip(int(hit.level.max()))} {span} · {n} {T.tr("dia" if n == 1 else "dias", "day" if n == 1 else "days")}'
            else:
                txt = T.tr('não atinge', 'not reached')
            pairs.append((f'BR-{br}', txt))
        if T.lang() == 'en':
            rule = ('Warning' if min_level == 2 else 'Watch or Warning')
            return (T.detail_rows(pairs) + f'<p class="note" style="margin-top:6px">A corridor enters {rule} on a day when at least '
                    f'{share} of its municipalities are at that level (display rule, not validated). Scenario: {T.esc(view_label)}.</p>')
        rule = ('alerta' if min_level == 2 else 'atenção ou alerta')
        return (T.detail_rows(pairs) + f'<p class="note" style="margin-top:6px">Um corredor entra em {rule} no dia em que pelo menos '
                f'{share} dos seus municípios estão nesse nível (regra de exibição, não validada). Cenário: {T.esc(view_label)}.</p>')

    first = (levels[levels.level >= 1].sort_values('date').groupby('nome')
             .agg(dia=('date', 'first'), pico=('level', 'max')).sort_values(['dia', 'pico'], ascending=[True, False]))
    mun_detail = (T.tr('<p class="note">Nenhum município em atenção no horizonte.</p>',
                       '<p class="note">No municipality at Watch within the horizon.</p>') if first.empty else
                  T.tr('<p class="note">Data = primeiro dia em atenção no horizonte.</p>',
                       '<p class="note">Date = first day at Watch within the horizon.</p>')
                  + T.detail_rows([(n, f'{T.chip(int(x.pico))} {dm(x.dia)}') for n, x in first.head(25).iterrows()])
                  + (T.tr(f'<p class="note">… e mais {len(first) - 25}.</p>', f'<p class="note">… and {len(first) - 25} more.</p>')
                     if len(first) > 25 else ''))
    if worst_day is not None and worst_day.level > 0:
        wd = levels[levels.date == worst_day.date]
        on_br = wd[wd.corridors.str.split('/').apply(lambda x: worst_day.BR[3:] in x)]
        top = on_br.sort_values('VAL', ascending=False).iloc[0] if on_br.VAL.notna().any() else None
        crit_detail = T.detail_rows([
            (T.tr('Corredor', 'Corridor'), f'{worst_day.BR} · {T.level_name(int(worst_day.level))}'),
            (T.tr('Municípios ≥ atenção', 'Municipalities ≥ Watch'), f'{worst_day.n_att}/{worst_day.n}'),
            (T.tr('Municípios em alerta', 'Municipalities at Warning'), f'{worst_day.n_alert}'),
            (T.tr(f'Maior {ix}', f'Highest {ix}'),
             f'{fv(top.VAL)} · {T.esc(top.nome)}' if top is not None else '–'),
            (T.tr('Rede inteira', 'Whole network'),
             f'{int((wd.level >= 1).sum())} {T.tr("de", "of")} {wd.codarea.nunique()}'),
        ]) + T.tr(f'<p class="note" style="margin-top:6px">Atenção: {rule_text(thr, fv, ix)}. Alerta: {ix} ≥ {fv(thr["alert"])}. '
                  f'Dia com o maior nível de corredor; empate desfeito pelo número de municípios em atenção.</p>',
                  f'<p class="note" style="margin-top:6px">Watch: {rule_text(thr, fv, ix)}. Warning: {ix} ≥ {fv(thr["alert"])}. '
                  f'Day with the highest corridor level; ties broken by the number of municipalities at Watch.</p>')
    else:
        crit_detail = T.tr('<p class="note">Nenhum dia com corredor em atenção neste cenário.</p>',
                           '<p class="note">No day with a corridor at Watch in this scenario.</p>')
    skill_rows = [(T.tr('Detectados 2013–24 (S2iD)', 'Detected 2013–24 (S2iD)'),
                   f'{T.num(oos["POD"]*100,0)}% ({T.num(oos["POD_CI95"][0]*100,0)}–{T.num(oos["POD_CI95"][1]*100,0)}%)'),
                  (T.tr('Atenção sem evento', 'Watch, no event'), f'{T.num(oos["POFD"]*100,1)}%'),
                  ('TSS 2013–24', f'{T.num(oos["TSS"],2)} ({T.num(oos["TSS_CI95"][0],2)}–{T.num(oos["TSS_CI95"][1],2)})')]
    if v25:
        skill_rows.append((T.tr('Teste 2025 · só o limiar do índice', '2025 test · index threshold only'),
                           f'{T.num(v25["POD"]*100,0)}% · TSS {T.num(v25["TSS"],2)}'))
    if rule25:
        skill_rows.append((T.tr('2025 · regra com gatilho (descritivo)', '2025 · rule with trigger (descriptive)'),
                           f'{T.num(rule25["POD"]*100,0)}% · TSS {T.num(rule25["TSS"],2)}'))
    skill_detail = T.detail_rows(skill_rows) + T.s2id_vs_rivers(oos, river, n_river) + T.tr(
        '<p class="note" style="margin-top:6px">Entre parênteses, IC95%. Medido com chuva <b>observada</b> (MERGE), deixando um ano '
        'de fora por vez. Com chuva <b>prevista</b>, o acerto dos níveis tende a ser menor e não foi medido; a chuva prevista foi verificada abaixo (ECMWF × GFS).</p>',
        '<p class="note" style="margin-top:6px">In brackets, 95% CI. Measured with <b>observed</b> rainfall (MERGE), leaving one year '
        'out at a time. With <b>forecast</b> rainfall, the skill of the levels is likely lower and has not been measured; forecast rainfall is verified below (ECMWF vs GFS).</p>')
    has_crit = worst_day is not None and worst_day.level > 0
    T.kpis([
        (T.tr('Corredores em alerta', 'Corridors at Warning'), f'{int((peak == 2).sum())}/3',
         T.tr('algum dia do horizonte', 'on any day in the horizon'), corridor_detail(2)),
        (T.tr('Corredores em atenção', 'Corridors at Watch'), f'{int((peak >= 1).sum())}/3',
         T.tr('atenção ou alerta', 'Watch or Warning'), corridor_detail(1)),
        (T.tr('Municípios afetados', 'Affected municipalities'), f'{int((mun_peak >= 1).sum())}',
         T.tr(f'de {len(mun_peak)} no horizonte', f'of {len(mun_peak)} within the horizon'), mun_detail),
        (T.tr('Dia crítico', 'Critical day'), dm(worst_day.date) if has_crit else '—',
         worst_day.BR if has_crit else T.tr('sem atenção prevista', 'no Watch forecast'), crit_detail),
        (T.tr('Acerto histórico (chuva observada)', 'Historical hit rate (observed rainfall)'), f'{T.num(oos["POD"]*100,0)}%',
         T.tr('S2iD 2013–2024, fora da amostra', 'S2iD 2013–2024, out-of-sample')
         + (T.tr(f' · cheia dos rios (ANA): {T.num(river["POD"]*100,0)}%', f' · river floods (ANA): {T.num(river["POD"]*100,0)}%') if river else '')
         + (T.tr(f' · teste 2025: {T.num(v25["POD"]*100,0)}%', f' · 2025 test: {T.num(v25["POD"]*100,0)}%') if v25 else '')
         if (v25 or river) else
         T.tr(f'eventos detectados fora da amostra · atenção em {T.num(oos["POFD"]*100,1)}% dos dias sem evento',
              f'events detected out-of-sample · Watch on {T.num(oos["POFD"]*100,1)}% of non-event days'), skill_detail),
    ])

    # Day D = 24 h rainfall ending 09h Brasília (12 UTC) of D. The window in progress now is the one ending at the next 09h.
    now_br = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None)
    current = now_br.normalize() + pd.Timedelta(days=1 if now_br.hour >= 9 else 0)
    cutoff = pd.Timestamp(meta['observed_cutoff'])
    default_day = next((d for d in days if pd.Timestamp(d) == current), days[0])
    asked = str(st.query_params.get('dia', ''))
    default_day = next((d for d in days if pd.Timestamp(d).strftime('%Y-%m-%d') == asked), default_day)
    opened = str(st.query_params.get('abrir', ''))

    def window_label(d):
        d = pd.Timestamp(d)
        tag = (T.tr(' · observado', ' · observed') if d <= cutoff else
               T.tr(' · previsão (em curso)', ' · forecast (in progress)') if d == current else T.tr(' · previsão', ' · forecast'))
        return T.tr('até ', 'to ') + T.day_label(d) + ' 09h' + tag

    day = c2.select_slider(T.tr('Dia', 'Day'), options=days, value=default_day, format_func=window_label,
                           label_visibility='collapsed')
    c2.caption(T.tr(f'Cada dia = chuva de 24 h que termina às 09h de Brasília (12 UTC) da data, convenção MERGE/CPTEC usada na calibração. '
                    f'Observada até {dm(cutoff)} 09h; daí em diante, previsão.',
                    f'Each day = 24 h rainfall ending at 09:00 Brasília time (12 UTC) on that date, the MERGE/CPTEC convention used in calibration. '
                    f'Observed up to {dm(cutoff)} 09:00; forecast from then on.'))

    en = T.lang() == 'en'
    left, right = st.columns([2.1, 1])
    with left:
        nodes = []
        names = units.set_index('nome')
        for n in NODES:
            if n['municipio'] in names.index:
                g = names.loc[n['municipio']].geometry.representative_point()
                nodes.append({**n, 'tipo': n['tipo_en'] if en else n['tipo'], 'lon': g.x, 'lat': g.y})
        st.pydeck_chart(deck(units, roads, levels[levels.date == day], nodes, ix, {'attention': thr['attention'], 'alert': thr['alert']}), height=520)
        T.legend()
    with right:
        st.markdown('<div class="section">' + T.tr('Situação por corredor', 'Status by corridor') + ' · ' + dm(day) + '</div>',
                    unsafe_allow_html=True)
        for br in CORRIDORS:
            t = ctab[(ctab.BR == 'BR-' + br)]
            today = t[t.date == day]
            lvl = int(today.level.iloc[0]) if len(today) else 0
            pk = t.sort_values(['level', 'n_att'], ascending=False).iloc[0] if len(t) else None
            hubs = [n['municipio'] for n in nodes if br in n['rota']
                    and levels[(levels.date == day) & (levels.nome == n['municipio'])].level.max() >= 1]
            on_br = levels[levels.corridors.str.split('/').apply(lambda x: br in x)]
            # day strip: each day is a link that selects that day for the whole page (map, cards and lists)
            active = on_br[(on_br.date == day) & (on_br.level >= 1)].sort_values(['level', 'VAL'], ascending=False)
            lst = (T.detail_rows([(a.nome, f'{T.chip(int(a.level))} {ix} {fv(a.VAL)} · P3 {T.num(a.P3,0)} mm')
                                  for a in active.itertuples()]) if len(active) else
                   T.tr('<p class="note">Nenhum município em atenção neste dia.</p>',
                        '<p class="note">No municipality at Watch on this day.</p>'))
            labels = ''
            for x in t.sort_values('date').itertuples():
                fg = T.LEVEL_TEXT[int(x.level)] if x.level >= 0 else T.C['text']
                href = f'?dia={pd.Timestamp(x.date):%Y-%m-%d}&lang={T.lang()}&abrir={br}&cen={VIEW[view_label]}&ix={ix}'
                labels += (f'<a class="daychip{" sel" if x.date == day else ""}" href="{href}" target="_self" '
                           f'title="{T.day_label(x.date)}: {T.level_name(int(x.level))} · {x.n_att}/{x.n}" '
                           f'style="background:{T.level_color(int(x.level))};color:{fg}">{pd.Timestamp(x.date):%d}</a>')
            day_block = (f'<div class="daystrip">{labels}</div>'
                         f'<p class="note" style="margin:0 0 6px 0">{T.tr("Clique em um dia para selecioná-lo na página.", "Click a day to select it on the page.")}</p>'
                         f'<div class="section">{T.tr("Municípios em atenção ou alerta", "Municipalities at Watch or Warning")} · {T.day_label(day)}</div>{lst}')
            st.markdown(
                f'<details class="card corr more"{" open" if opened == br else ""} style="--lvl:{T.level_color(lvl)}"><summary><div class="row"><h4>BR-{br}</h4>{T.chip(lvl)}</div>'
                f'<div class="row"><span>{T.tr("Municípios ≥ atenção", "Municipalities ≥ Watch")}</span><b>{int(today.n_att.iloc[0]) if len(today) else 0}/{int(today.n.iloc[0]) if len(today) else 0}</b></div>'
                f'<div class="row"><span>{T.tr("Pico no horizonte", "Peak within the horizon")}</span><b>{T.level_name(int(pk.level)) if pk is not None else "—"}'
                f'{" · " + dm(pk.date) if pk is not None and pk.level > 0 else ""}</b></div>'
                f'<div class="row"><span>{T.tr("Polos expostos", "Exposed hubs")}</span><b>{", ".join(hubs) if hubs else T.tr("nenhum", "none")}</b></div>'
                f'<div class="action">{T.esc(T.tr(ACTIONS[lvl], ACTIONS_EN[lvl]))}</div><span class="hint">{T.tr("ver municípios e dias", "view municipalities and days")}</span></summary>'
                f'<div class="d"><div class="section" style="margin-top:0">{T.tr("Nível do corredor por dia", "Corridor level by day")}</div>'
                f'{day_block}'
                + T.tr(f'<p class="note" style="margin-top:6px">Valores do cenário {T.esc(view_label)}. '
                       + ('API = índice de precipitação antecedente (Kohler &amp; Linsley, 1951), k = 0,90' if ix == 'API' else
                          'EDI = índice baseado na precipitação efetiva') +
                       f' (atenção: {rule_text(thr, fv, ix)}); P3 = chuva acumulada em 3 dias. Chuva = média da bacia a montante do município (ottobacias ANA).</p></div></details>',
                       f'<p class="note" style="margin-top:6px">Values for the {T.esc(view_label)} scenario. '
                       + ('API = antecedent precipitation index (Kohler &amp; Linsley, 1951), k = 0.90' if ix == 'API' else
                          'EDI = effective precipitation-based index') +
                       f' (Watch: {rule_text(thr, fv, ix)}); P3 = 3-day accumulated rainfall. Rainfall = mean over the municipality’s upstream basin (ANA Otto-coded basins).</p></div></details>'),
                unsafe_allow_html=True)

    st.markdown('<div class="section">' + T.tr('Linha do tempo · corredor × dia · número = municípios em atenção ou alerta',
                                               'Timeline · corridor × day · number = municipalities at Watch or Warning') + '</div>',
                unsafe_allow_html=True)
    by_model = {m: corridor_table(combine(df, m)) for m in ('ECMWF', 'GFS')}
    st.altair_chart(timeline(by_model), width='stretch')
    model_skill_section()

    a, b = st.columns([1.3, 1])
    with a:
        st.markdown('<div class="section">' + T.tr('Feed de alertas · municípios · ', 'Alert feed · municipalities · ') + T.day_label(day) + '</div>',
                    unsafe_allow_html=True)
        feed = levels[(levels.date == day) & (levels.level >= 1)].sort_values(['level', 'VAL'], ascending=[False, False])
        if feed.empty:
            st.markdown('<div class="card note">' + T.tr(f'Nenhum município em atenção ou alerta em {T.day_label(day)} neste cenário.',
                                                         f'No municipality at Watch or Warning on {T.day_label(day)} in this scenario.') + '</div>',
                        unsafe_allow_html=True)
        else:
            # first day of the current continuous Watch-or-above spell, to tell new entries from ongoing ones
            act = levels[levels.level >= 1]
            def since(code):
                ds = sorted(act[(act.codarea == code) & (act.date <= day)].date)
                start = ds[-1] if ds else day
                for d in reversed(ds[:-1]):
                    if (start - d).days == 1:
                        start = d
                    else:
                        break
                return start
            first_day = min(levels.date)
            rows = []
            for r in feed.head(20).itertuples():
                st0 = since(r.codarea)
                n_days = (pd.Timestamp(day) - pd.Timestamp(st0)).days + 1
                prev = levels[(levels.codarea == r.codarea) & (levels.date == pd.Timestamp(day) - pd.Timedelta(days=1))].level
                prev = int(prev.iloc[0]) if len(prev) else None
                if prev is not None and prev < int(r.level) and prev >= 1:
                    tag = T.tr('subiu de nível', 'escalated')
                elif n_days == 1 and day != first_day:
                    tag = T.tr('novo', 'new')
                else:
                    tag = T.tr(f'{n_days}º dia', f'day {n_days}')
                rows.append(f'<div class="feed-item"><span><b>{dm(day)}</b><br><span class="muted" style="font-size:.76rem">{tag}</span></span>'
                            f'<span><b>{T.esc(r.nome)}</b> · BR-{T.esc(r.corridors)}<br><span class="muted">P3 {T.num(r.P3,0)} mm · {ix} {fv(r.VAL)}</span></span>'
                            f'{T.chip(int(r.level))}</div>')
            more = (T.tr(f'<p class="note">… e mais {len(feed) - 20}.</p>', f'<p class="note">… and {len(feed) - 20} more.</p>') if len(feed) > 20 else '')
            st.markdown(f'<div class="card">{"".join(rows)}{more}</div>', unsafe_allow_html=True)
    with b:
        st.markdown('<div class="section">' + T.tr('Como ler', 'How to read') + '</div>', unsafe_allow_html=True)
        att = rule_text(thr, fv, ix)
        alr = f'{ix} ≥ {fv(thr["alert"])}'
        lift_path = STUDY / ('level_lift.json' if ix == 'EDI' else f'level_lift_{ix}.json')
        lift = json.loads((lift_path if lift_path.exists() else STUDY / 'level_lift.json').read_text(encoding='utf-8'))
        lift_att = T.num(lift['atencao']['lift_vs_base'], 1)
        lift_alr = T.num(lift['alerta']['lift_vs_base'], 1)
        npos = results['n']['positives']
        if en:
            how = (f'<div class="card"><div class="row"><span>Watch</span><b>{att} · {lift_att}× the average of all days</b></div>'
                   f'<div class="row"><span>Warning</span><b>{alr} · {lift_alr}× the average of all days</b></div>'
                   f'<p class="note" style="margin-top:8px">Thresholds were calibrated and tested out-of-sample against {npos} official flood '
                   f'events (S2iD, 2013–2024) and MERGE observed rainfall. In the forecast they inherit the error of the '
                   f'weather model: compare ECMWF and GFS. The level indicates conditions under which an official flood record has '
                   f'historically occurred in the municipality, not certainty of a road closure. Details on the <b>Threshold study</b> page.</p>'
                   + ('<p class="note"><b>API:</b> <code>antecedent_precipitation_index</code> from <code>climate-indices</code> 3.0.0 with the '
                      'library defaults (k = 0.90), thresholds in mm calibrated with the same procedure as the EDI.</p>'
                      if ix == 'API' else '') + '</div>')
        else:
            how = (f'<div class="card"><div class="row"><span>Atenção</span><b>{att} · {lift_att}× a média de todos os dias</b></div>'
                   f'<div class="row"><span>Alerta</span><b>{alr} · {lift_alr}× a média de todos os dias</b></div>'
                   f'<p class="note" style="margin-top:8px">Os limiares foram calibrados e testados fora da amostra com {npos} eventos oficiais '
                   f'de inundação (S2iD, 2013–2024) e chuva observada MERGE. Na previsão, eles herdam o erro do modelo '
                   f'meteorológico: compare ECMWF e GFS. O nível indica condição em que historicamente houve registro de '
                   f'inundação no município, e não a certeza de interdição. Detalhes na página <b>Estudo do limiar</b>.</p>'
                   + ('<p class="note"><b>API:</b> <code>antecedent_precipitation_index</code> do <code>climate-indices</code> 3.0.0 com os '
                      'padrões da biblioteca (k = 0,90), limiares em mm calibrados pelo mesmo procedimento do EDI.</p>'
                      if ix == 'API' else '') + '</div>')
        st.markdown(how, unsafe_allow_html=True)
        from .briefing import briefing_pdf, daily_rain
        pdf = briefing_pdf({**meta, 'thresholds': {**thr, 'predictor': ix}}, levels, ctab, results, f'{view_label} · {index_labels()[ix]}', units=units,
                           roads=roads, lang=T.lang(), ctab_by_model=by_model, rain=daily_rain(df, days))
        st.download_button(T.tr('Baixar briefing executivo (PDF)', 'Download executive briefing (PDF)'), pdf,
                           file_name=T.tr('briefing-potencial-inundacao-corredores-rs.pdf', 'rs-corridor-flood-potential-briefing.pdf'), mime='application/pdf', width='stretch')
    st.markdown(T.tr('<p class="note" style="margin-top:14px">Previsão: ECMWF IFS (ECMWF open data, CC BY 4.0) e NOAA GFS via '
                     '<a href="https://open-meteo.com" target="_blank">Open-Meteo.com</a> (CC BY 4.0). Chuva observada: MERGE/CPTEC-INPE. '
                     'Municípios: IBGE. Rodovias: DNIT SNV. Mapa: © OpenStreetMap contributors © CARTO. Estudo independente; '
                     'para alertas oficiais, siga a Defesa Civil, o CEMADEN e o SGB.</p>',
                     '<p class="note" style="margin-top:14px">Forecast: ECMWF IFS (ECMWF open data, CC BY 4.0) and NOAA GFS via '
                     '<a href="https://open-meteo.com" target="_blank">Open-Meteo.com</a> (CC BY 4.0). Observed rainfall: MERGE/CPTEC-INPE. '
                     'Municipalities: IBGE. Roads: DNIT SNV. Map: © OpenStreetMap contributors © CARTO. Independent study; '
                     'for official warnings follow Defesa Civil, CEMADEN and SGB.</p>'), unsafe_allow_html=True)
