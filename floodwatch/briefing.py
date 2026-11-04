"""Executive briefing (A4, Portuguese or English) rendered with matplotlib -> PDF bytes.

Page 1: bottom line per corridor, map, municipalities, hubs, reliability. Page 2: the coming days, one row per day."""
import io
import json
import textwrap

import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['pdf.fonttype'] = 42  # embed TrueType: Type 3 fonts render garbled in some PDF viewers at small sizes
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import pandas as pd

from .exposure import NODES
from .paths import ROOT, STUDY
from .ui_theme import C, LEVEL_COLOR

NAVY, MUTED, TEXT, BORDER = C['accent'], C['muted'], C['text'], C['border']
NODATA = C['nodata']
CORR = ['BR-116', 'BR-386', 'BR-290']

L = {
    'en': {'title': 'RS Highway Corridors · Flood-Potential Briefing',
           'sub': 'BR-116 · BR-386 · BR-290 · 86 municipalities · Rio Grande do Sul, Brazil',
           'issued': 'Issued', 'runs': 'ECMWF {e} · GFS {g} · observed rainfall to {o} 12 UTC', 'scen': 'Scenario: {s}',
           'levels': {-1: 'No data', 0: 'Normal', 1: 'Watch', 2: 'Warning'},
           'bottom': 'Bottom line', 'peak': 'Peak', 'none': 'no Watch in the horizon', 'mun_watch': 'municipalities at Watch or above',
           'actions': {-1: 'Index unavailable for part of the corridor; check the data feed.', 0: 'Monitor. No additional action.',
                       1: 'Confirm safety stock and alternative routes for critical loads.',
                       2: 'Trigger contingency plan: reschedule shipments, validate detours with the carrier.'},
           'map': 'Highest level in the horizon', 'heat': 'Corridor level by day (number = municipalities at Watch or above)',
           'top': 'Municipalities to watch', 'cols': ['Municipality', 'Road', 'Level', 'From', 'Max {p}'],
           'hubs': 'Public logistics / industrial references', 'model': 'Model guidance',
           'agree': '{br}: ECMWF {e} · GFS {g}',
           'skill': ('Verification 2024-2026 (archived runs vs observed rainfall): {b} forecast heavy rain (≥ 20 mm/day, D+1 to D+3) '
                     'better than {o} (ETS {vb} vs {vo}); both underestimated rain on flood-record days.'),
           'rel': 'How reliable is this?',
           'rel_txt': ('Watch = {p} ≥ {a}; Warning = {p} ≥ {w}. Thresholds come from {n} official flood events (S2iD, '
                       '2013-2024) and MERGE observed rainfall. Leave-one-year-out: {pod}% of events detected, Watch on {pofd}% of '
                       'event-free days, Peirce skill {tss} (95% CI {lo}-{hi}).'),
           'rel25': ' Independent 2025 test with frozen thresholds: Peirce skill {t} (95% CI {lo}-{hi}).',
           'dry': ' Floods after a dry spell are underestimated.',
           'exp': ' API: climate-indices 3.0.0 antecedent_precipitation_index, library defaults, k = 0.90.',
           'rel_end': (' The skill of the levels with forecast rainfall has not been measured. A level means conditions under which '
                       'flood records have historically occurred in the municipality, not a certainty of road closure.'),
           'p2': 'Coming days · {s}', 'p2sub': 'Day-by-day summary of the forecast horizon',
           'p2sum': 'Summary of the horizon', 'p2tab': 'Day by day',
           'p2cols': ['24 h window', 'Type', 'Mean rain', '', 'Highest rain (municipality)', 'BR-116', 'BR-386', 'BR-290',
                      'Watch+', 'Warning'],
           'p2rain': 'Rain: mm/day over the upstream basin; mean of the 86 municipalities; highest = either model',
           'kind': {'obs': 'observed', 'now': 'in progress', 'fc': 'forecast'},
           'win': 'to {d} 09h', 'p2chart': 'Mean basin rainfall per day (mm) · ECMWF vs GFS',
           'p2alert': 'Municipalities at Warning, by day', 'p2none_alert': 'No municipality at Warning in the horizon.',
           'sum_corr': '{br}: Watch or above from {a} to {b}; peak {pk} with {n}/{tot} municipalities{al}.',
           'sum_al': ', {k} of them at Warning', 'sum_quiet': '{brs}: Normal across the whole horizon.',
           'sum_quiet_n': '{br}: corridor Normal; at most {n} municipalities at Watch or above on the same day.',
           'sum_rain': ('Wettest forecast day: {d}, mean of {e} mm (ECMWF) and {g} mm (GFS) over the corridor municipalities; '
                        'highest value {mx} mm in {mun}.'),
           'p2note': ('Each day is the 24 h rainfall ending at 09:00 Brasília time (12 UTC), the MERGE/CPTEC convention used in '
                      'calibration. Observed rainfall up to {o}; forecast from then on. Corridor level: highest level present in at '
                      'least 20% of its municipalities (display rule, not validated); the number is municipalities at Watch or above / total. '
                      'Levels after the observed day depend on forecast rainfall, whose effect on the levels has not been measured.'),
           'foot': ('Independent study, not an official warning: follow Defesa Civil, CEMADEN and SGB. Forecast: ECMWF IFS and NOAA GFS '
                    'via Open-Meteo.com (CC BY 4.0). Observed rainfall: MERGE/CPTEC-INPE. Events: S2iD (Atlas Digital de Desastres, MIDR). '
                    'Roads: DNIT SNV. Municipalities: IBGE.')},
    'pt': {'title': 'Corredores Rodoviários RS · Briefing de Potencial de Inundação',
           'sub': 'BR-116 · BR-386 · BR-290 · 86 municípios · Rio Grande do Sul',
           'issued': 'Emitido', 'runs': 'ECMWF {e} · GFS {g} · chuva observada até {o} 12 UTC', 'scen': 'Cenário: {s}',
           'levels': {-1: 'Sem dado', 0: 'Normal', 1: 'Atenção', 2: 'Alerta'},
           'bottom': 'Resumo', 'peak': 'Pico', 'none': 'sem atenção no horizonte', 'mun_watch': 'municípios em atenção ou alerta',
           'actions': {-1: 'Índice indisponível em parte do corredor: verificar a atualização dos dados.',
                       0: 'Monitorar. Sem ação adicional.',
                       1: 'Confirmar estoques de segurança e rotas alternativas para cargas críticas.',
                       2: 'Acionar contingência: reprogramar embarques e validar desvios com o operador.'},
           'map': 'Maior nível no horizonte', 'heat': 'Nível do corredor por dia (número = municípios em atenção ou alerta)',
           'top': 'Municípios a acompanhar', 'cols': ['Município', 'Rodovia', 'Nível', 'Desde', '{p} máx.'],
           'hubs': 'Polos logísticos / industriais (referência pública)', 'model': 'Orientação sobre os modelos',
           'agree': '{br}: ECMWF {e} · GFS {g}',
           'skill': ('Verificação 2024-2026 (rodadas arquivadas × chuva observada): o {b} acertou mais a chuva forte (≥ 20 mm/dia, '
                     'D+1 a D+3) que o {o} (ETS {vb} × {vo}); os dois subestimaram a chuva nos dias com registro de inundação.'),
           'rel': 'Qual a confiabilidade?',
           'rel_txt': ('Atenção = {p} ≥ {a}; alerta = {p} ≥ {w}. Limiares calibrados com {n} eventos oficiais de inundação (S2iD, 2013-2024) e chuva observada MERGE. Deixando um ano de fora: {pod}% dos eventos detectados, '
                       'atenção em {pofd}% dos dias sem evento, TSS {tss} (IC95% {lo}-{hi}).'),
           'rel25': ' Teste independente 2025, limiares congelados: TSS {t} (IC95% {lo}-{hi}).',
           'dry': ' Inundações após estiagem são subestimadas.',
           'exp': ' API: antecedent_precipitation_index do climate-indices 3.0.0, padrões da biblioteca, k = 0,90.',
           'rel_end': (' O acerto dos níveis com chuva prevista não foi medido. O nível indica condição em que historicamente houve '
                       'registro de inundação no município, e não a certeza de interdição.'),
           'p2': 'Próximos dias · {s}', 'p2sub': 'Resumo dia a dia do horizonte de previsão',
           'p2sum': 'Resumo do horizonte', 'p2tab': 'Dia a dia',
           'p2cols': ['Janela de 24 h', 'Tipo', 'Chuva média', '', 'Maior chuva (município)', 'BR-116', 'BR-386', 'BR-290',
                      'Atenção+', 'Alerta'],
           'p2rain': 'Chuva: mm/dia na bacia a montante; média dos 86 municípios; maior = qualquer dos dois modelos',
           'kind': {'obs': 'observado', 'now': 'em curso', 'fc': 'previsão'},
           'win': 'até {d} 09h', 'p2chart': 'Chuva média na bacia por dia (mm) · ECMWF × GFS',
           'p2alert': 'Municípios em alerta, por dia', 'p2none_alert': 'Nenhum município em alerta no horizonte.',
           'sum_corr': '{br}: atenção ou alerta de {a} a {b}; pico {pk} com {n}/{tot} municípios{al}.',
           'sum_al': ', {k} deles em alerta', 'sum_quiet': '{brs}: normal em todo o horizonte.',
           'sum_quiet_n': '{br}: corredor normal; no máximo {n} municípios em atenção ou alerta no mesmo dia.',
           'sum_rain': ('Dia mais chuvoso previsto: {d}, média de {e} mm (ECMWF) e {g} mm (GFS) nos municípios dos corredores; '
                        'maior valor {mx} mm em {mun}.'),
           'p2note': ('Cada dia é a chuva de 24 h que termina às 09h de Brasília (12 UTC), convenção MERGE/CPTEC usada na calibração. '
                      'Chuva observada até {o}; daí em diante, previsão. Nível do corredor: o maior nível presente em pelo menos 20% '
                      'dos seus municípios (regra de exibição, não validada); o número é municípios em atenção ou alerta / total. Os níveis '
                      'depois do dia observado dependem da chuva prevista, cujo efeito sobre os níveis não foi medido.'),
           'foot': ('Estudo independente, não é alerta oficial: siga a Defesa Civil, o CEMADEN e o SGB. Previsão: ECMWF IFS e NOAA GFS '
                    'via Open-Meteo.com (CC BY 4.0). Chuva observada: MERGE/CPTEC-INPE. Eventos: S2iD (Atlas Digital de Desastres, MIDR). '
                    'Rodovias: DNIT SNV. Municípios: IBGE.')},
}
WEEK_PT = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']


