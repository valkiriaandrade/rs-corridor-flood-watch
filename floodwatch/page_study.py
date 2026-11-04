"""Page 2 · Threshold study: method, validation and limitations."""
import json

import altair as alt
import pandas as pd
import streamlit as st

from . import ui_theme as T

from .paths import STUDY as S
NAMES = {'P1': 'Chuva 1 dia', 'P3': 'Chuva 3 dias', 'P7': 'Chuva 7 dias', 'P30': 'Chuva 30 dias',
         'PE': 'PE (precipitação efetiva)', 'EDI': 'EDI', 'EDI&P3': 'EDI E chuva 3 dias (regra combinada)', 'EDI_alert': 'EDI · nível de alerta', 'MONTH': 'Só o mês (sazonal)',
         'API': 'API (precipitação antecedente)', 'API_alert': 'API · nível de alerta',
         'EDI_bacia': 'EDI da bacia a montante', 'API_bacia': 'API da bacia a montante',
         'EDI_bacia_alert': 'EDI da bacia · alerta', 'API_bacia_alert': 'API da bacia · alerta'}
NAMES_EN = {'P1': '1-day rainfall', 'P3': '3-day rainfall', 'P7': '7-day rainfall', 'P30': '30-day rainfall',
            'PE': 'PE (effective precipitation)', 'EDI': 'EDI', 'EDI&P3': 'EDI AND 3-day rainfall (combined rule)', 'EDI_alert': 'EDI · Warning level', 'MONTH': 'Month only (seasonal)',
            'API': 'API (antecedent precipitation)', 'API_alert': 'API · Warning level',
            'EDI_bacia': 'Upstream-basin EDI', 'API_bacia': 'Upstream-basin API',
            'EDI_bacia_alert': 'Upstream EDI · Warning', 'API_bacia_alert': 'Upstream API · Warning'}
COLORS = {'P1': '#A7B4C4', 'P3': '#6F8FB3', 'P7': '#2E5E8C', 'P30': '#1F3A5F', 'PE': '#7A4FB3', 'EDI': '#1C7C7D', 'API': '#C2571A'}


def fmt_index(v, ix, unit=True):
    """EDI-type indices are dimensionless (2 decimals); API-type indices are in mm."""
    if v is None or pd.isna(v):
        return '–'
    return (f'{T.num(v, 1)} mm' if unit else T.num(v, 1)) if ix.startswith('API') else T.num(v, 2)  # same precision as the forecast page


def proper_name(name):
    """Upper-case ANA names in proper case: 'PONTE DO CAI - BR-386' -> 'Ponte do Cai - BR-386'."""
    small = {'do', 'da', 'dos', 'das', 'de', 'e'}
    words = str(name or '').lower().split()
    out = []
    for i, w in enumerate(words):
        if w.startswith('br-'):
            out.append(w.upper())
        elif i and w in small:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return ' '.join(out)


def ci_verdict(ci):
    lo, hi = ci
    eps, tiny = 1e-9, 0.005  # identical predictions differ by ~1e-17; |TSS| < 0.005 is below the precision shown
    if lo is not None and hi is not None and (lo > eps or hi < -eps) and max(abs(lo), abs(hi)) < tiny:
        return T.tr('diferença desprezível', 'negligible difference')
    if lo is not None and lo > eps:
        return T.tr('melhor', 'better') if lo >= tiny else T.tr('melhor, com o limite inferior do IC logo acima de 0',
                                                                 'better, with the lower CI bound just above 0')
    if hi is not None and hi < -eps:
        return T.tr('pior', 'worse')
    return T.tr('sem diferença comprovada', 'no proven difference')


def suffix(ix):
    return '' if ix == 'EDI' else f'_{ix}'


def names():
    """Display names of the predictors in the current language (keys unchanged)."""
    return NAMES_EN if T.lang() == 'en' else NAMES


def dfmt(d, year=True):
    """Display date in the current language: 14/06/2025 (pt) or 14 Jun 2025 (en)."""
    t = pd.Timestamp(d)
    if T.lang() == 'en':
        return f'{t:%d %b %Y}' if year else f'{t:%d %b}'
    return f'{t:%d/%m/%Y}' if year else f'{t:%d/%m}'


@st.cache_data(show_spinner=False)
def load(key, ix='EDI'):
    r = json.loads((S / 'results.json').read_text(encoding='utf-8'))
    m = json.loads((S / 'data.metadata.json').read_text(encoding='utf-8'))
    roc = pd.read_csv(S / 'roc.csv')
    sx = suffix(ix)
    tl = pd.read_csv(S / f'timeline_2024{sx}.csv', parse_dates=['date'])
    road = pd.read_csv(S / f'road_check{sx}.csv')
    leads = pd.read_csv(S / f'event_leads{sx}.csv', parse_dates=['date'])
    return r, m, roc, tl, road, leads


def load_json(name):
    path = S / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def pct(x, d=0):
    return T.num(x*100, d) + '%'


