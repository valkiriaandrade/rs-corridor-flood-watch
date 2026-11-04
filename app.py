"""Executive app: page 1 corridor forecast, page 2 threshold study (Portuguese / English).

Run: streamlit run app.py --server.port 8530      (?lang=en opens in English)
"""
import streamlit as st

if 'lang' not in st.session_state:
    st.session_state.lang = 'en' if str(st.query_params.get('lang', 'pt')).lower().startswith('en') else 'pt'
EN = st.session_state.lang == 'en'

st.set_page_config(page_title='Flood Potential Monitor · RS Highways' if EN else 'Monitor de Potencial de Inundação · Rodovias RS',
                   page_icon=':material/flood:', layout='wide', initial_sidebar_state='collapsed')

from floodwatch import page_forecast, page_study


def _switch():
    choice = st.session_state._lang_choice
    if choice is None:  # clicking the selected option again clears it; keep the current language
        st.session_state._lang_choice = 'EN' if st.session_state.lang == 'en' else 'PT-BR'
        return
    st.session_state.lang = 'en' if choice == 'EN' else 'pt'
    st.query_params['lang'] = st.session_state.lang


nav = st.navigation([
    st.Page(page_forecast.render, title='Corridor forecast' if EN else 'Previsão por corredor', default=True),
    st.Page(page_study.render, title='Threshold study' if EN else 'Estudo do limiar', url_path='estudo'),
], position='top')
st.segmented_control('Idioma / Language', ['PT-BR', 'EN'], default='EN' if EN else 'PT-BR',
                        key='_lang_choice', on_change=_switch, label_visibility='collapsed')
nav.run()