def _num(x, d, lang):
    s = f'{x:.{d}f}'
    return s.replace('.', ',') if lang == 'pt' else s


def _day(d, lang, long=False):
    t = pd.Timestamp(d)
    if lang == 'pt':
        return f'{WEEK_PT[t.weekday()]} {t:%d/%m}' if long else f'{t:%d/%m}'
    return t.strftime('%a %d %b' if long else '%d %b')


def _ix(x, p, lang, alert=None):
    """Index value: EDI is dimensionless (2 decimals), API is in mm (1 decimal). A value just below the Warning
    threshold that rounds to it prints as '< alerta' so it never contradicts the level column."""
    d = 1 if p == 'API' else 2
    if alert is not None and x < alert and round(x, d) >= round(alert, d):
        return '< alerta' if lang == 'pt' else '< Warning'
    return f'{_num(x, d, lang)} mm' if p == 'API' else _num(x, d, lang)


def _color(level):
    return LEVEL_COLOR[level] if level >= 0 else NODATA


def build_figure(meta, levels, ctab, results, scenario, units=None, roads=None, lang='en', peaks=None):
    lang = 'pt' if lang == 'pt' else 'en'
    t = L[lang]
    thr = meta['thresholds']
    trig_path = STUDY / 'second_trigger.json'
    if trig_path.exists():  # operational rule = index + frozen 3-day trigger
        oos = json.loads(trig_path.read_text(encoding='utf-8'))['designs']['LOYO'][thr['predictor']]['with_P3']
    else:
        oos = results['out_of_sample']['LOYO'][thr['predictor']]
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.patch.set_facecolor('white')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def text(x, y, s, size=9, weight='normal', color=TEXT, **kw):
        ax.text(x, y, s, fontsize=size, fontweight=weight, color=color, va='top', **kw)

    def para(x, y, s, width, size=8.2, color=TEXT, step=0.0145):
        lines = textwrap.wrap(s, width)
        for k, line in enumerate(lines):
            text(x, y - k * step, line, size, color=color)
        return y - len(lines) * step

    def heading(y, s):
        text(0.05, y, s.upper(), 8.0, 'bold', color=C['accent2'])
        ax.plot([0.05, 0.95], [y - 0.017, y - 0.017], color=BORDER, lw=0.8)
        return y - 0.027

    # header band
    ax.add_patch(Rectangle((0, 0.905), 1, 0.095, color=NAVY))
    text(0.05, 0.977, t['title'], 15, 'bold', color='white')
    text(0.05, 0.951, t['sub'] + '  ·  ' + t['scen'].format(s=scenario), 8.4, color='#C9D5E3')
    created = pd.Timestamp(meta['created_utc'])
    fmt = '%Y-%m-%d %H UTC'
    text(0.05, 0.928, f'{t["issued"]} {created:%Y-%m-%d %H:%M} UTC · ' + t['runs'].format(
        e=pd.Timestamp(meta['runs']['ECMWF']).strftime(fmt), g=pd.Timestamp(meta['runs']['GFS']).strftime(fmt),
        o=meta['observed_cutoff']), 7.4, color='#C9D5E3')

    # bottom line: one card per corridor
    y = heading(0.885, t['bottom'])
    w, gap = 0.29, 0.02
    for i, br in enumerate(CORR):
        x0 = 0.05 + i * (w + gap)
        sub = ctab[ctab.BR == br]
        pk = sub.sort_values(['level', 'n_att'], ascending=False).iloc[0] if len(sub) else None
        lvl = int(pk.level) if pk is not None else -1
        ax.add_patch(FancyBboxPatch((x0, y - 0.118), w, 0.112, boxstyle='round,pad=0.003,rounding_size=0.008',
                                    fc='white', ec=BORDER, lw=0.8))
        ax.add_patch(Rectangle((x0 - 0.003, y - 0.121), 0.007, 0.118, color=_color(lvl)))
        text(x0 + 0.018, y - 0.012, br, 12, 'bold', color=NAVY)
        ax.add_patch(FancyBboxPatch((x0 + w - 0.088, y - 0.032), 0.078, 0.021, boxstyle='round,pad=0.002,rounding_size=0.004',
                                    fc=_color(lvl), ec='none'))
        ax.text(x0 + w - 0.049, y - 0.0215, t['levels'][lvl], fontsize=7.6, fontweight='bold', ha='center', va='center',
                color=TEXT if lvl in (1, -1) else 'white')
        if pk is not None and lvl > 0:
            days = sub[sub.level >= 1].date
            span = _day(days.min(), lang) + ('' if days.min() == days.max() else '–' + _day(days.max(), lang))
            text(x0 + 0.018, y - 0.041, f'{t["peak"]} {_day(pk.date, lang, True)} · {span}', 7.6, color=MUTED)
            text(x0 + 0.018, y - 0.056, f'{int(pk.n_att)}/{int(pk.n)} {t["mun_watch"]}', 7.6, color=MUTED)
        else:
            text(x0 + 0.018, y - 0.041, t['none'], 7.6, color=MUTED)
        para(x0 + 0.018, y - 0.076, t['actions'][lvl], 46, 7.4, step=0.0122)
    y -= 0.14

    # map (left) + corridor x day heatmap and municipality list (right)
    top = heading(y, t['map'] + '  ·  ' + t['top'])
    peak = levels.groupby('codarea')['level'].max()
    if units is not None:
        mx = fig.add_axes([0.04, top - 0.28, 0.40, 0.275])
        u = units.copy()
        u['lvl'] = u.codarea.astype(str).map(peak).fillna(-1).astype(int)
        u.plot(ax=mx, color=[_color(v) for v in u.lvl], edgecolor='white', linewidth=0.3)
        if roads is not None:
            roads.plot(ax=mx, color=NAVY, linewidth=0.9)
        mx.set_axis_off()
        mx.set_aspect('equal')
        for k, lv in enumerate([0, 1, 2, -1]):
            ax.add_patch(Rectangle((0.06 + k * 0.09, top - 0.296), 0.012, 0.008, color=_color(lv)))
            text(0.076 + k * 0.09, top - 0.2905, t['levels'][lv], 6.8, color=MUTED)
    if len(ctab):
        days = sorted(ctab.date.unique())
        hx = fig.add_axes([0.56, top - 0.11, 0.39, 0.1])
        for i, br in enumerate(CORR):
            for j, d in enumerate(days):
                r = ctab[(ctab.BR == br) & (ctab.date == d)]
                lvl = int(r.level.iloc[0]) if len(r) else -1
                hx.add_patch(Rectangle((j, i), 0.92, 0.86, color=_color(lvl)))
                if len(r):
                    hx.text(j + .46, i + .43, int(r.n_att.iloc[0]), ha='center', va='center', fontsize=7.2,
                            color=TEXT if lvl in (1, -1) else 'white', fontweight='bold')
        hx.set_xlim(0, len(days))
        hx.set_ylim(0, len(CORR))
        hx.set_yticks([i + .43 for i in range(len(CORR))], CORR, fontsize=7.6, color=TEXT)
        hx.set_xticks([j + .46 for j in range(len(days))], [_day(d, lang) for d in days], fontsize=6.6, color=MUTED)
        for s in hx.spines.values():
            s.set_visible(False)
        hx.tick_params(length=0)
        hx.invert_yaxis()
        text(0.5, top - 0.124, t['heat'], 6.6, color=MUTED)

    ty = top - 0.15
    act = levels[levels.level >= 1]
    cols_x = [0.5, 0.7, 0.775, 0.85, 0.905]
    for cx, name in zip(cols_x, t['cols']):
        text(cx, ty, name.format(p=thr['predictor']), 6.8, 'bold', color=MUTED)
    ty -= 0.016
    if act.empty:
        text(0.5, ty, '—', 7.5, color=MUTED)
        ty -= 0.014
    else:
        g = act.sort_values('date').groupby('nome').agg(level=('level', 'max'), first=('date', 'first'),
                                                         edi=('VAL' if 'VAL' in act else 'EDI', 'max'),
                                                         road=('corridors', 'first'))
        g = g.sort_values(['level', 'edi'], ascending=False)
        for nome, x in g.head(7).iterrows():
            text(cols_x[0], ty, textwrap.shorten(str(nome), 27, placeholder='…'), 7.2)
            text(cols_x[1], ty, f'BR-{x.road}', 7.0, color=MUTED)
            ax.add_patch(Rectangle((cols_x[2], ty - 0.0092), 0.008, 0.008, color=_color(int(x.level))))
            text(cols_x[2] + 0.012, ty, t['levels'][int(x.level)], 7.0)
            text(cols_x[3], ty, _day(x['first'], lang), 7.2, color=MUTED)
            text(cols_x[4], ty, _ix(x.edi, thr['predictor'], lang, thr['alert']), 7.2)
            ty -= 0.0138
        if len(g) > 7:
            text(cols_x[0], ty, f'+ {len(g) - 7}', 6.8, color=MUTED)
            ty -= 0.0138
    y = min(top - 0.31, ty) - 0.006

    # hubs (left) and model guidance (right)
    y = heading(y, t['hubs'] + '  ·  ' + t['model'])
    hub_y = y
    exposed = []
    for n in NODES:
        lv = levels[levels.nome == n['municipio']].level
        if len(lv):
            exposed.append((int(lv.max()), n))
    exposed.sort(key=lambda z: -z[0])
    for lvl, n in exposed[:6]:
        ax.add_patch(Rectangle((0.05, hub_y - 0.0095), 0.008, 0.008, color=_color(lvl)))
        tipo = n.get('tipo_en', n['tipo']) if lang == 'en' else n['tipo']
        text(0.063, hub_y, f'{n["municipio"]} · {t["levels"][lvl]}', 7.3, 'bold')
        text(0.063, hub_y - 0.0118, textwrap.shorten(f'{tipo} · {n["rota"]}', 60, placeholder='…'), 6.7, color=MUTED)
        hub_y -= 0.026
    my = y
    for br in CORR:
        e, g = (peaks or {}).get(('ECMWF', br)), (peaks or {}).get(('GFS', br))
        if e is not None and g is not None:
            text(0.5, my, t['agree'].format(br=br, e=t['levels'][e], g=t['levels'][g]), 7.4)
            my -= 0.0142
    sk = ROOT / 'data' / 'processed' / 'forecast_skill' / 'forecast_skill.json'
    if sk.exists():
        r = json.loads(sk.read_text(encoding='utf-8'))['primary']
        b = r['ranking'][0]
        o = [m for m in r['models'] if m != b][0]
        my = para(0.5, my - 0.004, t['skill'].format(b=b, o=o, vb=_num(r['primary'][b], 2, lang), vo=_num(r['primary'][o], 2, lang)),
                  62, 7.1, color=MUTED, step=0.0123)
    y = min(hub_y, my) - 0.01

    # reliability
    y = heading(y, t['rel'])
    p = thr['predictor']
    watch = _ix(thr['attention'], p, lang)
    if thr.get('trigger_p3_mm') is not None:
        watch += (' ou chuva de 3 dias ≥ ' if lang == 'pt' else ' or 3-day rain ≥ ') + f'{_num(thr["trigger_p3_mm"], 0, lang)} mm'
    rel = t['rel_txt'].format(p=p, a=watch, w=_ix(thr['alert'], p, lang),
                              n=results['n']['positives'], pod=_num(oos['POD'] * 100, 0, lang), pofd=_num(oos['POFD'] * 100, 1, lang),
                              tss=_num(oos['TSS'], 2, lang), lo=_num(oos['TSS_CI95'][0], 2, lang), hi=_num(oos['TSS_CI95'][1], 2, lang))
    v25p = STUDY / 'validation_2025.json'
    if v25p.exists():
        v = json.loads(v25p.read_text(encoding='utf-8'))
        a = v.get(f'{p}_attention')
        if a:
            rel += t['rel25'].format(t=_num(a['TSS'], 2, lang), lo=_num(a['TSS_CI95'][0], 2, lang), hi=_num(a['TSS_CI95'][1], 2, lang))
    rel += t['dry'] if p == 'EDI' else t['exp']
    rel += t['rel_end']
    para(0.05, y, rel, 132, 7.4, color=TEXT, step=0.013)

    # footer
    ax.plot([0.05, 0.95], [0.058, 0.058], color=BORDER, lw=0.8)
    para(0.05, 0.051, t['foot'], 155, 6.2, color=MUTED, step=0.0102)
    return fig