def render():
    T.apply()
    tr = T.tr
    N = names()
    if not (S / 'results.json').exists():
        st.warning(tr('Estudo ainda não concluído.', 'Study not yet completed.'))
        return
    r0 = json.loads((S / 'results.json').read_text(encoding='utf-8'))
    has_api = 'API' in r0['final_thresholds_all_years'] and (S / 'level_lift_API.json').exists()
    if '_ix_study' not in st.session_state:
        st.session_state['_ix_study'] = 'API' if str(st.query_params.get('ix', '')) == 'API' and has_api else 'EDI'
    ix = st.session_state['_ix_study'] if has_api else 'EDI'
    r, m, roc, tl, road, leads = load(str((S / 'results.json').stat().st_mtime), ix)
    best = ix
    fx = lambda v: fmt_index(v, best)
    loyo = r['out_of_sample']['LOYO']
    hold = r['out_of_sample']['holdout_2013-2020_vs_2021-2024']
    fin = r['final_thresholds_all_years'][best]
    # Operational rule = index threshold OR frozen 3-day trigger (second_trigger.json); index alone if not run yet.
    g = load_json('second_trigger.json')
    trigger = g['final_frozen'][best]['P3_mm'] if g else None
    L = g['designs']['LOYO'][best]['with_P3'] if g else loyo[best]
    H = g['designs']['holdout_2013-2020_vs_2021-2024'][best]['with_P3'] if g else hold[best]
    rv = load_json('river_validation.json')
    RV = (rv or {}).get('scores', {}).get(f'{best}_bacia_rule' if g else f'{best}_bacia')  # same rule as L, river floods as events
    watch_rule = f'{best} ≥ {fx(fin["attention"])}' + (tr(f' ou chuva de 3 dias ≥ {T.num(trigger, 0)} mm',
                                                          f' or 3-day rain ≥ {T.num(trigger, 0)} mm') if trigger else '')

    st.markdown(f'<div class="topbar"><div><div class="title">{tr("Estudo do limiar · potencial de inundação nos corredores", "Threshold study · flood potential along the corridors")}</div>'
                f'<div class="sub">{tr("Protocolo pré-registrado · validação fora da amostra · limitações explícitas", "Pre-registered protocol · out-of-sample validation · explicit limitations")}</div></div></div>',
                unsafe_allow_html=True)
    if has_api:
        st.radio(tr('Índice de potencial de inundação', 'Flood-potential index'), ['EDI', 'API'], key='_ix_study', horizontal=True,
                 format_func={'EDI': 'EDI', 'API': 'API'}.get)
        info = {
            'EDI': tr('<b>EDI · Effective Drought Index</b> (Byun &amp; Wilhite, 1999), baseado na precipitação efetiva: '
                      'PE(d) = Σ<sub>n=1..365</sub> (Σ<sub>m=1..n</sub> chuva<sub>m</sub>) / n, em que chuva<sub>m</sub> é a chuva de m dias atrás (mais peso à chuva recente), e '
                      'EDI = (PE − média do dia do calendário) / desvio-padrão do dia do calendário, calibração 1999–2012. Adimensional, '
                      'com memória de 365 dias. Calculado com as funções <code>effective_precipitation</code> e <code>edi</code> do '
                      '<code>climate-indices</code> 3.0.0, com os padrões da biblioteca, e avaliado com o mesmo procedimento da API. '
                      'Todos os números abaixo são do EDI.',
                      '<b>EDI · Effective Drought Index</b> (Byun &amp; Wilhite, 1999), based on effective precipitation: '
                      'PE(d) = Σ<sub>n=1..365</sub> (Σ<sub>m=1..n</sub> rain<sub>m</sub>) / n, where rain<sub>m</sub> is the rain m days earlier (more weight on recent rain), and '
                      'EDI = (PE − calendar-day mean) / calendar-day standard deviation, calibration 1999–2012. Dimensionless, '
                      'with a 365-day memory. Computed with the <code>effective_precipitation</code> and <code>edi</code> functions of '
                      '<code>climate-indices</code> 3.0.0, with the library defaults, and evaluated with the same procedure as the API. '
                      'All figures below are for the EDI.'),
            'API': tr('<b>API · índice de precipitação antecedente</b> (Kohler &amp; Linsley, 1951): API(d) = 0,90 × API(d−1) + chuva(d), '
                      'em mm, com memória de cerca de um mês. Calculado com a função <code>antecedent_precipitation_index</code> do '
                      '<code>climate-indices</code> 3.0.0, com os padrões da biblioteca, e avaliado com o mesmo procedimento do EDI. '
                      'Todos os números abaixo são da API.',
                      '<b>API · Antecedent Precipitation Index</b> (Kohler &amp; Linsley, 1951): API(d) = 0.90 × API(d−1) + rain(d), '
                      'in mm, with a memory of about one month. Computed with the <code>antecedent_precipitation_index</code> function of '
                      '<code>climate-indices</code> 3.0.0, with the library defaults, and evaluated with the same procedure as the EDI. '
                      'All figures below are for the API.')}
        st.markdown('<div class="card" style="border-left:5px solid ' + T.C['accent2'] + '">' + info[best] + '</div>',
                    unsafe_allow_html=True)
    lift = json.loads((S / f'level_lift{suffix(best)}.json').read_text(encoding='utf-8'))
    pv = r['paired_vs_best_rain'].get(best)
    if pv is None:  # the operational predictor is itself the best rainfall predictor
        compare = tr('É o melhor entre os preditores comparados', 'It is the best of the predictors compared')
    else:
        lo, hi = pv['CI95']
        if T.lang() == 'en':
            verdict = ('better than' if lo > 0 else 'worse than' if hi < 0 else 'statistically equivalent to')
            rain = 'the ' + NAMES_EN[pv['vs']].replace(' rainfall', ' accumulated rainfall')
            compare = (f'Performance is {verdict} {rain} (TSS difference {T.num(pv["TSS_diff"], 2, True)}; '
                       f'95% CI {T.num(lo, 2, True)} to {T.num(hi, 2, True)})')
        else:
            verdict = ('superior ao' if lo > 0 else 'inferior ao' if hi < 0 else 'estatisticamente equivalente ao')
            rain = NAMES[pv['vs']].lower().replace('chuva ', 'da chuva acumulada de ')
            compare = (f'O desempenho é {verdict} {rain} (diferença de TSS {T.num(pv["TSS_diff"], 2, True)}; '
                       f'IC95% {T.num(lo, 2, True)} a {T.num(hi, 2, True)})')
    if T.lang() == 'en':
        headline = (f'Watch rule {watch_rule}: detected {pct(L["POD"])} of official flood events out-of-sample, with Watch on '
                    f'{pct(L["POFD"], 1)} of event-free days (TSS {T.num(L["TSS"], 2)}; 95% CI {T.num(L["TSS_CI95"][0], 2)}–'
                    f'{T.num(L["TSS_CI95"][1], 2)}). Index alone: TSS {T.num(loyo[best]["TSS"], 2)}; {compare[0].lower() + compare[1:]}. '
                    f'At Warning ({best} ≥ {fx(fin["alert_pofd2pct"])}), the official-record rate is '
                    f'{T.num(lift["alerta"]["lift_vs_base"], 1)} times the all-day average.')
    else:
        headline = (f'Regra de atenção {watch_rule}: detectou {pct(L["POD"])} dos eventos oficiais de inundação fora da amostra, '
                    f'com atenção em {pct(L["POFD"], 1)} dos dias sem evento (TSS {T.num(L["TSS"], 2)}; IC95% {T.num(L["TSS_CI95"][0], 2)}–'
                    f'{T.num(L["TSS_CI95"][1], 2)}). Índice sozinho: TSS {T.num(loyo[best]["TSS"], 2)}; {compare[0].lower() + compare[1:]}. '
                    f'Em alerta ({best} ≥ {fx(fin["alert_pofd2pct"])}), a taxa de registros é '
                    f'{T.num(lift["alerta"]["lift_vs_base"], 1)} vezes a média de todos os dias.')
    v25all = load_json('validation_2025.json')
    v25 = v25all.get(f'{best}_attention') if v25all else None
    if v25 and best == 'EDI':
        headline += tr(f' No teste independente de 2025, com limiar congelado, o TSS caiu para {T.num(v25["TSS"], 2)} '
                       f'(IC95% {T.num(v25["TSS_CI95"][0], 2)}–{T.num(v25["TSS_CI95"][1], 2)}): a enchente de junho veio após estiagem.',
                       f' In the independent 2025 test, with the threshold frozen, TSS fell to {T.num(v25["TSS"], 2)} '
                       f'(95% CI {T.num(v25["TSS_CI95"][0], 2)}–{T.num(v25["TSS_CI95"][1], 2)}): the June flood followed a dry spell.')
    elif v25:
        pa = r.get('paired_API_vs_EDI')
        headline += tr(f' No teste independente de 2025, com limiar congelado, o TSS foi {T.num(v25["TSS"], 2)} '
                       f'(IC95% {T.num(v25["TSS_CI95"][0], 2)}–{T.num(v25["TSS_CI95"][1], 2)}).',
                       f' In the independent 2025 test, with the threshold frozen, TSS was {T.num(v25["TSS"], 2)} '
                       f'(95% CI {T.num(v25["TSS_CI95"][0], 2)}–{T.num(v25["TSS_CI95"][1], 2)}).')
        if pa:
            headline += tr(f' Diferença API − EDI em 2013–2024: {T.num(pa["TSS_diff"], 2, True)} (IC95% {T.num(pa["CI95"][0], 2, True)} a '
                           f'{T.num(pa["CI95"][1], 2, True)}), {ci_verdict(pa["CI95"])}.',
                           f' API − EDI difference in 2013–2024: {T.num(pa["TSS_diff"], 2, True)} (95% CI {T.num(pa["CI95"][0], 2, True)} to '
                           f'{T.num(pa["CI95"][1], 2, True)}), {ci_verdict(pa["CI95"])}.')
    st.markdown(f'<div class="headline"><div class="q">{tr("Resposta", "Answer")}</div><div class="a">{T.esc(headline)}</div></div>',
                unsafe_allow_html=True)
    ev_all = pd.read_csv(S / 'events.csv')
    by_year = ev_all.groupby(pd.to_datetime(ev_all.date).dt.year).size()
    years_txt = ' · '.join(f'{y}: {n}' for y, n in by_year.items())
    top_ep = ev_all.groupby('episode_id').size().sort_values(ascending=False).head(3) if 'episode_id' in ev_all else pd.Series(dtype=int)
    ep_txt = T.detail_rows([(tr(f'{k[9:11]}/{k[7:9]}/{k[3:7]}', f'{k[9:11]} {pd.Timestamp(2000, int(k[7:9]), 1):%b} {k[3:7]}')
                             if str(k).startswith('EP-') else str(k),
                             f'{n} {tr("eventos", "events")}') for k, n in top_ep.items()])
    lfa = lift['atencao']; lal = lift['alerta']
    has25 = v25 is not None
    T.kpis([
        (tr('Eventos oficiais', 'Official events'), f'{r["n"]["positives"]}',
         tr(f'de {m["atlas_records_corridor_period"]} registros S2iD (inundação, enxurrada, alagamento, chuva intensa)',
            f'from {m["atlas_records_corridor_period"]} S2iD records (riverine flood, flash flood, urban flooding, heavy rain)'),
         tr(f'<p>Registros do mesmo município a até 7 dias um do outro contam como um único evento '
            f'({m["atlas_records_corridor_period"]} → {r["n"]["positives"]}). Fonte: Atlas Digital de Desastres no Brasil, '
            f'COBRADE 12100, 12200, 12300 e 13214.</p><div class="section">Eventos por ano</div><p class="note">{years_txt}</p>',
            f'<p>Records from the same municipality within 7 days of each other count as a single event '
            f'({m["atlas_records_corridor_period"]} → {r["n"]["positives"]}). Source: Atlas Digital de Desastres no Brasil, '
            f'COBRADE 12100, 12200, 12300 and 13214.</p><div class="section">Events per year</div><p class="note">{years_txt}</p>')),
        (tr('Episódios distintos', 'Distinct episodes'), f'{r["n"]["episodes"]}',
         tr('2013–2024 · separados por mais de 5 dias', '2013–2024 · separated by more than 5 days'),
         tr('<p>Um episódio junta eventos de municípios diferentes ligados no tempo (intervalo de até 5 dias). Ele é a unidade de '
            'reamostragem do bootstrap, para que um único temporal com dezenas de registros não pareça dezenas de casos independentes.</p>'
            f'<div class="section">Maiores episódios (início)</div>{ep_txt}',
            '<p>An episode groups events from different municipalities that are linked in time (gaps of up to 5 days). It is the '
            'bootstrap resampling unit, so that a single storm with dozens of records does not look like dozens of independent cases.</p>'
            f'<div class="section">Largest episodes (start date)</div>{ep_txt}')),
        (tr('Município-dias sem evento', 'Municipality-days without an event'),
         tr(f'{T.num(r["n"]["negatives"]/1000,0)} mil', f'{T.num(r["n"]["negatives"]/1000,0)}k'),
         tr('controles negativos', 'negative controls'),
         tr('<p>Dias de cada um dos municípios dos corredores a mais de 15 dias de qualquer registro. A folga evita contar como “sem evento” '
            'dias vizinhos a uma inundação registrada com data imprecisa.</p>',
            '<p>Days, for each corridor municipality, more than 15 days away from any record. The buffer avoids counting as “no event” '
            'days close to a recorded flood whose date is imprecise.</p>')),
        (tr('Acerto fora da amostra', 'Out-of-sample hit rate'), pct(L['POD']),
         tr('registros do S2iD, deixando um ano de fora', 'S2iD records, leave-one-year-out')
         + (tr(f' · cheia dos rios (ANA): {pct(RV["POD"])}', f' · river floods (ANA): {pct(RV["POD"])}') if RV else ''),
         tr(f'<p>Regra de atenção: {watch_rule}. Para cada ano de 2013 a 2024, o limiar do índice e o da chuva de 3 dias são escolhidos '
            'só com os outros 11 anos e aplicados ao ano deixado de fora. O valor é a fração dos eventos com o nível em atenção ou alerta '
            'no dia do registro ou na véspera.</p>',
            f'<p>Watch rule: {watch_rule}. For each year from 2013 to 2024, the index threshold and the 3-day rainfall threshold are chosen '
            'using only the other 11 years and applied to the held-out year. The value is the share of events with the level at Watch or '
            'Warning on the day of the record or the day before.</p>')
         + T.s2id_vs_rivers(L, RV, rv['municipalities'] if rv else None)
         + T.detail_rows([(tr('IC95% da detecção (S2iD)', 'Detection 95% CI (S2iD)'), f'{pct(L["POD_CI95"][0])}–{pct(L["POD_CI95"][1])}'),
                          (tr('Treino 2013–2020 → teste 2021–2024', 'Train 2013–2020 → test 2021–2024'), f'TSS {T.num(H["TSS"],2)}'),
                          (tr('Índice sozinho (sem gatilho)', 'Index alone (no trigger)'), f'{pct(loyo[best]["POD"])} · TSS {T.num(loyo[best]["TSS"],2)}'),
                          (tr('Teste 2025 · só o limiar do índice', '2025 test · index threshold only'),
                           pct(v25["POD"]) if has25 else '–')])),
        (tr('Dias sem evento em atenção', 'Event-free days at Watch'), pct(L['POFD'], 1),
         tr('alarme falso nos registros do S2iD', 'false alarm on S2iD records')
         + (tr(f' · sem cheia nos rios (ANA): {pct(RV["POFD"], 1)}', f' · without river flood (ANA): {pct(RV["POFD"], 1)}') if RV else ''),
         tr(f'<p>É o custo do nível de atenção: ele fica ativo em parte dos dias sem registro, porque o {best} acumula chuva de muitos dias. '
            'Por isso o nível é lido como risco elevado, e não como previsão de alagamento.</p>',
            f'<p>This is the cost of the Watch level: it is active on part of the days without a record, because the {best} accumulates rainfall over many days. '
            'That is why the level is read as elevated risk, not as a flood forecast.</p>')
         + T.s2id_vs_rivers(L, RV, rv['municipalities'] if rv else None)
         + T.detail_rows([(tr('Taxa de registros em atenção', 'Record rate at Watch'), f'{T.num(lfa["lift_vs_base"],1)}× {tr("a média", "the average")}'),
                          (tr('Taxa de registros em alerta', 'Record rate at Warning'), f'{T.num(lal["lift_vs_base"],1)}× {tr("a média", "the average")}'),
                          (tr('Alerta em dias sem evento', 'Warning on event-free days'), pct(loyo[f'{best}_alert']['POFD'], 1))])),
        (tr('Habilidade (TSS)', 'Skill (TSS)'), f'{T.num(L["TSS"],2)}',
         f'{tr("IC95%", "95% CI")} {T.num(L["TSS_CI95"][0],2)}–{T.num(L["TSS_CI95"][1],2)}',
         tr('<p>TSS (escore de Peirce) = eventos detectados − dias sem evento em atenção. Vai de 0 (sem habilidade, igual a sortear) a 1 '
            '(perfeito) e não depende de quão raros são os eventos.</p>',
            '<p>TSS (Peirce skill score) = events detected − event-free days at Watch. It ranges from 0 (no skill, equivalent to chance) to 1 '
            '(perfect) and does not depend on how rare the events are.</p>')
         + T.detail_rows(([(f'{k} + {tr("gatilho 3 dias", "3-day trigger")}', T.num(g['designs']['LOYO'][k]['with_P3']['TSS'], 2))
                           for k in ('EDI', 'API')] if g else [])
                         + [(f'{N[k]} ({tr("só índice", "index only")})', T.num(loyo[k]['TSS'], 2)) for k in (['EDI', 'API'] if has_api else ['EDI'])]
                         + [(N['P30'], T.num(loyo['P30']['TSS'], 2)),
                          (N['P3'], T.num(loyo['P3']['TSS'], 2)), (f'{N["MONTH"]}, AUC', T.num(r['auc']['MONTH']['AUC'], 2))])),
    ] + ([(tr('Teste independente 2025', 'Independent 2025 test'), f'TSS {T.num(v25["TSS"], 2)}',
           f'{tr("IC95%", "95% CI")} {T.num(v25["TSS_CI95"][0], 2)}–{T.num(v25["TSS_CI95"][1], 2)}',
           tr('<p>Limiares congelados de 2013–2024 aplicados a 2025, ano que nenhuma etapa do estudo usou. O critério pré-registrado '
              '(limite inferior do IC acima de 0,2) não foi atingido. Detalhes na aba <b>Teste independente 2025</b>.</p>',
              '<p>Frozen 2013–2024 thresholds applied to 2025, a year no step of the study used. The pre-registered criterion '
              '(lower CI bound above 0.2) was not met. Details in the <b>Independent 2025 test</b> tab.</p>')
           + T.detail_rows([(tr('Eventos detectados', 'Events detected'), pct(v25['POD'])),
                            (tr('Atenção em dias sem evento', 'Watch on event-free days'), pct(v25['POFD'], 1))]))] if has25 else []))

    t1, t3, t7, t8, t4, t5, t2, t6 = st.tabs([tr('Comparação de preditores', 'Predictor comparison'), tr('Verificação nas rodovias', 'Highway check'),
                                              tr('Bacia a montante (ANA)', 'Upstream basin (ANA)'), tr('Nível dos rios (ANA)', 'River levels (ANA)'),
                                              tr('Método e dados', 'Method and data'), tr('Limitações', 'Limitations'),
                                              tr('Maio de 2024', 'May 2024'), tr('Teste independente 2025', 'Independent 2025 test')])
    with t7:
        upstream_tab(N)
    with t8:
        rivers_tab(N, m["units"])
    with t1:
        a, b = st.columns([1, 1.15])
        with a:
            st.markdown(f'<div class="section">{tr("Curva ROC · todos os anos", "ROC curve · all years")}</div>', unsafe_allow_html=True)
            data = roc.copy()
            data['nome'] = data.predictor.map(N)
            ch = alt.Chart(data).mark_line(strokeWidth=2.2).encode(
                x=alt.X('POFD:Q', title=tr('Alarme falso (fração dos dias sem evento)', 'False alarm (share of event-free days)'), scale=alt.Scale(domain=[0, 1])),
                y=alt.Y('POD:Q', title=tr('Eventos detectados', 'Events detected'), scale=alt.Scale(domain=[0, 1])),
                color=alt.Color('nome:N', title=None, scale=alt.Scale(domain=[N[k] for k in COLORS], range=list(COLORS.values())),
                                legend=alt.Legend(orient='bottom', columns=1, labelLimit=0, labelColor=T.C['text'])),
                order='threshold:Q', tooltip=[alt.Tooltip('nome:N', title=tr('Preditor', 'Predictor')),
                                              alt.Tooltip('threshold:Q', format='.2f', title=tr('Limiar', 'Threshold')),
                                              alt.Tooltip('POD:Q', format='.2f'), alt.Tooltip('POFD:Q', format='.3f')])
            diag = alt.Chart(pd.DataFrame({'x': [0, 1], 'y': [0, 1]})).mark_line(strokeDash=[4, 4], color=T.C['muted']).encode(x='x', y='y')
            st.altair_chart((ch + diag).properties(height=360).configure(background=T.C['panel'])
                            .configure_axis(labelColor=T.C['muted'], titleColor=T.C['muted'], gridColor=T.C['border'])
                            .configure_view(stroke=None), width='stretch')
        with b:
            st.markdown(f'<div class="section">{tr("Desempenho fora da amostra · limiar escolhido sem ver o ano testado", "Out-of-sample performance · threshold chosen without seeing the test year")}</div>',
                        unsafe_allow_html=True)
            rows = ''
            for k in ['P1', 'P3', 'P7', 'P30', 'PE', 'EDI', 'EDI&P3', 'EDI_alert'] + (['API', 'API_alert'] if has_api else []):
                v, h = loyo[k], hold[k]
                au = r['auc'].get(k, {}).get('AUC')
                cls = ' class="best"' if k == best and not g else ''
                rows += (f'<tr{cls}><td>{N[k]}</td><td>{f"{T.num(au,2)}" if au else "–"}</td><td>{pct(v["POD"])}</td>'
                         f'<td>{pct(v["POFD"], 1)}</td><td><b>{T.num(v["TSS"],2)}</b> <span class="muted">({T.num(v["TSS_CI95"][0],2)}–{T.num(v["TSS_CI95"][1],2)})</span></td>'
                         f'<td>{T.num(h["TSS"],2)}</td><td>{T.num(v["TSS_without_AprMay2024"],2)} · {T.num(h["TSS_without_AprMay2024"],2)}</td></tr>')
            if g:  # operational rules: index OR frozen 3-day trigger (docs/protocol.md §9.3, §10)
                for k in ('EDI', 'API'):
                    v, h = g['designs']['LOYO'][k]['with_P3'], g['designs']['holdout_2013-2020_vs_2021-2024'][k]['with_P3']
                    cls = ' class="best"' if k == best else ''
                    rows += (f'<tr{cls}><td>{k} + {tr("gatilho 3 dias (regra do painel)", "3-day trigger (dashboard rule)")}</td>'
                             f'<td>–</td><td>{pct(v["POD"])}</td><td>{pct(v["POFD"], 1)}</td><td><b>{T.num(v["TSS"],2)}</b> <span class="muted">'
                             f'({T.num(v["TSS_CI95"][0],2)}–{T.num(v["TSS_CI95"][1],2)})</span></td><td>{T.num(h["TSS"],2)}</td>'
                             f'<td>{T.num(v.get("TSS_without_AprMay2024"),2)} · {T.num(h.get("TSS_without_AprMay2024"),2)}</td></tr>')
            st.markdown(tr('<table class="t"><tr><th>Preditor</th><th>AUC</th><th>Detecção</th><th>Atenção sem evento</th>'
                           '<th>TSS (IC95%)</th><th>TSS teste 2021–24</th><th>TSS sem o episódio abr–mai/24 (por ano · teste)</th></tr>',
                           '<table class="t"><tr><th>Predictor</th><th>AUC</th><th>Detection</th><th>Watch without event</th>'
                           '<th>TSS (95% CI)</th><th>TSS test 2021–24</th><th>TSS excluding the Apr–May 2024 episode (by year · test)</th></tr>')
                        + rows + '</table>',
                        unsafe_allow_html=True)
            pv = r['paired_vs_best_rain']
            ci = tr('IC95%', '95% CI')
            to = tr('a', 'to')
            txt = ''.join(f'<div class="row"><span>{N[k]} − {N[v["vs"]]}</span><b>{T.num(v["TSS_diff"],2,True)} '
                          f'<span class="muted">({ci} {T.num(v["CI95"][0],2,True)} {to} {T.num(v["CI95"][1],2,True)})</span> · '
                          f'{ci_verdict(v["CI95"])}</b></div>' for k, v in pv.items())
            pa = r.get('paired_API_vs_EDI')
            if pa:
                txt += (f'<div class="row"><span>{N["API"]} − EDI</span><b>{T.num(pa["TSS_diff"],2,True)} '
                        f'<span class="muted">({ci} {T.num(pa["CI95"][0],2,True)} {to} {T.num(pa["CI95"][1],2,True)})</span> · {ci_verdict(pa["CI95"])}</b></div>')
            st.markdown(f'<div class="card" style="margin-top:10px"><div class="section">{tr("O índice supera a chuva simples?", "Does the index beat plain rainfall?")}</div>{txt}</div>',
                        unsafe_allow_html=True)
            st.markdown(tr(f'<p class="note">Sazonalidade sozinha (mês): AUC {T.num(r["auc"]["MONTH"]["AUC"],2)}. TSS = detecção − alarme falso '
                           f'(0 = sem habilidade, 1 = perfeito). IC por bootstrap em blocos (episódios e ano-mês), 2.000 réplicas.</p>',
                           f'<p class="note">Seasonality alone (month): AUC {T.num(r["auc"]["MONTH"]["AUC"],2)}. TSS = detection − false alarm '
                           f'(0 = no skill, 1 = perfect). CIs from block bootstrap (episodes and year-month), 2,000 replicates.</p>'),
                        unsafe_allow_html=True)
    with t6:
        v = json.loads((S / 'validation_2025.json').read_text(encoding='utf-8')) if (S / 'validation_2025.json').exists() else None
        if v is None:
            st.info(tr('Teste de 2025 ainda não executado (python -m floodwatch.validation_2025).',
                       '2025 test not yet run (python -m floodwatch.validation_2025).'))
        else:
            a25, al25, p25 = v['EDI_attention'], v['EDI_alert'], v['P30']
            ft = v['frozen_thresholds']

            def result_line(ix, x, thr, ok):
                status = tr('confirmado', 'confirmed') if ok else tr('não confirmado pelo critério pré-registrado',
                                                                     'not confirmed under the pre-registered criterion')
                val = fmt_index(thr, ix)
                return tr(f'<p><b>{ix}: {status}.</b> {ix} ≥ {val} detectou {pct(x["POD"])} dos {v["events"]} eventos de 2025 '
                          f'({v["episodes"]} episódios), com atenção em {pct(x["POFD"], 1)} dos dias sem evento: TSS {T.num(x["TSS"], 2)} '
                          f'(IC95% {T.num(x["TSS_CI95"][0], 2)}–{T.num(x["TSS_CI95"][1], 2)}).</p>',
                          f'<p><b>{ix}: {status}.</b> {ix} ≥ {val} detected {pct(x["POD"])} of the {v["events"]} events in 2025 '
                          f'({v["episodes"]} episodes), with Watch on {pct(x["POFD"], 1)} of event-free days: TSS {T.num(x["TSS"], 2)} '
                          f'(95% CI {T.num(x["TSS_CI95"][0], 2)}–{T.num(x["TSS_CI95"][1], 2)}).</p>')

            lines = result_line('EDI', a25, ft['EDI_attention'], v['confirmed_2025'])
            if 'API_attention' in v:
                lines += result_line('API', v['API_attention'], ft['API_attention'], v.get('confirmed_2025_API'))
            st.markdown(tr('<div class="card"><div class="section">Limiares congelados de 2013–2024 aplicados a 2025, um ano que nenhuma etapa do estudo viu</div>',
                           '<div class="card"><div class="section">Frozen 2013–2024 thresholds applied to 2025, a year no stage of the study had seen</div>')
                        + lines + tr('<p class="note">O critério registrado exigia limite inferior do IC95% do TSS acima de 0,2.</p></div>',
                                     '<p class="note">The registered criterion required a lower 95% CI bound of TSS above 0.2.</p></div>'),
                        unsafe_allow_html=True)
            rules = [(tr(f'EDI ≥ {T.num(ft["EDI_attention"], 2)} (atenção)', f'EDI ≥ {T.num(ft["EDI_attention"], 2)} (Watch)'), a25),
                     (tr(f'EDI ≥ {T.num(ft["EDI_alert"], 2)} (alerta)', f'EDI ≥ {T.num(ft["EDI_alert"], 2)} (Warning)'), al25),
                     (tr(f'Chuva 30 dias ≥ {T.num(ft["P30"], 0)} mm (comparação)', f'30-day rainfall ≥ {T.num(ft["P30"], 0)} mm (benchmark)'), p25)]
            if 'API_attention' in v:
                rules += [(tr(f'API ≥ {fmt_index(ft["API_attention"], "API")} (atenção)', f'API ≥ {fmt_index(ft["API_attention"], "API")} (Watch)'), v['API_attention']),
                          (tr(f'API ≥ {fmt_index(ft["API_alert"], "API")} (alerta)', f'API ≥ {fmt_index(ft["API_alert"], "API")} (Warning)'), v['API_alert'])]
            rows = ''.join(f'<tr><td>{n}</td><td>{pct(x["POD"])}</td><td>{pct(x["POFD"], 1)}</td><td><b>{T.num(x["TSS"], 2)}</b> '
                           f'<span class="muted">({T.num(x["TSS_CI95"][0], 2)}–{T.num(x["TSS_CI95"][1], 2)})</span></td></tr>'
                           for n, x in rules)
            st.markdown(tr('<table class="t"><tr><th>Regra congelada</th><th>Detecção</th><th>Atenção sem evento</th><th>TSS (IC95%)</th></tr>',
                           '<table class="t"><tr><th>Frozen rule</th><th>Detection</th><th>Watch without event</th><th>TSS (95% CI)</th></tr>')
                        + rows + '</table>', unsafe_allow_html=True)
            if 'API_minus_EDI_TSS' in v:
                da, june, aug = v['API_minus_EDI_TSS'], v['by_episode'].get('EP-20250614', {}), v['by_episode'].get('EP-20250822', {})
                st.markdown(tr(f'<div class="card" style="margin-top:10px"><div class="section">API em 2025</div>'
                               f'<p>Com memória de cerca de um mês, a API reage mais rápido depois de uma estiagem. Na enchente de junho, '
                               f'{pct(june.get("API_share_at_attention", float("nan")))} dos eventos estavam em atenção pela API, contra '
                               f'{pct(june.get("share_at_attention", float("nan")))} pelo EDI; em agosto, {pct(aug.get("API_share_at_attention", float("nan")))} '
                               f'e {pct(aug.get("share_at_attention", float("nan")))}. Diferença API − EDI no TSS de 2025: {T.num(da["diff"], 2, True)} '
                               f'(IC95% {T.num(da["CI95"][0], 2, True)} a {T.num(da["CI95"][1], 2, True)}), {ci_verdict(da["CI95"])}.</p></div>',
                               f'<div class="card" style="margin-top:10px"><div class="section">API in 2025</div>'
                               f'<p>With a memory of about one month, the API reacts faster after a dry spell. In the June flood, '
                               f'{pct(june.get("API_share_at_attention", float("nan")))} of events were at Watch by the API, versus '
                               f'{pct(june.get("share_at_attention", float("nan")))} by the EDI; in August, {pct(aug.get("API_share_at_attention", float("nan")))} '
                               f'and {pct(aug.get("share_at_attention", float("nan")))}. API − EDI TSS difference in 2025: {T.num(da["diff"], 2, True)} '
                               f'(95% CI {T.num(da["CI95"][0], 2, True)} to {T.num(da["CI95"][1], 2, True)}), {ci_verdict(da["CI95"])}.</p></div>'),
                            unsafe_allow_html=True)
            d = v['EDI_minus_P30_TSS']
            st.markdown(tr(f"""<div class="card" style="margin-top:10px"><div class="section">Por que a detecção do EDI caiu</div>
<p>{v['episodes_list'].get('EP-20250614', 0)} dos {v['events']} eventos de 2025 vieram da enchente de junho, que ocorreu logo depois da estiagem do verão. O EDI acumula a chuva de 365 dias e ainda estava baixo quando veio a chuva intensa: a mediana no dia dos eventos de junho foi {T.num(v['by_episode']['EP-20250614']['EDI_median'], 2)}, contra {T.num(v['EDI_median_events_2013_2024'], 2)} nos eventos de 2013–2024. No episódio de agosto, com o solo já úmido, {pct(v['by_episode']['EP-20250822']['share_at_attention'])} dos eventos estavam em atenção.</p>
<p><b>Leitura:</b> o EDI capta bem a inundação de solo encharcado e subestima a de chuva intensa sobre solo que vinha seco. Diferença EDI − chuva 30 dias em 2025: {T.num(d['diff'], 2, True)} (IC95% {T.num(d['CI95'][0], 2, True)} a {T.num(d['CI95'][1], 2, True)}), sem diferença comprovada.</p>
<p><b>O que fazer com isso.</b> Os limiares não foram reajustados com 2025: ajustar o limiar depois de ver o resultado invalidaria o teste. A hipótese que sai daqui é que um segundo gatilho de chuva intensa de curto prazo cobriria as enchentes após estiagem. Ela foi testada em 2013–2024 (quadro abaixo) e só será confirmada com dados que o estudo ainda não viu (registros de 2026 em diante).</p>
<p class="note">Chuva de 2025: MERGE na versão IMERG-late ({', '.join(f'{k}: {n} dia' + ('' if n == 1 else 's') for k, n in v['rain_product_states'].items())}), e não V07B final. Registros do Atlas de 2025 podem estar incompletos.</p></div>""",
                           f"""<div class="card" style="margin-top:10px"><div class="section">Why EDI detection dropped</div>
<p>{v['episodes_list'].get('EP-20250614', 0)} of the {v['events']} events in 2025 came from the June flood, which occurred right after the summer dry spell. The EDI accumulates 365 days of rainfall and was still low when the heavy rain arrived: the median on June event days was {T.num(v['by_episode']['EP-20250614']['EDI_median'], 2)}, versus {T.num(v['EDI_median_events_2013_2024'], 2)} for 2013–2024 events. In the August episode, with soils already wet, {pct(v['by_episode']['EP-20250822']['share_at_attention'])} of events were at Watch.</p>
<p><b>Interpretation:</b> the EDI captures floods on saturated soils well and underestimates floods from heavy rain on previously dry soils. EDI − 30-day rainfall difference in 2025: {T.num(d['diff'], 2, True)} (95% CI {T.num(d['CI95'][0], 2, True)} to {T.num(d['CI95'][1], 2, True)}), no proven difference.</p>
<p><b>What to do about it.</b> The thresholds were not re-tuned with 2025: adjusting the threshold after seeing the result would invalidate the test. The hypothesis that emerges is that a second, short-term heavy-rain trigger would cover floods after dry spells. It was tested on 2013–2024 (panel below) and will only be confirmed with data the study has not yet seen (records from 2026 onwards).</p>
<p class="note">2025 rainfall: MERGE, IMERG-late version ({', '.join(f'{k}: {n} day' + ('' if n == 1 else 's') for k, n in v['rain_product_states'].items())}), not V07B final. 2025 Atlas records may be incomplete.</p></div>"""),
                        unsafe_allow_html=True)
            second_trigger_card()
    with t2:
        st.markdown('<div class="card" style="border-left:5px solid ' + T.C['accent2'] + '">'
                    + tr(f'<b>Reconstituição com chuva observada, não previsão.</b> '
                         f'O gráfico recalcula o {best} de abril–maio de 2024 a partir da chuva que de fato caiu (MERGE/CPTEC, medida por satélite '
                         'e pluviômetros) e o compara com os registros oficiais de cada dia. Ele mostra se o limiar reconheceria a enchente, '
                         'e não o que os modelos de previsão indicavam na época.',
                         f'<b>Reconstruction with observed rainfall, not a forecast.</b> '
                         f'The chart recomputes the April–May 2024 {best} from the rain that actually fell (MERGE/CPTEC, satellite and rain-gauge '
                         'measurements) and compares it with each day’s official records. It shows whether the threshold would have recognised the flood, '
                         'not what the forecast models were indicating at the time.')
                    + '</div>', unsafe_allow_html=True)
        st.markdown(tr(f'<div class="section">Abril–maio de 2024 · fração dos {m["units"]} municípios em atenção/alerta com chuva observada · barras = registros oficiais no dia</div>',
                       f'<div class="section">April–May 2024 · share of the {m["units"]} municipalities at Watch/Warning with observed rainfall · bars = official records on the day</div>'),
                    unsafe_allow_html=True)
        lbl_att, lbl_al = tr('Atenção ou alerta', 'Watch or Warning'), tr('Alerta', 'Warning')
        base = alt.Chart(tl).encode(x=alt.X('date:T', title=None, axis=alt.Axis(format=tr('%d/%m', '%d %b'))))
        area = base.transform_fold(['attention', 'alert'], as_=['nivel', 'frac']).mark_area(opacity=.75).encode(
            y=alt.Y('frac:Q', title=tr('Fração de municípios', 'Share of municipalities'), stack=None, axis=alt.Axis(format='%')),
            color=alt.Color('nivel:N', scale=alt.Scale(domain=['attention', 'alert'], range=[T.C['atencao'], T.C['alerta']]),
                            legend=alt.Legend(orient='top', labelExpr=f"datum.label == 'attention' ? '{lbl_att}' : '{lbl_al}'",
                                              title=None, labelColor=T.C['text'])))
        bars = base.mark_bar(color=T.C['text'], opacity=.85, width=5).encode(
            y=alt.Y('records:Q', title=tr('Registros S2iD no dia', 'S2iD records on the day'),
                    scale=alt.Scale(domain=[0, float(tl.records.max()) * 1.12 if len(tl) else 1], nice=True)), tooltip=[alt.Tooltip('date:T', title=tr('Data', 'Date'), format=tr('%d/%m/%Y', '%d %b %Y')),
                                                                                  alt.Tooltip('records:Q', title=tr('Registros S2iD', 'S2iD records'))])
        st.altair_chart(alt.layer(area, bars).resolve_scale(y='independent').properties(height=320)
                        .configure(background=T.C['panel']).configure_axis(labelColor=T.C['muted'], titleColor=T.C['muted'],
                                                                           gridColor=T.C['border']).configure_view(stroke=None),
                        width='stretch')
        ep = r['sensitivity_episode']
        ev = leads[leads.episode_id == ep['block']]
        st.markdown(tr(f'<p class="note">Nos {len(ev)} eventos do episódio de {dfmt(ep["start"], False)} a {dfmt(ep["end"])}, {pct((ev.level_on_day >= 1).mean())} estavam em atenção '
                       f'ou alerta na data do registro e {pct((ev.level_on_day == 2).mean())} em alerta, calculados com a chuva observada. '
                       f'Como o {best} acumula chuva de muitos dias, o nível fica ativo por semanas; isso não equivale a antecedência de previsão.</p>',
                       f'<p class="note">Of the {len(ev)} events in the episode from {dfmt(ep["start"], False)} to {dfmt(ep["end"])}, {pct((ev.level_on_day >= 1).mean())} were at Watch '
                       f'or Warning on the record date and {pct((ev.level_on_day == 2).mean())} at Warning, computed with observed rainfall. '
                       f'Because the {best} accumulates rainfall over many days, the level stays active for weeks; this is not equivalent to forecast lead time.</p>'),
                    unsafe_allow_html=True)
    with t3:
        st.markdown(f'<div class="section">{tr("Impactos documentados em BR-116/386/290 · não usados na calibração", "Documented impacts on BR-116/386/290 · not used in calibration")} · {best}</div>', unsafe_allow_html=True)
        ok = road[road.status == 'avaliado']
        def first_day(v):
            if pd.isna(v):
                return tr('não ativou', 'not triggered')
            v = int(v)
            if v == 0:
                return tr('no dia', 'on the day')
            if v <= -7:
                return tr('7 dias antes ou mais', '7 or more days before')
            return tr(f'{-v} dias antes', f'{-v} days before')
        zero = tr(',0', '.0')
        rows = ''.join(f'<tr><td>{T.esc(x.road.replace("/RS", ""))} km {T.num(x.km, 1).replace(zero, "")}</td><td>{T.esc(x.municipio)}</td>'
                       f'<td>{dfmt(x.data)}</td>'
                       f'<td>{T.chip(int(x["nivel_max_d-2_a_d"])) if pd.notna(x["nivel_max_d-2_a_d"]) else "–"}</td>'
                       f'<td>{first_day(x["primeiro_dia_atencao_ate_7d_antes"])}</td></tr>'
                       for _, x in ok.iterrows())
        st.markdown(tr('<table class="t"><tr><th>Trecho</th><th>Município</th><th>Data documentada</th><th>Nível máx. (D−2 a D)</th>'
                       '<th>Atenção ativa desde</th></tr>',
                       '<table class="t"><tr><th>Section</th><th>Municipality</th><th>Documented date</th><th>Max. level (D−2 to D)</th>'
                       '<th>Watch active since</th></tr>') + rows + '</table>', unsafe_allow_html=True)
        hit = (ok['nivel_max_d-2_a_d'] >= 1).mean() if len(ok) else float('nan')
        hit_alert = (ok['nivel_max_d-2_a_d'] == 2).mean() if len(ok) else float('nan')
        st.markdown(tr(f'<p class="note">{len(ok)} impactos com data e município; {pct(hit)} com atenção ou alerta e {pct(hit_alert)} com alerta entre D−2 e D. '
                       f'A data documentada é a de boletim/condição, não o início exato do impacto. Amostra pequena: '
                       f'é conferência qualitativa, não métrica.</p>',
                       f'<p class="note">{len(ok)} impacts with date and municipality; {pct(hit)} at Watch or Warning and {pct(hit_alert)} at Warning between D−2 and D. '
                       f'The documented date is that of the bulletin/condition report, not the exact onset of the impact. Small sample: '
                       f'this is a qualitative check, not a metric.</p>'), unsafe_allow_html=True)
    with t4:
        lv_rows = ''
        for k in ('EDI', 'API'):
            f = r['final_thresholds_all_years'][k]
            b = g['final_frozen'][k]['P3_mm'] if g else None
            lv_rows += (f'<tr><td><b>{k}</b></td><td>{fmt_index(f["attention"], k)} <span class="muted">({tr("IC95%", "95% CI")} '
                        f'{fmt_index(f["attention_CI95"][0], k)}–{fmt_index(f["attention_CI95"][1], k)})</span></td>'
                        f'<td>{T.num(b, 0) + " mm" if b else "–"}</td><td>{fmt_index(f["alert_pofd2pct"], k)}</td></tr>')
        levels_table = ('<div class="section">' + tr('Níveis do painel (refeitos com todos os anos de 2013–2024 e congelados)',
                                                      'Dashboard levels (refitted on all 2013–2024 years and frozen)') + '</div>'
                        + tr('<table class="t"><tr><th>Índice</th><th>Atenção: índice ≥</th><th>ou chuva de 3 dias na bacia ≥</th>'
                             '<th>Alerta: índice ≥ (alarme falso ≤ 2%)</th></tr>',
                             '<table class="t"><tr><th>Index</th><th>Watch: index ≥</th><th>or 3-day basin rainfall ≥</th>'
                             '<th>Warning: index ≥ (false alarm ≤ 2%)</th></tr>') + lv_rows + '</table>')
        st.markdown(tr(f"""<div class="card">
<p><b>Pergunta.</b> A partir de qual valor do EDI (Byun &amp; Wilhite, 1999) e da API (Kohler &amp; Linsley, 1951) os municípios dos corredores passam a ter registros oficiais de inundação com frequência elevada, e esses limiares continuam funcionando em anos que não foram usados para defini-los? Como referência, o mesmo teste é feito com a chuva acumulada simples (1, 3, 7 e 30 dias), para saber se os índices acrescentam algo.</p>
<p><b>Unidade.</b> {m['units']} municípios cortados pela BR-116, BR-386 ou BR-290 (SNV/DNIT 2024 × malha IBGE), dia a dia, 2013–2024.</p>
<p><b>Eventos.</b> Atlas Digital de Desastres no Brasil (MIDR/CEPED, BD v1.1), COBRADE 12100, 12200, 12300 e 13214. Data informada do desastre (S2iD, 2013 em diante). Registros do mesmo município a até 7 dias contam como um evento: {m['events_after_dedup']} eventos, {m['episodes']} episódios.</p>
<p><b>Negativos.</b> Município-dias a mais de 15 dias de qualquer registro.</p>
<p><b>Chuva e índices.</b> MERGE/CPTEC diário V07B final (0,1°), média ponderada por área sobre a <b>bacia a montante</b> de cada município: as ottobacias da ANA (BHO 2017, nível 6) que tocam o município mais todas as que drenam para elas. A versão só com a chuva do município fica como comparação (aba Bacia a montante). O dia D é a chuva acumulada entre 12 UTC de D−1 e 12 UTC de D (9h em Brasília); a previsão ECMWF/GFS é somada na mesma janela. PE e EDI com janela de 365 dias e calibração fixa em 1999–2012, anterior a todo o período avaliado; API com decaimento k = 0,90 (memória de cerca de um mês), sem calibração. Cada preditor é o máximo de D−1 e D, sem dados após o evento.</p>
<p><b>Limiar.</b> Escolhido pelo máximo TSS (Peirce). A validação deixa um ano de fora: o limiar é reescolhido sem o ano testado. Há um teste temporal (2013–2020 → 2021–2024) e bootstrap em blocos para os intervalos de confiança.</p>
<p><b>EDI.</b> Effective Drought Index (Byun &amp; Wilhite, 1999). Primeiro a precipitação efetiva, PE(d) = Σ<sub>n=1..365</sub> (Σ<sub>m=1..n</sub> P<sub>m</sub>) / n, em que P<sub>m</sub> é a chuva de m dias atrás: soma a chuva de um ano inteiro, com mais peso na recente. Depois a padronização, EDI = (PE − média do dia do calendário) / desvio-padrão do dia do calendário, com calibração fixa em 1999–2012. Adimensional, memória de 365 dias. Funções <code>effective_precipitation</code> e <code>edi</code> do <code>climate-indices</code> 3.0.0, com os padrões da biblioteca.</p>
<p><b>API.</b> Índice de precipitação antecedente (Kohler &amp; Linsley, 1951): API(d) = 0,90 · API(d−1) + P(d), em mm. A chuva de 7 dias atrás ainda pesa cerca de 48% e a de 30 dias, cerca de 4%: memória de cerca de um mês, sem calibração. Função <code>antecedent_precipitation_index</code> do <code>climate-indices</code> 3.0.0, com os padrões da biblioteca (semente zero, dia sem dado não vira zero). A biblioteca exige o k e não tem valor padrão; 0,90 fica na faixa típica citada na documentação (0,85–0,90).</p>
<p>Os dois índices passam por exatamente o mesmo procedimento: mesma chuva, janela, validação por ano, teste temporal, alerta fora da amostra, bootstrap, teste de 2025 e gatilho de 3 dias.</p>
{levels_table}
<p><b>Dados da ANA.</b> Ottobacias (BHO 2017, nível 6) para a chuva da bacia a montante de cada município, e cotas diárias das estações fluviométricas do HidroWeb como validação extra. Regras registradas antes de rodar (protocolo, §3, §8.2 e §9).</p>
<p class="note">Protocolo registrado antes dos resultados: docs/protocol.md. Código: floodwatch/study.py, floodwatch/upstream.py, floodwatch/ana.py e floodwatch/ana_validation.py. Índices: <code>climate-indices</code> 3.0.0.</p></div>""",
                       f"""<div class="card">
<p><b>Question.</b> Above which value of the EDI (Byun &amp; Wilhite, 1999) and of the API (Kohler &amp; Linsley, 1951) do corridor municipalities start to show official flood records at an elevated frequency, and do those thresholds keep working in years not used to set them? As a benchmark, the same test is run with plain accumulated rainfall (1, 3, 7 and 30 days), to find out whether the indices add anything.</p>
<p><b>Unit.</b> {m['units']} municipalities crossed by BR-116, BR-386 or BR-290 (SNV/DNIT 2024 × IBGE boundaries), day by day, 2013–2024.</p>
<p><b>Events.</b> Atlas Digital de Desastres no Brasil (MIDR/CEPED, DB v1.1), COBRADE 12100, 12200, 12300 and 13214. Reported disaster date (S2iD, 2013 onwards). Records from the same municipality within 7 days count as one event: {m['events_after_dedup']} events, {m['episodes']} episodes.</p>
<p><b>Negatives.</b> Municipality-days more than 15 days from any record.</p>
<p><b>Rainfall and indices.</b> MERGE/CPTEC daily V07B final (0.1°), area-weighted mean over the <b>upstream basin</b> of each municipality: the ANA Otto-coded basins (“ottobacias”, BHO 2017, level 6) touching the municipality plus all those draining into them. The municipal-only version is kept for comparison (Upstream basin tab). Day D is the rainfall accumulated from 12 UTC on D−1 to 12 UTC on D (09:00 Brasília time); ECMWF/GFS forecasts are summed over the same window. PE and EDI with a 365-day window and calibration fixed to 1999–2012, before the entire evaluation period; API with decay k = 0.90 (memory of about one month), no calibration needed. Each predictor is the maximum of D−1 and D, with no data after the event.</p>
<p><b>Threshold.</b> Chosen by maximum TSS (Peirce). Validation is leave-one-year-out: the threshold is re-chosen without the test year. There is also a temporal test (2013–2020 → 2021–2024) and a block bootstrap for the confidence intervals.</p>
<p><b>EDI.</b> Effective Drought Index (Byun &amp; Wilhite, 1999). First the effective precipitation, PE(d) = Σ<sub>n=1..365</sub> (Σ<sub>m=1..n</sub> P<sub>m</sub>) / n, where P<sub>m</sub> is the rain m days earlier: a whole year of rain, with more weight on recent rain. Then the standardisation, EDI = (PE − calendar-day mean) / calendar-day standard deviation, calibration fixed to 1999–2012. Dimensionless, 365-day memory. The <code>effective_precipitation</code> and <code>edi</code> functions of <code>climate-indices</code> 3.0.0, with the library defaults.</p>
<p><b>API.</b> Antecedent Precipitation Index (Kohler &amp; Linsley, 1951): API(d) = 0.90 · API(d−1) + P(d), in mm. Rain from 7 days earlier still weighs about 48% and from 30 days about 4%: a memory of about one month, no calibration. The <code>antecedent_precipitation_index</code> function of <code>climate-indices</code> 3.0.0, with the library defaults (zero seed, a missing day never becomes zero). The library requires k and has no default; 0.90 is within the typical range cited in its documentation (0.85–0.90).</p>
<p>Both indices go through exactly the same procedure: same rainfall, window, year-by-year validation, temporal test, out-of-sample Warning, bootstrap, 2025 test and 3-day trigger.</p>
{levels_table}
<p><b>ANA data.</b> Otto-coded basins (BHO 2017, level 6) for the upstream-basin rainfall of each municipality, and daily stages from HidroWeb river gauges as an extra validation. Rules registered before running (protocol, §3, §8.2 and §9).</p>
<p class="note">Protocol registered before the results: docs/protocol.md. Code: floodwatch/study.py, floodwatch/upstream.py, floodwatch/ana.py and floodwatch/ana_validation.py. Indices: <code>climate-indices</code> 3.0.0.</p></div>"""),
                    unsafe_allow_html=True)
        refs = """<ol class="note">
<li>Byun, H.-R.; Wilhite, D. A. (1999). Objective Quantification of Drought Severity and Duration. <i>Journal of Climate</i> 12(9):2747–2756. <a href="https://doi.org/10.1175/1520-0442(1999)012%3C2747:OQODSA%3E2.0.CO;2" target="_blank">doi</a></li>
<li>Deo, R. C.; Byun, H.-R.; Adamowski, J. F.; Kim, D.-W. (2015). A Real-time Flood Monitoring Index Based on Daily Effective Precipitation… <i>Water Resources Management</i> 29(11):4075–4093. <a href="https://doi.org/10.1007/s11269-015-1046-3" target="_blank">doi</a></li>
<li>Adams, J. climate_indices: open source Python library (v3.0.0+, """ + tr('módulo', 'module') + """ <code>flood</code>). <a href="https://github.com/monocongo/climate_indices" target="_blank">github</a></li>
<li>Kohler, M. A.; Linsley, R. K. (1951). Predicting the runoff from storm rainfall. <i>Research Paper 34</i>, U.S. Weather Bureau.</li>
<li>ANA (2017). Base Hidrográfica Ottocodificada Multiescalas 2017 5k (BHO 2017 5k) e HidroWeb, Sistema de Informações Hidrológicas. <a href="https://metadados.snirh.gov.br" target="_blank">snirh</a></li>
<li>Ramos Filho, G. M. et al. (2021). An improved rainfall-threshold approach for robust prediction and warning of flood and flash flood hazards. <i>Natural Hazards</i> 105(3):2409–2429. <a href="https://doi.org/10.1007/s11069-020-04405-x" target="_blank">doi</a></li>
<li>Silva, J. R.; Nunes, A. B. (2012). Análise quantitativa de eventos extremos de precipitação para Bagé e sua relação com o El Niño. ENPOS/UFPel. <a href="https://www2.ufpel.edu.br/enpos/2012/anais/pdf/CE/CE_00380.pdf" target="_blank">pdf</a></li>
<li>Casa Civil/PR (2025). Nota Técnica nº 1/2025 – Cadastro de municípios suscetíveis a enxurradas e inundações. <a href="https://www.gov.br/casacivil/pt-br/assuntos/cadastro-de-municipios-suscetiveis-a-eventos-de-enxurradas-e-inundacoes/sei_6390694_nota_tecnica_1_2025.pdf" target="_blank">pdf</a></li>
<li>Collischonn, W. et al. (2025). The exceptional hydrological disaster of April–May 2024 in southern Brazil. <i>RBRH</i> 30. <a href="https://doi.org/10.1590/2318-0331.302520240119" target="_blank">doi</a></li>
<li>Medeiros, M. S.; Fan, F. M.; Paiva, R. C. D. (2025). Emergency forecasts for water levels in the Guaíba River during the 2024 flood. <i>RBRH</i> 30. <a href="https://doi.org/10.1590/2318-0331.302520250025" target="_blank">doi</a></li>
</ol>"""
        st.markdown(tr("""<div class="card"><div class="section">Posicionamento</div>
<p>Este estudo não substitui os alertas oficiais do CEMADEN, do SGB e da Defesa Civil, nem as plataformas comerciais de monitoramento. Até onde a pesquisa bibliográfica encontrou, é o primeiro a calibrar e validar, fora da amostra e contra registros municipais do S2iD, um limiar de potencial de inundação baseado na precipitação efetiva de Byun &amp; Wilhite (EDI) e no índice de precipitação antecedente (API) para os corredores BR-116, BR-386 e BR-290. O resultado é aplicado a previsões ECMWF/GFS como indicador complementar de risco logístico.</p>
<div class="section">Referências</div>""" + refs + """<p class="note">Dados: MERGE/CPTEC-INPE; Atlas Digital de Desastres no Brasil (MIDR/CEPED-UFSC); ANA (BHO e HidroWeb); DNIT SNV; IBGE; ECMWF e NOAA GFS via Open-Meteo.</p></div>""",
                       """<div class="card"><div class="section">Positioning</div>
<p>This study does not replace the official warnings from CEMADEN, SGB and Civil Defence, nor commercial monitoring platforms. As far as the literature review found, it is the first to calibrate and validate, out-of-sample and against S2iD municipal records, a flood-potential threshold based on Byun &amp; Wilhite effective precipitation (EDI) and on the antecedent precipitation index (API) for the BR-116, BR-386 and BR-290 corridors. The result is applied to ECMWF/GFS forecasts as a complementary logistics-risk indicator.</p>
<div class="section">References</div>""" + refs + """<p class="note">Data: MERGE/CPTEC-INPE; Atlas Digital de Desastres no Brasil (MIDR/CEPED-UFSC); ANA (BHO and HidroWeb); DNIT SNV; IBGE; ECMWF and NOAA GFS via Open-Meteo.</p></div>"""),
                    unsafe_allow_html=True)
        st.download_button(tr('Baixar resultados (JSON)', 'Download results (JSON)'), (S / 'results.json').read_bytes(),
                           tr('resultados-limiar.json', 'threshold-results.json'))
        st.download_button(tr('Baixar eventos (CSV)', 'Download events (CSV)'), (S / 'events.csv').read_bytes(),
                           tr('eventos-atlas-corredores.csv', 'atlas-events-corridors.csv'))
    with t5:
        st.markdown(tr("""<div class="card"><ul>
<li><b>Registro não é medição.</b> O S2iD depende de o município solicitar o registro, muitas vezes para obter recursos. A ausência de registro não prova ausência de inundação, e a cobertura varia por ano.</li>
<li><b>A unidade é o município, não o km.</b> O nível indica condição associada historicamente a registros de inundação no município, não a interdição de um trecho.</li>
<li><b>Chuva observada × prevista.</b> A validação usa chuva observada. Na previsão, os níveis herdam o erro do ECMWF e do GFS. A chuva prevista foi verificada com rodadas arquivadas de 2024–2026 (o ECMWF acertou mais a chuva forte de D+1 a D+3; os dois subestimaram a chuva nos dias de inundação), mas o acerto dos níveis com chuva prevista não foi medido.</li>
<li><b>Bacia a montante sem tempo de viagem.</b> A chuva da bacia entra no mesmo dia em que cai; o índice não modela o tempo que a cheia leva para descer o rio nem o efeito de barragens. Trechos costeiros e lagunares (ex.: Lagoa dos Patos) não têm montante na codificação de Pfafstetter.</li>
<li><b>Inundação após estiagem.</b> Com memória de 365 dias, o EDI demora a subir depois de uma seca e subestimou a enchente de junho/2025 (teste independente). A API, com memória de cerca de um mês, reage mais rápido, mas também esquece mais rápido a umidade acumulada em meses chuvosos.</li>
<li><b>A chuva prevista pode falhar muito.</b> Em 27/04/2024, o ECMWF previu 174 mm em 7 dias para a bacia do Guaíba, e choveram 422 mm (Collischonn et al., 2025).</li>
<li><b>Episódios grandes pesam.</b> Abril–maio/2024 concentra muitos registros. Os resultados sem esse episódio estão na última coluna da tabela de desempenho, na aba <b>Comparação de preditores</b>.</li>
<li><b>Incerteza do limiar.</b> Os intervalos de confiança do TSS fora da amostra reamostram os dias de teste com os limiares de cada dobra fixos; a incerteza da escolha do limiar aparece separadamente, no IC do próprio limiar.</li>
<li><b>Multiplicador de risco.</b> É calculado com os limiares finais sobre todos os município-dias de 2013–2024 (dentro da amostra). As métricas fora da amostra são as da validação por ano.</li>
<li><b>Categorias agrupadas.</b> Os eventos incluem "chuvas intensas" (COBRADE 13214), além de inundação, enxurrada e alagamento, porque municípios vizinhos classificam a mesma ocorrência de formas diferentes.</li>
<li><b>O índice é recente em software.</b> O módulo de inundação (EDI e API) do <code>climate-indices</code> foi lançado em 10/2026, ainda sem validação numérica externa.</li>
<li><b>Nível dos rios.</b> A validação com a ANA cobre só os municípios com estação fluviométrica, usa a mediana dos máximos anuais como cheia (não a cota oficial de inundação) e leituras de 7h e 17h, que podem perder o pico.</li>
<li><b>Fora do escopo:</b> previsão de vazão e deslizamentos. A chuva de 2025 do teste independente vem da versão preliminar do MERGE (IMERG-late).</li></ul></div>""",
                       """<div class="card"><ul>
<li><b>An official record is not a measurement.</b> S2iD depends on the municipality requesting the record, often to obtain funding. The absence of a record does not prove the absence of flooding, and coverage varies by year.</li>
<li><b>The unit is the municipality, not the km.</b> The level indicates a condition historically associated with flood records in the municipality, not the closure of a road section.</li>
<li><b>Observed vs forecast rainfall.</b> Validation uses observed rainfall. In forecast mode, the levels inherit ECMWF and GFS error. Forecast rainfall was verified against archived 2024–2026 runs (ECMWF forecast heavy rain better at D+1 to D+3; both underestimated rain on flood days), but the skill of the levels with forecast rainfall has not been measured.</li>
<li><b>Upstream basin without travel time.</b> Basin rainfall counts on the day it falls; the index does not model how long the flood takes to travel down the river, nor the effect of dams. Coastal and lagoon reaches (e.g. Lagoa dos Patos) have no upstream area in the Pfafstetter coding.</li>
<li><b>Flooding after dry spells.</b> With a 365-day memory, the EDI is slow to rise after a drought and underestimated the June 2025 flood (independent test). The API, with a memory of about one month, reacts faster but also forgets moisture built up over wet months sooner.</li>
<li><b>Forecast rainfall can miss badly.</b> On 27 Apr 2024, ECMWF forecast 174 mm over 7 days for the Guaíba basin, and 422 mm fell (Collischonn et al., 2025).</li>
<li><b>Large episodes carry weight.</b> April–May 2024 concentrates many records. Results excluding that episode are in the last column of the performance table, in the <b>Predictor comparison</b> tab.</li>
<li><b>Threshold uncertainty.</b> The out-of-sample TSS confidence intervals resample the test days with each fold’s thresholds held fixed; the uncertainty of the threshold choice is shown separately, in the threshold’s own CI.</li>
<li><b>Risk multiplier.</b> It is computed with the final thresholds over all municipality-days in 2013–2024 (in-sample). The out-of-sample metrics are those of the year-by-year validation.</li>
<li><b>Grouped categories.</b> Events include "heavy rain" (COBRADE 13214), as well as riverine floods, flash floods and urban flooding, because neighbouring municipalities classify the same occurrence in different ways.</li>
<li><b>The index is new in software.</b> The flood module (EDI and API) of <code>climate-indices</code> was released in Oct 2026 and has no external numerical validation yet.</li>
<li><b>River levels.</b> The ANA validation covers only municipalities with a river gauge, uses the median of annual maxima as a flood (not the official flood stage) and 7:00/17:00 readings, which can miss the peak.</li>
<li><b>Out of scope:</b> discharge forecasting and landslides. The 2025 rainfall in the independent test comes from the preliminary MERGE version (IMERG-late).</li></ul></div>"""),
                    unsafe_allow_html=True)


