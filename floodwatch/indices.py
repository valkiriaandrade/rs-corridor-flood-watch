"""Public climate-indices 3.0.0 PE/EDI, with explicit calendar/calibration.

No data inference, thresholds, local validation claim, or pooling of locations.
"""
from importlib.metadata import version
import numpy as np
import pandas as pd
from climate_indices import flood,utils


def validate_daily(series):
    if not isinstance(series.index,pd.DatetimeIndex) or series.empty:raise ValueError('Série diária com datas é obrigatória')
    if series.index.tz is not None or series.index.hasnans:raise ValueError('Use rótulos de dia sem fuso e informe a janela em metadados')
    if not series.index.equals(series.index.normalize()):raise ValueError('Horário não pode ser apagado silenciosamente')
    if series.index.has_duplicates or not series.index.is_monotonic_increasing:raise ValueError('Datas duplicadas ou fora de ordem')
    if not series.index.equals(pd.date_range(series.index[0],series.index[-1],freq='D')):raise ValueError('Dias ausentes devem ser explícitos como NaN')
    values=series.to_numpy(dtype=float)
    if np.isinf(values).any() or (values[np.isfinite(values)]<0).any():raise ValueError('Chuva negativa ou infinita')
    if series.index[0].month!=1 or series.index[0].day!=1:raise ValueError('Calendário deve iniciar em 1º de janeiro; não preencher início com zero')
    return values


def compute(series,calibration_start,calibration_end,analysis_date):
    if version('climate-indices')!='3.0.0':raise ValueError('Requer climate-indices==3.0.0')
    values=validate_daily(series)
    analysis=pd.Timestamp(analysis_date).normalize()
    if calibration_end>=analysis.year:raise ValueError('Calibração deve terminar em ano completo anterior à análise')
    if calibration_start<=series.index[0].year:raise ValueError('Excluir o ano inicial de aquecimento da calibração')
    if calibration_end<=calibration_start:raise ValueError('Pelo menos dois anos completos de calibração')
    if pd.Timestamp(calibration_start,1,1)<series.index[0] or pd.Timestamp(calibration_end,12,31)>series.index[-1]:
        raise ValueError('Anos de calibração não estão completos na série')
    years=series.index[-1].year-series.index[0].year+1
    # Official NumPy convention: interpolate only the artificial non-leap Feb 29
    # before PE; never write these artificial days into the original observations.
    all_leap=utils.transform_to_366day(values,series.index[0].year,years)
    pe=flood.effective_precipitation(all_leap,duration=365)
    edi=flood.edi(pe,data_start_year=series.index[0].year,calibration_year_initial=int(calibration_start),
                  calibration_year_final=int(calibration_end),duration=365)
    pe_g=utils.transform_to_gregorian(pe,series.index[0].year)[:len(series)]
    edi_g=utils.transform_to_gregorian(edi,series.index[0].year)[:len(series)]
    result=pd.DataFrame({'date':series.index,'precipitation_mm':values,'pe_mm':pe_g,'edi':edi_g})
    if np.isinf(result[['pe_mm','edi']].to_numpy()).any():raise ValueError('Resultado infinito')
    if not result.pe_mm.notna().any():raise ValueError('Sem janela PE completa; não exibir série inteiramente ausente')
    if not result.edi.notna().any():raise ValueError('Sem EDI válido: confira cobertura e variância dos anos de calibração')
    meta={'library':'climate-indices==3.0.0','duration':365,'duration_basis':'365 positions in all-leap calendar',
          'data_start_year':series.index[0].year,'calibration_start':int(calibration_start),'calibration_end':int(calibration_end),
          'calendar':'366 positions/year; artificial non-leap Feb29 rain = mean(Feb28,Mar1), before PE; returned dates Gregorian',
          'gaps':'NaN preserved; PE windows containing a gap missing; EDI requires finite nonzero calibration variance',
          'warmup':'first 364 all-leap positions missing; first year excluded from calibration',
          'missing_rain_days':int(np.isnan(values).sum()),'pe_valid_days':int(np.isfinite(pe_g).sum()),
          'edi_valid_days':int(np.isfinite(edi_g).sum()),'interpretation':'umidade antecedente; sem limiar, probabilidade ou confirmação de inundação'}
    meta['missing_rain_days_by_year']={str(year):int(series[series.index.year==year].isna().sum()) for year in sorted(set(series.index.year))}
    calibration=pe.reshape(years,366)[calibration_start-series.index[0].year:calibration_end-series.index[0].year+1]
    samples=np.isfinite(calibration).sum(axis=0)
    meta['calibration_pe_samples_per_calendar_position']={'min':int(samples.min()),'max':int(samples.max())}
    meta['calibration_pe_valid_positions_by_year']={str(y):int(np.isfinite(calibration[i]).sum()) for i,y in enumerate(range(calibration_start,calibration_end+1))}
    return result,meta


def append_forecast(observed,forecast,calibration_start,calibration_end,analysis_date):
    """One location + model + member only; daily windows must match upstream."""
    validate_daily(observed)
    if forecast.empty or forecast.index.has_duplicates or not forecast.index.is_monotonic_increasing:
        raise ValueError('Previsão vazia, duplicada ou fora de ordem')
    if forecast.index[0]!=observed.index[-1]+pd.Timedelta(days=1):raise ValueError('Lacuna ou sobreposição entre observado e previsto')
    joined=pd.concat([observed,forecast])
    values,meta=compute(joined,calibration_start,calibration_end,analysis_date)
    values['origin']=np.where(values.date<=observed.index[-1],'observed','forecast')
    return values,meta


API_K = 0.90


def api(series, k=API_K):
    """Antecedent Precipitation Index (Kohler & Linsley 1951), API(d) = k*API(d-1) + P(d), mm, on the real calendar.

    climate-indices 3.0.0 `flood.antecedent_precipitation_index`, zero seed, nan_policy 'propagate' (a missing day
    makes the index missing from then on, never silently zero). All library defaults; only the required decay k is given.
    """
    if version('climate-indices') != '3.0.0':
        raise ValueError('Requer climate-indices==3.0.0')
    values = validate_daily(series)
    return np.asarray(flood.antecedent_precipitation_index(values, k), float)