def _kind(d, cutoff, current):
    d = pd.Timestamp(d)
    return 'obs' if d <= cutoff else ('now' if d == current else 'fc')


def horizon_summary(levels, ctab, rain, lang):
    """Plain-language lines: per corridor, when Watch starts/ends and the peak; then the wettest forecast day."""
    t = L[lang]
    out, quiet = [], []
    for br in CORR:
        sub = ctab[ctab.BR == br].sort_values('date')
        on = sub[sub.level >= 1]
        if len(on):
            pk = on.sort_values(['level', 'n_att'], ascending=False).iloc[0]
            road = br.split('-')[1]
            mun = levels[levels.corridors.str.split('/').apply(lambda x: road in x)]
            k = mun[mun.level == 2].codarea.nunique()
            out.append(t['sum_corr'].format(br=br, a=_day(on.date.min(), lang, True), b=_day(on.date.max(), lang, True),
                                            pk=_day(pk.date, lang, True), n=int(pk.n_att), tot=int(pk.n),
                                            al=t['sum_al'].format(k=k) if k else ''))
        elif len(sub) and sub.n_att.max() > 0:
            out.append(t['sum_quiet_n'].format(br=br, n=int(sub.n_att.max())))
        else:
            quiet.append(br)
    if quiet:
        out.append(t['sum_quiet'].format(brs=' · '.join(quiet)))
    if rain is not None and len(rain):
        fc = rain[rain.kind != 'obs']
        if len(fc):
            wet = fc.groupby('date')['mean'].mean().idxmax()
            r = fc[fc.date == wet].set_index('model')
            top = r.sort_values('max', ascending=False).iloc[0]
            out.append(t['sum_rain'].format(d=_day(wet, lang, True),
                                            e=_num(r.loc['ECMWF', 'mean'], 0, lang) if 'ECMWF' in r.index else '–',
                                            g=_num(r.loc['GFS', 'mean'], 0, lang) if 'GFS' in r.index else '–',
                                            mx=_num(top['max'], 0, lang), mun=top['max_nome']))
    return out