def _score_table(rows, head):
    """rows: list of (label, dict with POD, POFD, TSS, TSS_CI95[, AUC])."""
    pct = lambda x: T.num(x * 100, 0) + '%'
    body = ''.join(f'<tr><td>{n}</td><td>{T.num(x["AUC"], 2) if x.get("AUC") is not None else "–"}</td><td>{pct(x["POD"])}</td>'
                   f'<td>{T.num(x["POFD"] * 100, 1)}%</td><td><b>{T.num(x["TSS"], 2)}</b> <span class="muted">'
                   f'({T.num(x["TSS_CI95"][0], 2)}–{T.num(x["TSS_CI95"][1], 2)})</span></td>{x.get("extra", "")}</tr>' for n, x in rows)
    return f'<table class="t"><tr>{head}</tr>{body}</table>'


def _paired_rows(pairs, N):
    tr = T.tr
    out = ''
    for key, v in pairs.items():
        a, b = key.split('-')
        out += (f'<div class="row"><span>{N.get(a, a)} − {N.get(b, b)}</span><b>{T.num(v["diff"], 2, True)} <span class="muted">'
                f'({tr("IC95%", "95% CI")} {T.num(v["CI95"][0], 2, True)} {tr("a", "to")} {T.num(v["CI95"][1], 2, True)})</span> · '
                f'{ci_verdict(v["CI95"])}</b></div>')
    return out


