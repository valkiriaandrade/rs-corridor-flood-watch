"""Public logistics/industrial reference nodes (no supplier names, no private data).

Each node is a municipality-level public reference; the dashboard matches it to the
study units by municipality name. Nodes outside the corridor municipalities are shown
for context only and never receive a level.
"""
NODES = [
    {'municipio': 'Porto Alegre', 'tipo': 'Capital · aeroporto e distribuição',
     'tipo_en': 'State capital · airport and distribution', 'rota': 'BR-116 / BR-290'},
    {'municipio': 'Canoas', 'tipo': 'Refinaria e polo industrial',
     'tipo_en': 'Refinery and industrial hub', 'rota': 'BR-116 / BR-386'},
    {'municipio': 'Gravataí', 'tipo': 'Polo automotivo',
     'tipo_en': 'Automotive hub', 'rota': 'BR-290'},
    {'municipio': 'Triunfo', 'tipo': 'Polo petroquímico',
     'tipo_en': 'Petrochemical complex', 'rota': 'BR-386'},
    {'municipio': 'Caxias do Sul', 'tipo': 'Polo metalmecânico e de autopeças',
     'tipo_en': 'Metalworking and auto-parts hub', 'rota': 'BR-116'},
    {'municipio': 'Novo Hamburgo', 'tipo': 'Polo industrial do Vale do Sinos',
     'tipo_en': 'Sinos Valley industrial hub', 'rota': 'BR-116'},
    {'municipio': 'Lajeado', 'tipo': 'Agroindústria do Vale do Taquari',
     'tipo_en': 'Taquari Valley agribusiness', 'rota': 'BR-386'},
    {'municipio': 'Pelotas', 'tipo': 'Ligação com o porto de Rio Grande',
     'tipo_en': 'Link to the Port of Rio Grande', 'rota': 'BR-116'},
    {'municipio': 'Eldorado do Sul', 'tipo': 'Acesso rodoviário à Região Metropolitana',
     'tipo_en': 'Highway access to the Porto Alegre Metropolitan Region', 'rota': 'BR-290'},
    {'municipio': 'Uruguaiana', 'tipo': 'Fronteira e aduana com a Argentina',
     'tipo_en': 'Border crossing and customs with Argentina', 'rota': 'BR-290'},
]

# One sentence per level; operational and conservative.
ACTIONS = {
    -1: 'Índice indisponível em parte do corredor: verificar a atualização dos dados.',
    0: 'Monitorar. Sem ação adicional.',
    1: 'Confirmar estoques de segurança e rotas alternativas para cargas críticas da região.',
    2: 'Acionar plano de contingência: antecipar ou reprogramar embarques e validar rota alternativa com o operador logístico.',
}

ACTIONS_EN = {
    -1: 'Index unavailable for part of the corridor: check the data update.',
    0: 'Monitor. No further action.',
    1: 'Confirm safety stocks and alternative routes for critical cargo in the region.',
    2: 'Activate the contingency plan: bring forward or reschedule shipments and confirm an alternative route with the logistics provider.',
}