def build_days_figure(meta, levels, ctab, scenario, rain, lang='en', now=None):
    """Page 2: summary of the coming days, one table row per 24 h window."""
    t = L[lang]
    cutoff = pd.Timestamp(meta['observed_cutoff'])
    now = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None) if now is None else pd.Timestamp(now)
    current = now.normalize() + pd.Timedelta(days=1 if now.hour >= 9 else 0)
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.patch.set_facecolor('white')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def text(x, y, s, size=9, weight='normal', color=TEXT, **kw):
        ax.text(x, y, s, fontsize=size, fontweight=weight, color=color, va='top', **kw)

    def para(x, y, s, width, size=8.2, color=TEXT, step=0.0145):
        lines = textwrap.wrap(s, width)
        for k, line in enumerate(lines):
            text(x, y - k * step, line, size, color=color)
        return y - len(lines) * step

    def heading(y, s):
        text(0.05, y, s.upper(), 8.0, 'bold', color=C['accent2'])
        ax.plot([0.05, 0.95], [y - 0.017, y - 0.017], color=BORDER, lw=0.8)
        return y - 0.027

    ax.add_patch(Rectangle((0, 0.935), 1, 0.065, color=NAVY))
    text(0.05, 0.979, t['p2'].format(s=scenario), 14, 'bold', color='white')
    text(0.05, 0.955, t['p2sub'] + '  ·  ' + t['sub'], 8.0, color='#C9D5E3')

    if rain is not None and len(rain):
        rain = rain.assign(kind=[_kind(d, cutoff, current) for d in rain.date])
    y = heading(0.915, t['p2sum'])
    for line in horizon_summary(levels, ctab, rain, lang):
        ax.add_patch(Rectangle((0.05, y - 0.0085), 0.005, 0.005, color=NAVY))
        y = para(0.062, y, line, 118, 7.8, step=0.0135) - 0.004
    y -= 0.008

    # day-by-day table
    y = heading(y, t['p2tab'])
    xs = [0.05, 0.188, 0.31, 0.36, 0.41, 0.60, 0.665, 0.73, 0.81, 0.885]
    for x, name in zip(xs, t['p2cols']):
        text(x, y, name, 6.9, 'bold', color=MUTED)
    text(xs[2], y - 0.0125, 'ECMWF', 6.2, color=MUTED)
    text(xs[3], y - 0.0125, 'GFS', 6.2, color=MUTED)
    y -= 0.03
    days = sorted(ctab.date.unique()) if len(ctab) else []
    r_ix = rain.set_index(['date', 'model']) if rain is not None and len(rain) else None
    row_h = 0.0215
    for i, d in enumerate(days):
        kind = _kind(d, cutoff, current)
        if i % 2 == 0:
            ax.add_patch(Rectangle((0.045, y - row_h + 0.004), 0.91, row_h, color='#F4F6F9', lw=0))
        weight = 'bold' if kind == 'now' else 'normal'
        text(xs[0], y - 0.003, t['win'].format(d=_day(d, lang, True)), 7.0, weight)
        text(xs[1], y - 0.003, t['kind'][kind], 7.0, color=MUTED if kind == 'obs' else TEXT)
        if r_ix is not None:
            for x, m in ((xs[2], 'ECMWF'), (xs[3], 'GFS')):
                if (d, m) in r_ix.index:
                    text(x, y - 0.003, _num(r_ix.loc[(d, m), 'mean'], 0, lang), 7.2)
            day_r = rain[rain.date == d].sort_values('max', ascending=False)
            if len(day_r):
                top = day_r.iloc[0]
                text(xs[4], y - 0.003, textwrap.shorten(f'{_num(top["max"], 0, lang)} mm · {top["max_nome"]}', 27, placeholder='…'), 7.0)
        for x, br in zip(xs[5:8], CORR):
            r = ctab[(ctab.BR == br) & (ctab.date == d)]
            lvl = int(r.level.iloc[0]) if len(r) else -1
            ax.add_patch(FancyBboxPatch((x, y - 0.0145), 0.052, 0.0135, boxstyle='round,pad=0.001,rounding_size=0.003',
                                        fc=_color(lvl), ec='none'))
            ax.text(x + 0.026, y - 0.0078, f'{int(r.n_att.iloc[0])}/{int(r.n.iloc[0])}' if len(r) else '–', fontsize=6.6,
                    fontweight='bold', ha='center', va='center', color=TEXT if lvl in (1, -1) else 'white')
        lv = levels[levels.date == d]
        text(xs[8], y - 0.003, str(int((lv.level >= 1).sum())), 7.2, 'bold')
        n_al = int((lv.level == 2).sum())
        text(xs[9], y - 0.003, str(n_al), 7.2, 'bold', color=LEVEL_COLOR[2] if n_al else MUTED)
        y -= row_h
    text(0.05, y - 0.002, t['p2rain'], 6.2, color=MUTED)
    for k, lv in enumerate([0, 1, 2, -1]):
        ax.add_patch(Rectangle((0.60 + k * 0.085, y - 0.0085), 0.011, 0.007, color=_color(lv)))
        text(0.614 + k * 0.085, y - 0.002, t['levels'][lv], 6.4, color=MUTED)
    y -= 0.03

    # daily rainfall chart (ECMWF vs GFS)
    if rain is not None and len(rain):
        y = heading(y, t['p2chart'])
        cx = fig.add_axes([0.08, y - 0.15, 0.87, 0.14])
        width = 0.38
        obs_n = sum(_kind(d, cutoff, current) == 'obs' for d in days)
        if obs_n:
            cx.axvspan(-0.5, obs_n - 0.5, color='#EEF1F5', zorder=0)
        for off, m, col in ((-width / 2, 'ECMWF', NAVY), (width / 2, 'GFS', C['accent2'])):
            r = rain[rain.model == m].set_index('date').reindex(days)
            cx.bar([j + off for j in range(len(days))], r['mean'].fillna(0), width=width, color=col, label=m, alpha=0.92)
        cx.set_xticks(range(len(days)), [_day(d, lang) for d in days], fontsize=6.8, color=MUTED)
        cx.tick_params(axis='y', labelsize=6.8, colors=MUTED, length=0)
        cx.tick_params(axis='x', length=0)
        for side in ('top', 'right', 'left'):
            cx.spines[side].set_visible(False)
        cx.spines['bottom'].set_color(BORDER)
        cx.grid(axis='y', color=BORDER, lw=0.5)
        cx.set_axisbelow(True)
        cx.legend(fontsize=6.8, frameon=False, loc='upper right')
        cx.set_xlim(-0.5, len(days) - 0.5)
        y -= 0.175

    # municipalities at Warning, by day
    y = heading(y, t['p2alert'])
    al = levels[levels.level == 2]
    if al.empty:
        text(0.05, y, t['p2none_alert'], 7.6, color=MUTED)
        y -= 0.016
    else:
        for d in days:
            names = sorted(al[al.date == d].nome.unique())
            if not names:
                continue
            text(0.05, y, _day(d, lang, True), 7.4, 'bold')
            y = para(0.15, y, ', '.join(names), 128, 7.2, step=0.0125) - 0.003
            if y < 0.13:
                break
        y -= 0.006

    # method note right after the content (never into the footer)
    para(0.05, max(y - 0.012, 0.105), t['p2note'].format(o=_day(cutoff, lang, True) + ' 09h'), 150, 6.6, color=MUTED, step=0.0112)
    ax.plot([0.05, 0.95], [0.058, 0.058], color=BORDER, lw=0.8)
    para(0.05, 0.051, t['foot'], 155, 6.2, color=MUTED, step=0.0102)
    return fig