def upstream_tab(N):
    tr = T.tr
    u = load_json('upstream_results.json')
    if u is None:
        st.info(tr('Análise da bacia a montante ainda não executada (python -m floodwatch.upstream basins/rain e '
                   'python -m floodwatch.ana_validation upstream).',
                   'Upstream-basin analysis not run yet (python -m floodwatch.upstream basins/rain and '
                   'python -m floodwatch.ana_validation upstream).'))
        return
    N = {**N, 'EDI': tr('EDI do município', 'Municipal EDI'), 'API': tr('API do município', 'Municipal API'),
         'EDI_alert': tr('EDI do município · alerta', 'Municipal EDI · Warning'), 'API_alert': tr('API do município · alerta', 'Municipal API · Warning')}
    units = pd.DataFrame(u['units'])
    med = units.ratio.median()
    big = units.sort_values('upstream_km2', ascending=False).head(6)
    st.markdown(tr(
        f'<div class="card"><div class="section">A pergunta</div><p>O índice por município olha só a chuva que cai dentro do município. '
        f'Mas um rio enche com a chuva de toda a bacia acima dele. Aqui, para cada um dos {len(units)} municípios, a chuva diária foi '
        f'recalculada como a média sobre a <b>bacia a montante</b>: as ottobacias da ANA (BHO 2017, nível 6) que tocam o município, '
        f'mais todas as que drenam para elas (regra de Pfafstetter). Com essa chuva, EDI e API foram recalculados e avaliados com o mesmo '
        f'procedimento, os mesmos eventos e os mesmos dias sem evento da versão por município. <b>Com esse resultado, o estudo e a previsão passaram a usar a chuva da bacia</b>; esta aba mostra a comparação.</p>'
        f'<p class="note">Mediana: a área a montante é {T.num(med, 1)} vezes a área do município. Maiores bacias: '
        + ', '.join(f'{T.esc(x.nome)} ({T.num(x.upstream_km2 / 1000, 0)} mil km²)' for x in big.itertuples()) + '.</p></div>',
        f'<div class="card"><div class="section">The question</div><p>The municipal index only looks at the rain falling inside the municipality. '
        f'But a river rises with the rain over its whole upstream basin. Here, for each of the {len(units)} municipalities, daily rainfall was '
        f'recomputed as the mean over the <b>upstream basin</b>: the ANA Otto-coded basins (“ottobacias”, BHO 2017, level 6) touching the municipality, '
        f'plus all those draining into them (Pfafstetter rule). With that rainfall, EDI and API were recomputed and evaluated with the same '
        f'procedure, the same events and the same event-free days as the municipal version. <b>Based on this, the study and the forecast now use basin rainfall</b>; this tab shows the comparison.</p>'
        f'<p class="note">Median: the upstream area is {T.num(med, 1)} times the municipality area. Largest basins: '
        + ', '.join(f'{T.esc(x.nome)} ({T.num(x.upstream_km2 / 1000, 0)}k km²)' for x in big.itertuples()) + '.</p></div>'),
        unsafe_allow_html=True)
    cols = ['EDI', 'EDI_bacia', 'API', 'API_bacia']
    loyo, hold, fin = u['out_of_sample']['LOYO'], u['out_of_sample']['holdout_2013-2020_vs_2021-2024'], u['final_thresholds_all_years']
    rows = []
    for c in cols + [c + '_alert' for c in cols]:
        x = dict(loyo[c])
        base = c.replace('_alert', '')
        x['AUC'] = u['auc'][c]['AUC'] if c in u['auc'] else None
        thr = fin[base]['alert_pofd2pct' if c.endswith('_alert') else 'attention']
        x['extra'] = f'<td>{T.num(hold[c]["TSS"], 2)}</td><td>{fmt_index(thr, base)}</td>'
        rows.append((N.get(c, c), x))
    a, b = st.columns([1.35, 1])
    with a:
        st.markdown(f'<div class="section">{tr("Município × bacia a montante · fora da amostra (deixando um ano de fora)", "Municipality vs upstream basin · out-of-sample (leave-one-year-out)")}</div>',
                    unsafe_allow_html=True)
        st.markdown(_score_table(rows, tr('<th>Índice</th><th>AUC</th><th>Detecção</th><th>Atenção sem evento</th><th>TSS (IC95%)</th>'
                                          '<th>TSS teste 2021–24</th><th>Limiar final</th>',
                                          '<th>Index</th><th>AUC</th><th>Detection</th><th>Watch without event</th><th>TSS (95% CI)</th>'
                                          '<th>TSS test 2021–24</th><th>Final threshold</th>')), unsafe_allow_html=True)
    with b:
        st.markdown(f'<div class="card"><div class="section">{tr("A chuva da bacia melhora o índice?", "Does basin rainfall improve the index?")}</div>'
                    f'{_paired_rows(u["paired"], N)}<p class="note" style="margin-top:8px">'
                    + tr('Diferença pareada do TSS fora da amostra, bootstrap em blocos (2.000 réplicas). Critério registrado antes: só conta como '
                         'melhora se o IC95% inteiro ficar acima de 0.',
                         'Paired out-of-sample TSS difference, block bootstrap (2,000 replicates). Criterion registered beforehand: it only counts as '
                         'an improvement if the whole 95% CI is above 0.') + '</p></div>', unsafe_allow_html=True)
        t25 = u.get('test_2025', {})
        if 'error' not in t25 and t25:
            rows25 = ''.join(f'<div class="row"><span>{N.get(c, c)}</span><b>TSS {T.num(t25[c]["TSS"], 2)} <span class="muted">'
                             f'({T.num(t25[c]["TSS_CI95"][0], 2)}–{T.num(t25[c]["TSS_CI95"][1], 2)})</span></b></div>' for c in cols)
            st.markdown(f'<div class="card" style="margin-top:10px"><div class="section">{tr("Teste independente 2025 · limiares congelados", "Independent 2025 test · frozen thresholds")}</div>'
                        f'{rows25}{_paired_rows(t25.get("paired", {}), N)}</div>', unsafe_allow_html=True)
    show = units.sort_values('ratio', ascending=False)[['nome', 'corridors', 'municipality_km2', 'upstream_km2', 'ratio', 'upstream_basins']]
    with st.expander(tr('Área a montante por município', 'Upstream area by municipality')):
        st.markdown('<table class="t"><tr>' + tr('<th>Município</th><th>BR</th><th>Área do município</th><th>Área a montante</th><th>Razão</th><th>Ottobacias</th>',
                                               '<th>Municipality</th><th>BR</th><th>Municipality area</th><th>Upstream area</th><th>Ratio</th><th>Otto basins</th>')
                    + '</tr>' + ''.join(f'<tr><td>{T.esc(x.nome)}</td><td>{T.esc(x.corridors)}</td><td>{T.num(x.municipality_km2, 0)} km²</td>'
                                        f'<td>{T.num(x.upstream_km2, 0)} km²</td><td>{T.num(x.ratio, 1)}×</td><td>{x.upstream_basins}</td></tr>'
                                        for x in show.itertuples()) + '</table>', unsafe_allow_html=True)


def two_keys_table(v):
    """Detection, false alarm and TSS of the dashboard (basin) indices against S2iD records and against river floods."""
    tr = T.tr
    pct = lambda x, d=0: T.num(x * 100, d) + '%'
    r = load_json('results.json')
    g = load_json('second_trigger.json')
    if r is None:
        return ''
    loyo = r['out_of_sample']['LOYO']
    cell = lambda x: (f'<td>{pct(x["POD"])}</td><td>{pct(x["POFD"], 1)}</td><td><b>{T.num(x["TSS"], 2)}</b></td>'
                      if x else '<td>–</td><td>–</td><td>–</td>')
    body = ''
    rows = [(tr('EDI · atenção · regra do painel = cartões', 'EDI · Watch · dashboard rule = cards'),
             g['designs']['LOYO']['EDI']['with_P3'] if g else None, v['scores'].get('EDI_bacia_rule')),
            (tr('API · atenção · regra do painel = cartões', 'API · Watch · dashboard rule = cards'),
             g['designs']['LOYO']['API']['with_P3'] if g else None, v['scores'].get('API_bacia_rule')),
            (tr('EDI · atenção · índice sozinho', 'EDI · Watch · index alone'), loyo.get('EDI'), v['scores'].get('EDI_bacia')),
            (tr('API · atenção · índice sozinho', 'API · Watch · index alone'), loyo.get('API'), v['scores'].get('API_bacia')),
            (tr('EDI · alerta', 'EDI · Warning'), loyo.get('EDI_alert'), v['scores'].get('EDI_bacia_alert')),
            (tr('API · alerta', 'API · Warning'), loyo.get('API_alert'), v['scores'].get('API_bacia_alert'))]
    for label, atlas, river in rows:
        body += f'<tr><td>{label}</td>{cell(atlas)}{cell(river)}</tr>'
    sub = tr('<th>Detec.</th><th>Alarme falso</th><th>TSS</th>', '<th>Detect.</th><th>False alarm</th><th>TSS</th>') * 2
    head = tr('<tr><th></th><th colspan="3">Registros do S2iD (Defesa Civil)</th><th colspan="3">Cheia dos rios (ANA)</th></tr>',
              '<tr><th></th><th colspan="3">S2iD records (Civil Defence)</th><th colspan="3">River floods (ANA)</th></tr>')
    title = tr('Mesma regra, dois gabaritos · índices da bacia (os do painel)', 'Same rule, two answer keys · basin indices (the dashboard ones)')
    note = tr('<p class="note"><b>Detecção</b>: fração dos eventos com o município em atenção (ou alerta) no dia ou na véspera. '
              '<b>Alarme falso</b>: fração dos dias sem evento em que o nível ficou em atenção (ou alerta). '
              'Em cada linha a regra é a mesma nas duas colunas; muda o gabarito e, junto, os municípios (todos os dos corredores × os 25 com estação) '
              'e os limiares (escolhidos sem o ano testado × congelados). As duas primeiras linhas são as dos cartões do topo. '
              'Contra os rios, a regra do painel foi aplicada com os limiares congelados, sem nada reajustado (descritivo).</p>',
              '<p class="note"><b>Detection</b>: share of events with the municipality at Watch (or Warning) on the day or the day before. '
              '<b>False alarm</b>: share of event-free days on which the level was at Watch (or Warning). '
              'In each row the rule is the same in both columns; the answer key changes and, with it, the municipalities (all corridor ones vs the 25 with a gauge) '
              'and the thresholds (fitted without the tested year vs frozen). The first two rows are those of the cards at the top. '
              'Against rivers, the dashboard rule was applied with the frozen thresholds, nothing re-tuned (descriptive).</p>')
    return (f'<div class="section" style="margin-top:10px">{title}</div>'
            f'<table class="t wrap">{head}<tr><th></th>{sub}</tr>{body}</table>{note}')