def daily_rain(df, days):
    """Per (date, model): mean and max daily basin rainfall over the municipalities, on the given days.

    Uses rain_mm (the day itself); P1 is not used because the predictors take the max over d-1 and d."""
    if 'rain_mm' not in df:
        return None
    f = df[df.date.isin(days) & df.rain_mm.notna()]
    if f.empty:
        return None
    g = f.groupby(['date', 'model'])
    out = g['rain_mm'].mean().rename('mean').to_frame()
    top = f.loc[g['rain_mm'].idxmax()].set_index(['date', 'model'])
    out['max'] = top['rain_mm']
    out['max_nome'] = top['nome']
    return out.reset_index()


def briefing_pdf(meta, levels, ctab, results, scenario, units=None, roads=None, lang='en', ctab_by_model=None, fmt='pdf',
                 rain=None, page=1):
    """PDF: page 1 (bottom line, map, reliability) + page 2 (coming days). PNG: only the requested page.

    rain: output of daily_rain (one row per date and model); page 2 leaves the rainfall out if it is None."""
    from matplotlib.backends.backend_pdf import PdfPages
    lang = 'pt' if lang == 'pt' else 'en'
    peaks = None
    if ctab_by_model:
        peaks = {(m, br): int(tb[tb.BR == br].level.max()) for m, tb in ctab_by_model.items() for br in CORR if len(tb[tb.BR == br])}
    buf = io.BytesIO()
    if fmt == 'pdf':
        with PdfPages(buf) as pdf:
            for make in (lambda: build_figure(meta, levels, ctab, results, scenario, units, roads, lang, peaks),
                         lambda: build_days_figure(meta, levels, ctab, scenario, rain, lang)):
                fig = make()
                pdf.savefig(fig)
                plt.close(fig)
    else:
        fig = (build_figure(meta, levels, ctab, results, scenario, units, roads, lang, peaks) if page == 1
               else build_days_figure(meta, levels, ctab, scenario, rain, lang))
        fig.savefig(buf, format=fmt, dpi=110)
        plt.close(fig)
    return buf.getvalue()