def rivers_tab(N, N_mun):
    tr = T.tr
    v = load_json('river_validation.json')
    if v is None:
        st.info(tr('Validação com nível dos rios ainda não executada (python -m floodwatch.ana download/series e '
                   'python -m floodwatch.ana_validation rivers).',
                   'River-level validation not run yet (python -m floodwatch.ana download/series and '
                   'python -m floodwatch.ana_validation rivers).'))
        return
    N = {**N, 'EDI': tr('EDI do município', 'Municipal EDI'), 'API': tr('API do município', 'Municipal API'),
         'EDI_alert': tr('EDI do município · alerta', 'Municipal EDI · Warning'), 'API_alert': tr('API do município · alerta', 'Municipal API · Warning'),
         'P30': tr('Chuva 30 dias (bacia)', '30-day rainfall (basin)')}
    panel = tr(' <span class="muted">· painel</span>', ' <span class="muted">· dashboard</span>')
    for k in ('EDI_bacia', 'API_bacia', 'EDI_bacia_alert', 'API_bacia_alert'):
        N[k] = '<b>' + N[k] + '</b>' + panel
    used = [s for s in v['stations'] if s.get('used')]
    num_table = two_keys_table(v)
    st.markdown(tr(
        f'<div class="card"><div class="section">Outra referência de evento: o rio acima da cheia</div><p>Os limiares foram calibrados com '
        f'registros da Defesa Civil (S2iD), que dependem de o município pedir o registro. Aqui o evento é físico: a cota diária de uma estação '
        f'fluviométrica da ANA (HidroWeb) passa da <b>mediana dos máximos anuais</b> da própria estação, uma aproximação da cheia de 2 anos. '
        f'{len(used)} estações em {v["municipalities"]} municípios dos corredores, 2013–2024: {v["events"]} eventos em {v["episodes"]} episódios. '
        f'Os limiares <b>não foram reajustados</b>: são os mesmos calibrados com o S2iD.</p>'
        f'<div class="section" style="margin-top:10px">Por que estes números diferem dos cartões do topo</div>'
        f'<p>A régua é a mesma (o índice da bacia com o limiar do painel). O que muda é o <b>gabarito</b>, ou seja, o que conta como evento:</p>'
        f'<table class="t wrap"><tr><th></th><th>Cartões do topo</th><th>Esta aba</th></tr>'
        f'<tr><td>Evento</td><td>registro de desastre na Defesa Civil (S2iD)</td><td>rio acima da cheia na régua da ANA</td></tr>'
        f'<tr><td>Regra testada</td><td>regra completa do painel: índice OU chuva de 3 dias</td><td>a mesma regra (tabela abaixo) e o índice sozinho (tabela seguinte)</td></tr>'
        f'<tr><td>Limiares</td><td>ajustados sem o ano testado (um ano de fora por vez)</td><td>os congelados do painel, sem reajuste</td></tr>'
        f'<tr><td>Municípios</td><td>todos os {N_mun} dos corredores</td><td>só os {v["municipalities"]} com estação da ANA</td></tr>'
        f'<tr><td>Papel</td><td><b>calibração e resultado principal</b></td><td>checagem independente com um evento físico</td></tr></table>'
        f'{num_table}'
        f'<p>A detecção é maior aqui porque o rio só sobe depois de dias ou semanas de chuva acumulada, exatamente o que o índice mede. '
        f'Muitos registros do S2iD vêm de chuva forte e localizada (alagamento urbano, deslizamento) sem solo encharcado antes, e o índice não os vê. '
        f'Um rio acima da cheia sem registro no S2iD conta como evento aqui e não conta nos cartões. O alarme falso também é menor nos rios: '
        f'os dias sem evento são outros (só dias com leitura na estação), e um dia de chuva acumulada sem registro no S2iD pode ter tido cheia de rio.</p>'
        f'<p class="note">As linhas em negrito, “da bacia”, são as do painel. As linhas “do município” ficam só como comparação: mesmo procedimento, '
        f'com a chuva sobre o município e limiares calibrados com essa chuva.</p></div>',
        f'<div class="card"><div class="section">A different event reference: the river above flood level</div><p>The thresholds were calibrated with '
        f'Civil Defence records (S2iD), which depend on the municipality requesting them. Here the event is physical: the daily stage of an ANA '
        f'river gauge (HidroWeb) exceeds the station’s own <b>median of annual maxima</b>, an approximation of the 2-year flood. '
        f'{len(used)} gauges in {v["municipalities"]} corridor municipalities, 2013–2024: {v["events"]} events in {v["episodes"]} episodes. '
        f'The thresholds were <b>not re-tuned</b>: they are the same ones calibrated with S2iD.</p>'
        f'<div class="section" style="margin-top:10px">Why these numbers differ from the cards at the top</div>'
        f'<p>The ruler is the same (the basin index with the dashboard threshold). What changes is the <b>answer key</b>, i.e. what counts as an event:</p>'
        f'<table class="t wrap"><tr><th></th><th>Cards at the top</th><th>This tab</th></tr>'
        f'<tr><td>Event</td><td>disaster record with Civil Defence (S2iD)</td><td>river above flood level at the ANA gauge</td></tr>'
        f'<tr><td>Rule tested</td><td>full dashboard rule: index OR 3-day rainfall</td><td>the same rule (table below) and the index alone (next table)</td></tr>'
        f'<tr><td>Thresholds</td><td>fitted without the tested year (leave one year out)</td><td>the frozen dashboard ones, not re-tuned</td></tr>'
        f'<tr><td>Municipalities</td><td>all {N_mun} corridor municipalities</td><td>only the {v["municipalities"]} with an ANA gauge</td></tr>'
        f'<tr><td>Role</td><td><b>calibration and main result</b></td><td>independent check with a physical event</td></tr></table>'
        f'{num_table}'
        f'<p>Detection is higher here because a river only rises after days or weeks of accumulated rain, which is exactly what the index measures. '
        f'Many S2iD records come from short, local downpours (urban flooding, landslides) without wet antecedent soil, which the index cannot see. '
        f'A river above flood level with no S2iD record counts as an event here but not in the cards. The false alarm is also lower for rivers: '
        f'the event-free days are different (only days with a gauge reading), and a day of accumulated rain without an S2iD record may have had a river flood.</p>'
        f'<p class="note">The bold “basin” rows are the dashboard ones. The “municipal” rows are only a comparison: same procedure, with rainfall '
        f'over the municipality and thresholds calibrated on that rainfall.</p></div>'), unsafe_allow_html=True)
    rows = []
    ft = v['frozen_thresholds']
    for c in ['EDI_bacia', 'API_bacia', 'EDI_bacia_alert', 'API_bacia_alert', 'EDI', 'API', 'EDI_alert', 'API_alert', 'P30']:
        if c not in v['scores']:
            continue
        x = dict(v['scores'][c])
        base = c.replace('_alert', '')
        x['AUC'] = v['auc'][c]['AUC'] if c in v['auc'] else None
        x['extra'] = f'<td>{fmt_index(ft[base]["alert" if c.endswith("_alert") else "attention"], base if base != "P30" else "API")}</td>'
        rows.append((N.get(c, c), x))
    a, b = st.columns([1.35, 1])
    with a:
        st.markdown(f'<div class="section">{tr("Limiares congelados × cheias medidas nos rios", "Frozen thresholds vs gauged river floods")}</div>',
                    unsafe_allow_html=True)
        st.markdown(_score_table(rows, tr('<th>Regra</th><th>AUC</th><th>Detecção</th><th>Atenção sem cheia</th><th>TSS (IC95%)</th><th>Limiar</th>',
                                          '<th>Rule</th><th>AUC</th><th>Detection</th><th>Watch without flood</th><th>TSS (95% CI)</th><th>Threshold</th>')),
                    unsafe_allow_html=True)
    with b:
        st.markdown(f'<div class="card"><div class="section">{tr("Comparações pareadas", "Paired comparisons")}</div>{_paired_rows(v["paired"], N)}'
                    f'<p class="note" style="margin-top:8px">' + tr(
                        'Bootstrap em blocos: cheias por episódio, dias sem cheia por ano-mês (2.000 réplicas). Validação extra, registrada antes de rodar; '
                        'não altera os limiares.',
                        'Block bootstrap: floods by episode, flood-free days by year-month (2,000 replicates). Extra validation, registered before running; '
                        'it does not change the thresholds.') + '</p></div>', unsafe_allow_html=True)
    rp = load_json('river_predictor.json')
    if rp:
        lab = {'river_d1': tr('Só o rio em cheia em D−1', 'River in flood on D−1 only'),
               'EDI': tr('EDI da bacia', 'Basin EDI'), 'EDI_or_river': tr('EDI da bacia OU rio em cheia', 'Basin EDI OR river in flood'),
               'API': tr('API da bacia', 'Basin API'), 'API_or_river': tr('API da bacia OU rio em cheia', 'Basin API OR river in flood')}
        rows = [(lab[k], rp['rules'][k]) for k in ['river_d1', 'EDI', 'EDI_or_river', 'API', 'API_or_river'] if k in rp['rules']]
        pairs = {k.replace('_or_river', '+rio' if T.lang() == 'pt' else '+river'): v for k, v in rp['paired'].items()}
        NN = {**N, 'EDI+rio': lab['EDI_or_river'], 'API+rio': lab['API_or_river'], 'EDI+river': lab['EDI_or_river'],
              'API+river': lab['API_or_river'], 'EDI': lab['EDI'], 'API': lab['API']}
        st.markdown(f'<div class="section">{tr("O nível do rio acrescenta ao índice? · registros S2iD", "Does the river level add to the index? · S2iD records")}</div>'
                    + '<p class="note">' + tr(
                        f'{rp["municipalities"]} municípios com estação, {rp["events"]} eventos do S2iD ({rp["episodes"]} episódios), 2013–2024. '
                        'Rio em cheia em D−1 = alguma estação do município acima da sua cheia de 2 anos no dia anterior ao registro. '
                        'Limiares do índice já fixados; nenhum ajuste novo.',
                        f'{rp["municipalities"]} municipalities with a gauge, {rp["events"]} S2iD events ({rp["episodes"]} episodes), 2013–2024. '
                        'River in flood on D−1 = any gauge of the municipality above its 2-year flood on the day before the record. '
                        'Index thresholds already fixed; no new tuning.') + '</p>', unsafe_allow_html=True)
        a2, b2 = st.columns([1.35, 1])
        with a2:
            st.markdown(_score_table(rows, tr('<th>Regra</th><th>AUC</th><th>Detecção</th><th>Atenção sem evento</th><th>TSS (IC95%)</th>',
                                              '<th>Rule</th><th>AUC</th><th>Detection</th><th>Watch without event</th><th>TSS (95% CI)</th>')),
                        unsafe_allow_html=True)
        with b2:
            st.markdown(f'<div class="card">{_paired_rows(pairs, NN)}<p class="note" style="margin-top:8px">'
                        + tr('Só conta como ganho se o IC95% inteiro ficar acima de 0 (critério registrado antes). Na previsão, o nível do rio '
                             'é só observado: serviria para sinalizar cheia já em curso.',
                             'It only counts as a gain if the whole 95% CI is above 0 (criterion registered beforehand). In the forecast the river '
                             'level is observed only: it would flag a flood already under way.') + '</p></div>', unsafe_allow_html=True)
    with st.expander(tr('Estações usadas', 'Gauges used')):
        st.markdown('<table class="t"><tr>' + tr('<th>Estação</th><th>Rio</th><th>Município</th><th>Área de drenagem</th><th>Dias válidos</th><th>Cheia (cota)</th><th>Dias acima</th>',
                                               '<th>Gauge</th><th>River</th><th>Municipality</th><th>Drainage area</th><th>Valid days</th><th>Flood (stage)</th><th>Days above</th>')
                    + '</tr>' + ''.join(f'<tr><td>{s["station"]} · {T.esc(proper_name(s.get("name", "")))}</td><td>{T.esc(proper_name(s.get("river", "")))}</td>'
                                        f'<td>{T.esc(s.get("municipio", ""))}</td><td>{T.num(s["drainage_km2"], 0)} km²</td><td>{T.num(s["valid_share"] * 100, 0)}%</td>'
                                        f'<td>{T.num(s["threshold_cm"], 0)} cm</td><td>{T.num(s["days_over"], 0)}</td></tr>' for s in used) + '</table>'
                    + '<p class="note">' + tr('Fonte: ANA, HidroWeb (HidroSerieHistorica, cota diária; dado consistido quando disponível).',
                                              'Source: ANA, HidroWeb (HidroSerieHistorica, daily stage; consistent data when available).') + '</p>',
                    unsafe_allow_html=True)


def second_trigger_card():
    """Second short-term trigger (index OR 3-day rainfall), docs/protocol.md §9.3."""
    tr = T.tr
    g = load_json('second_trigger.json')
    if g is None:
        return
    pct = lambda x: T.num(x * 100, 0) + '%' if x is not None else '–'
    rows = ''
    for ix in ('EDI', 'API'):
        for dn, lab in (('LOYO', tr('por ano', 'by year')), ('holdout_2013-2020_vs_2021-2024', tr('teste 2021–24', 'test 2021–24'))):
            r = g['designs'][dn][ix]
            d = r['paired_with_minus_alone']
            rows += (f'<tr><td>{ix} · {lab}</td><td>{T.num(r["alone"]["TSS"], 2)}</td><td><b>{T.num(r["with_P3"]["TSS"], 2)}</b></td>'
                     f'<td>{pct(r["alone"]["POD"])} → {pct(r["with_P3"]["POD"])}</td>'
                     f'<td>{T.num(r["alone"]["POFD"] * 100, 1)}% → {T.num(r["with_P3"]["POFD"] * 100, 1)}%</td>'
                     f'<td>{T.num(d["diff"], 2, True)} <span class="muted">({T.num(d["CI95"][0], 2, True)} {tr("a", "to")} '
                     f'{T.num(d["CI95"][1], 2, True)})</span> · {ci_verdict(d["CI95"])}</td></tr>')
    fz = g['final_frozen']
    t25 = g.get('test_2025_descriptive', {})
    june = ''
    if 'error' not in t25 and t25:
        june = tr(' Em 2025 (só descritivo, porque a hipótese veio daí): na enchente de junho, ',
                  ' In 2025 (descriptive only, since the hypothesis came from it): in the June flood, ') + ', '.join(
            f'{ix} {pct(t25[ix]["june_share_alone"])} → {pct(t25[ix]["june_share_with_P3"])}' for ix in ('EDI', 'API')) + tr(
            ' dos eventos em atenção; TSS do ano ', ' of events at Watch; TSS for the year ') + ', '.join(
            f'{ix} {T.num(t25[ix]["alone"]["TSS"], 2)} → {T.num(t25[ix]["with_P3"]["TSS"], 2)}' for ix in ('EDI', 'API')) + '.'
    st.markdown(
        f'<div class="card" style="margin-top:10px"><div class="section">{tr("Teste do segundo gatilho · índice OU chuva de 3 dias", "Second-trigger test · index OR 3-day rainfall")}</div>'
        + tr(f'<p>Regra registrada antes de rodar: atenção se o índice passa do limiar <b>ou</b> se a chuva de 3 dias na bacia passa de b. '
             f'Em cada ano testado, b é escolhido só com os outros anos. Limiares finais congelados: EDI ≥ {T.num(fz["EDI"]["index_attention"], 2)} '
             f'ou P3 ≥ {T.num(fz["EDI"]["P3_mm"], 0)} mm; API ≥ {fmt_index(fz["API"]["index_attention"], "API")} ou P3 ≥ {T.num(fz["API"]["P3_mm"], 0)} mm.</p>',
             f'<p>Rule registered before running: Watch if the index exceeds its threshold <b>or</b> the 3-day basin rainfall exceeds b. '
             f'In each test year, b is chosen using the other years only. Final frozen thresholds: EDI ≥ {T.num(fz["EDI"]["index_attention"], 2)} '
             f'or P3 ≥ {T.num(fz["EDI"]["P3_mm"], 0)} mm; API ≥ {T.num(fz["API"]["index_attention"], 0)} mm or P3 ≥ {T.num(fz["API"]["P3_mm"], 0)} mm.</p>')
        + tr('<table class="t"><tr><th>Índice · teste</th><th>TSS só índice</th><th>TSS com gatilho</th><th>Detecção</th><th>Atenção sem evento</th><th>Diferença (IC95%)</th></tr>',
             '<table class="t"><tr><th>Index · test</th><th>TSS index only</th><th>TSS with trigger</th><th>Detection</th><th>Watch without event</th><th>Difference (95% CI)</th></tr>')
        + rows + '</table><p class="note" style="margin-top:8px">' + tr(
            'Só conta como ganho se o IC95% inteiro ficar acima de 0. A previsão diária grava o nível com o gatilho congelado no banco de '
            'previsões; os registros de 2026 em diante são o teste de confirmação.',
            'It only counts as a gain if the whole 95% CI is above 0. The daily forecast stores the level with the frozen trigger in the forecast '
            'archive; records from 2026 onwards are the confirmation test.') + june + '</p></div>', unsafe_allow_html=True)
