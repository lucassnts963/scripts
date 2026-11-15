#!/usr/bin/env python3
"""Controle diário de medição do contrato Trocador de Calor 4600014468 (Montisol + Fercama).

Base única em SQLite (dados/medicao.sqlite). Tudo o que é planilha, BMM e painel sai daqui.
Backup diário em CSV (backup/AAAA-MM-DD/). Envios do app RDO chegam pelo n8n e só entram depois de aprovados.

  python medicao.py whatsapp ARQ.txt [--grupo NOME]   lê mensagens (app RDO ou texto livre) -> base, status a-conferir
  python medicao.py importar-grade ARQ.xlsx           grades diárias por TAG/turno (planilha de medição)
  python medicao.py importar-apresentacao data.json   produção e apontamento da apresentação do Trocador
  python medicao.py importar-bmm ARQ.xlsx --periodo N quantidades de HH e verbas de um BMM já enviado
  python medicao.py importar-entrada ARQ.xlsx         aba ENTRADA da planilha gerada (lançamento manual)
  python medicao.py confirmar ID [ID...] | --fonte HASH
  python medicao.py planilha [--saida ARQ.xlsx]       gera a planilha de controle e os BMMs por período
  python medicao.py conferir [--periodo N]            regras R1 a R10 e qualidade dos dados
  python medicao.py apresentacao PASTA [--aplicar]    leva a produção para o data.json da apresentação
  python medicao.py analise                           comportamento por turno, trocador, paradas e absenteísmo
  python medicao.py backup [--manter 60]              exporta todas as tabelas em CSV (backup/AAAA-MM-DD/)
  python medicao.py migrar-csv [PASTA]                carrega CSVs (formato do backup) na base SQLite
  python medicao.py sincronizar-n8n [--simular]       traz do n8n os envios do app aprovados pelo Lucas e registra

Regras do contrato: wiki/gestao/controle-de-itens-proposta-automacao.md (seção 3).
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, shutil, sqlite3, sys, unicodedata, urllib.request
from collections import defaultdict

# os dados (o SQLite, os CSV, a planilha) ficam no vault: MEDICAO_DIR; sem ele, a pasta deste arquivo
AQUI = os.environ.get('MEDICAO_DIR') or os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, 'dados')
BANCO = os.environ.get('MEDICAO_DB', os.path.join(DADOS, 'medicao.sqlite'))
BACKUP = os.path.join(AQUI, 'backup')
N8N_URL = os.environ.get('N8N_URL', 'http://n8n:5678')
N8N_TABELA = os.environ.get('MEDICAO_N8N_TABELA', '6rDsDBPw30iiqdEf')   # Data Table montisol_rdo_recebidos
QQP_CSV = os.path.join(AQUI, '..', 'qqp', 'qqp-trocador-calor-4600014468.csv')
EFETIVO_JSON = os.path.join(AQUI, '..', 'rdo', 'efetivo.json')

INICIO = dt.date(2026, 8, 28)
VALOR_CONTRATO = 65082432.60
GMM_PPT, GMM_APG, FAIXA = 4000, 120, 4000

TABELAS = {
    'ppu': ['id', 'data', 'turno', 'tag', 'grupo', 'servico', 'quantidade', 'retrabalho', 'encarregado',
            'equipe', 'fonte_tipo', 'fonte_ref', 'status', 'obs'],
    'hh': ['id', 'data', 'turno', 'equipe', 'colaborador', 'funcao', 'hn', 'he65', 'he100', 'adn', 'os',
           'fonte_tipo', 'fonte_ref', 'status', 'obs'],
    'presenca': ['id', 'data', 'turno', 'equipe', 'colaborador', 'funcao', 'situacao', 'justificativa',
                 'tag', 'encarregado', 'fonte_tipo', 'fonte_ref', 'status'],
    'ocorrencias': ['id', 'data', 'turno', 'tag', 'responsavel', 'motivo', 'inicio', 'fim', 'minutos',
                    'impacto', 'fonte_tipo', 'fonte_ref', 'status'],
    'lancamentos': ['id', 'periodo', 'item', 'quantidade', 'faturador', 'fonte_tipo', 'fonte_ref', 'status', 'obs'],
    'fontes': ['hash', 'recebido', 'data', 'grupo', 'remetente', 'formato', 'linhas', 'status', 'texto'],
    'trocadores': ['tag', 'grupo', 'tipo', 'tubos', 'id_apresentacao'],
    'recebidos': ['id', 'recebido_em', 'data', 'turno', 'modalidade', 'encarregado', 'aprovado_em', 'registrado_em',
                  'obs_lucas', 'linhas', 'payload'],
}
CHAVE = {'fontes': 'hash', 'trocadores': 'tag'}

# função do efetivo -> item base da QQP (hora normal); +10 HE 65%, +20 HE 100%, +30 adicional noturno
FUNCAO_ITEM = [('ENCARREGADO', 130), ('MARTELETE', 170), ('MINI PA', 210), ('MONTADOR', 250),
               ('SOLDADOR', 290), ('AJUDANTE', 330), ('CACAMBA', 370), ('MUNCK', 410), ('ROMPEDOR', 450),
               ('OPERADOR DE HIDROJATO', 530), ('JATISTA', 490)]
TIPO_HORA = {'hn': 0, 'he65': 10, 'he100': 20, 'adn': 30}
EQUIPES_HH = {'descontaminacao', 'area31'}  # equipes extras cobradas em HH (premissa de 27/10/2026)

# grupo do trocador e serviço -> itens (mão de obra Montisol, equipamento Fercama)
ITENS_PPU = {('precipitacao', 'desobstrucao'): ('30', '40'),
             ('aquecedor', 'desobstrucao'): ('60', '70'),
             ('aquecedor', 'garantia'): ('60', '70'),   # GMM paga por falta de liberação da Hydro
             ('aquecedor', 'abertura'): ('100', '110'),
             ('caustico', 'abertura'): ('90', None),
             ('bayer', 'abertura'): ('80', None)}


# ---------------------------------------------------------------- base (SQLite)
_con = None


def con():
    global _con
    if _con is None:
        os.makedirs(os.path.dirname(BANCO), exist_ok=True)
        _con = sqlite3.connect(BANCO)
        _con.row_factory = sqlite3.Row
        _con.execute('PRAGMA journal_mode=WAL')
        for t, cols in TABELAS.items():
            k = CHAVE.get(t, 'id')
            _con.execute(f'CREATE TABLE IF NOT EXISTS {t} (' + ', '.join(f'"{c}" TEXT' + (' PRIMARY KEY' if c == k else '') for c in cols) + ')')
        _con.execute('CREATE TABLE IF NOT EXISTS alteracoes (quando TEXT, tabela TEXT, chave TEXT, campo TEXT, antes TEXT, depois TEXT)')
        _con.commit()
    return _con


def _txt(v):
    return '' if v is None else str(v)


def ler(t):
    return [{k: _txt(r[k]) for k in r.keys()} for r in con().execute(f'SELECT * FROM {t} ORDER BY rowid')]


def gravar(t, linhas):
    """Regrava a tabela inteira numa transação, registrando em 'alteracoes' o que mudou de status."""
    c, k, cols = con(), CHAVE.get(t, 'id'), TABELAS[t]
    antes = {r[k]: r for r in ler(t)} if 'status' in cols else {}
    agora = dt.datetime.now().isoformat(timespec='seconds')
    with c:
        c.execute(f'DELETE FROM {t}')
        c.executemany(f'INSERT OR REPLACE INTO {t} ({",".join(chr(34) + x + chr(34) for x in cols)}) VALUES ({",".join("?" * len(cols))})',
                      [[_txt(r.get(x)) for x in cols] for r in linhas])
        for r in linhas:
            a = antes.get(_txt(r.get(k)))
            if a and a.get('status') != _txt(r.get('status')):
                c.execute('INSERT INTO alteracoes VALUES (?,?,?,?,?,?)', (agora, t, _txt(r.get(k)), 'status', a.get('status'), _txt(r.get('status'))))


def acrescentar(t, novas):
    """Acrescenta sem duplicar (mesma chave)."""
    c, cols = con(), TABELAS[t]
    with c:
        antes = c.total_changes
        c.executemany(f'INSERT OR IGNORE INTO {t} ({",".join(chr(34) + x + chr(34) for x in cols)}) VALUES ({",".join("?" * len(cols))})',
                      [[_txt(r.get(x)) for x in cols] for r in novas])
        return c.total_changes - antes


def hid(*partes):
    return hashlib.sha1('|'.join(str(p) for p in partes).encode()).hexdigest()[:10]


def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s or '') if unicodedata.category(c) != 'Mn').upper().strip()


def chave_tag(s):
    k = re.sub(r'[^A-Z0-9]', '', sem_acento(s))
    return re.sub(r'(?<![0-9])0+(?=[0-9])', '', k)


def num(x):
    try:
        return float(str(x).replace(',', '.')) if str(x).strip() not in ('', 'None') else 0.0
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- contrato
def periodo_de(d):
    """Período de medição (16 a 15). Nº 1 = 28/08 a 15/09/2026."""
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    ref = d if d.day >= 16 else (d.replace(day=1) - dt.timedelta(days=1))
    n = (ref.year - 2026) * 12 + ref.month - 8 + 1
    return max(n, 1) if d >= INICIO else 0


def limites(n):
    ini = INICIO if n == 1 else dt.date(2026 + (8 + n - 1 - 1) // 12, (8 + n - 1 - 1) % 12 + 1, 16)
    m = 8 + n  # mês do fim
    fim = dt.date(2026 + (m - 1) // 12, (m - 1) % 12 + 1, 15)
    return ini, fim


def qqp():
    with open(QQP_CSV, encoding='utf-8') as f:
        q = {r['item']: r for r in csv.DictReader(f, delimiter=';')}
    for it, r in q.items():
        d = r['descricao'].lower()
        r['faturador'] = 'Fercama' if ('equipamento' in d.split(' - ')[-1] or int(it) >= 570) else 'Montisol'
        r['preco'] = num(r['preco_unitario'])
        r['qtd_contrato'] = num(r['quantidade'])
    return q


def item_hh(funcao, tipo):
    f = sem_acento(funcao)
    for k, base in FUNCAO_ITEM:
        if k in f:
            return str(base + TIPO_HORA[tipo])
    return None


# ---------------------------------------------------------------- cadastros
def efetivo():
    try:
        return json.load(open(EFETIVO_JSON, encoding='utf-8'))['colaboradores']
    except Exception:
        return []


def achar_pessoa(nome, ef):
    t = [x for x in re.split(r'\s+', sem_acento(nome)) if len(x) > 2]
    if not t:
        return None
    c = [p for p in ef if all(x in sem_acento(p['nome']).split() for x in t)]
    return c[0] if len(c) == 1 else None


def equipe_de_frente(frente):
    f = sem_acento(frente)
    if 'CONTAMINA' in f:
        return 'descontaminacao'
    if 'AREA 31' in f:
        return 'area31'
    if 'LAVAGEM' in f or 'ACIDA' in f:
        return 'lavagem-acida'
    if 'DESOBSTRU' in f:
        return 'desobstrucao'
    return re.sub(r'[^a-z0-9]+', '-', f.lower()).strip('-')


def tags():
    return {chave_tag(r['tag']): r for r in ler('trocadores')}


def grupo_da_tag(tag):
    r = tags().get(chave_tag(tag))
    if r:
        return r['grupo']
    k = chave_tag(tag)
    return 'aquecedor' if re.match(r'HE2[A-D]', k) else 'precipitacao' if re.match(r'HE(41|6|7|5)', k) else ''


# ---------------------------------------------------------------- leitura do WhatsApp
DATA_RE = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{2,4})')
TAG_RE = re.compile(r'\bHE[\s-]*\d{1,2}\s*[A-D](?:[\s-]*\d{1,2}[A-Z]?)?(?:[\s-]*[A-D]\s*/\s*[A-D])?', re.I)


def data_de(txt):
    m = DATA_RE.search(txt)
    if not m:
        return ''
    d, mo, a = map(int, m.groups())
    a = a + 2000 if a < 100 else a
    try:
        return dt.date(a, mo, d).isoformat()
    except ValueError:
        return ''


def norm_turno(v):
    t = sem_acento(v).strip(' *')
    if re.search(r'\bADM\b|^0?7[:H]', t): return 'ADM'
    if re.match(r'^(15|TARDE)', t): return 'Tarde'
    if re.match(r'^(23|NOITE)', t): return 'Noite'
    return v.strip(' *')[:20]


def turno_de(txt):
    t = sem_acento(txt)
    m = re.search(r'TURNO:?\*?\s*([^\n]+)', t)
    if m and m.group(1).strip(' *'):
        return norm_turno(m.group(1))
    if re.search(r'\bADM\b', t): return 'ADM'
    if re.search(r'\b23[:H ]|\bNOITE\b|23:30', t): return 'Noite'
    if re.search(r'\b15[:H ]|\bTARDE\b', t): return 'Tarde'
    return ''


def campo(bloco, rotulo):
    m = re.search(r'^[•\s*]*' + rotulo + r'\*?:\*?\s*(.*)$', bloco, re.M | re.I)
    return m.group(1).strip() if m else ''


def ler_app_ppu(txt, h):
    """Mensagem do RDO de campo (modalidade PPU): um bloco por TAG + presença."""
    ppu, oc, pres = [], [], []
    blocos = re.split(r'\n\s*━{6,}\s*\n', txt)
    for b in blocos:
        if 'RELATÓRIO DIÁRIO DE PRODUÇÃO' in b:
            data, turno, tag = data_de(campo(b, r'📅 \*?Data')), campo(b, r'🔧 \*?Turno'), campo(b, r'🏷️ \*?TAG do trocador')
            q = num(campo(b, 'Tubos desobstruídos no turno'))
            ppu.append(dict(id=hid(h, tag, 'desob'), data=data, turno=turno, tag=tag, grupo=grupo_da_tag(tag),
                            servico='desobstrucao', quantidade=q, retrabalho=0, encarregado='',
                            equipe='desobstrucao', fonte_tipo='rdo-app', fonte_ref=h, status='a-conferir',
                            obs='; '.join(x for x in [campo(b, 'Situação atual'), campo(b, 'Pendências')] if x)))
            for i, p in enumerate(re.split(r'\*Parada \d+\*', b)[1:]):
                oc.append(dict(id=hid(h, tag, 'par', i), data=data, turno=turno, tag=tag,
                               responsavel=campo(p, 'Responsável'), motivo=campo(p, 'Motivo'),
                               inicio=campo(p, 'Início'), fim=campo(p, 'Término'),
                               minutos=num(campo(p, 'Tempo parado').split()[0] if campo(p, 'Tempo parado') else 0),
                               impacto=campo(p, 'Impacto na produção'), fonte_tipo='rdo-app', fonte_ref=h,
                               status='a-conferir'))
        elif 'PRESENÇA' in b or 'APONTAMENTO DE PRESENÇA' in b:
            pres += ler_presenca_app(b, h)
    return ppu, oc, pres


def ler_presenca_app(b, h):
    data, turno = data_de(campo(b, r'📅 \*?Data')), campo(b, r'🔧 \*?Turno')
    enc, eq = campo(b, r'👷 \*?Encarregado'), campo(b, r'🏷️ \*?Equipe')
    equipe = equipe_de_frente(eq) if eq else 'desobstrucao'
    out, sit = [], None
    for ln in b.splitlines():
        if 'PRESENTES' in ln: sit = 'presente'; continue
        if 'FALTAS' in ln: sit = 'falta'; continue
        if 'FÉRIAS' in ln or 'AFASTADOS' in ln: sit = 'ferias'; continue
        m = re.match(r'\s*\d+\.\s*(.+)', ln)
        if sit and m:
            partes = [x.strip() for x in m.group(1).split(' – ')]
            just = next((x.split(':', 1)[1].strip() for x in partes if x.startswith('Justificativa')), '')
            tag = next((x.split(':', 1)[1].strip() for x in partes if x.startswith('Deveria estar')), '')
            out.append(dict(id=hid(data, norm_turno(turno), sem_acento(partes[0])), data=data, turno=turno, equipe=equipe, colaborador=partes[0],
                            funcao=partes[1] if len(partes) > 1 and ':' not in partes[1] else '',
                            situacao=sit, justificativa=just, tag=tag, encarregado=enc,
                            fonte_tipo='rdo-app', fonte_ref=h, status='a-conferir'))
    return out


MARCA_OK = ('✅', '👷', '👨‍🔧', '👨', '🧑')
MARCA_NAO = ('❌', '⛔', '⚠️')
CABECALHOS = {'ATESTADO': 'atestado', 'FOLGA': 'folga', 'FALTA': 'falta', 'FERIAS': 'ferias'}


def ler_texto_livre(txt, h, grupo):
    """Feedback livre dos encarregados: data, turno, TAG, tubos e efetivo (heurística; tudo a conferir)."""
    ef = efetivo()
    data, turno = data_de(txt), turno_de(txt)
    enc = ''
    m = re.search(r'(?:ENC\.?|Enc\.?|L[ií]der)\s*:?\s*\*?([A-Za-zÀ-ú ]+)', txt)
    if m:
        enc = m.group(1).strip(' *')
    ppu, pres = [], []
    # tubos: "Total desobstruido=75" com a TAG mais próxima acima
    tag_atual = ''
    for ln in txt.splitlines():
        mt = TAG_RE.search(ln)
        if mt:
            tag_atual = mt.group(0).upper().replace(' ', '')
        mq = re.search(r'desobstru[ií]d[oa]s?(?:\s+no\s+turno)?\s*[=:]\s*(\d+)', ln, re.I)
        if mq and tag_atual:
            tag_atual = (tags().get(chave_tag(tag_atual)) or {}).get('tag', tag_atual)
            ppu.append(dict(id=hid(h, tag_atual, 'livre'), data=data, turno=turno, tag=tag_atual,
                            grupo=grupo_da_tag(tag_atual), servico='desobstrucao', quantidade=int(mq.group(1)),
                            retrabalho=0, encarregado=enc, equipe='desobstrucao', fonte_tipo='whatsapp-livre',
                            fonte_ref=h, status='a-conferir', obs='lido de texto livre'))
    # efetivo
    S_msg = sem_acento(txt)
    equipe_msg = next((e for k, e in (('CONTAMINA', 'descontaminacao'), ('AREA 31', 'area31'), ('ACIDA', 'lavagem-acida'),
                                      ('DESOBSTRU', 'desobstrucao')) if k in S_msg), '')
    equipe_sec = equipe_de_frente(grupo) if grupo else equipe_msg
    sit_sec = 'presente'
    for ln in txt.splitlines():
        s = ln.strip().lstrip('*').strip()
        if not s:
            continue
        S = sem_acento(s)
        if re.match(r'^[^A-Z]*(ENC|LIDER|OBS)\b', S):
            continue
        if s.startswith('🔰') or s.startswith('💠') or s.startswith('📝') or (s.startswith('⛔') and len(S) < 12):
            for k, v in CABECALHOS.items():
                if k in S:
                    sit_sec = v
                    break
            else:
                sit_sec = 'presente'
            if 'EXTRA' in S and 'AREA' not in S:
                equipe_sec = 'descontaminacao'
            else:
                for k, e in (('CONTAMINA', 'descontaminacao'), ('AREA 31', 'area31'), ('ACIDA', 'lavagem-acida'), ('DESOBSTRU', 'desobstrucao')):
                    if k in S:
                        equipe_sec = e
                        break
            continue
        marca_nao = s.startswith(MARCA_NAO)
        if not (s.startswith(MARCA_OK) or marca_nao or (sit_sec != 'presente' and S[:1].isalpha())):
            continue
        nome = re.sub(r'^[^\wÀ-ú]+', '', s).strip(' *')
        just = ''
        mj = re.search(r'\s*[(/\-–]\s*(.+?)\)?$', nome)
        if mj and (marca_nao or '(' in nome or '/' in nome or ' - ' in nome):
            just = mj.group(1).strip()
            nome = nome[:mj.start()].strip()
        if not nome or len(nome.split()) < 2 or TAG_RE.search(nome) or re.search(r'\d', nome):
            continue
        palavras = set(sem_acento(nome).split())
        if len(palavras) > 6 or palavras & {'FOI', 'POIS', 'PARA', 'MESMO', 'CONCLUIDO', 'TOTAL', 'AREA', 'PEDENTE',
                                             'PENDENTE', 'EQUIPE', 'JATEAMENTO', 'RAQUETE', 'RAQUETES', 'VAI', 'FEITO'}:
            continue
        p = achar_pessoa(nome, ef)
        sit = sit_sec if not marca_nao else ('ferias' if 'FERIAS' in sem_acento(just) else 'atestado' if 'ATESTADO' in sem_acento(just) else 'falta')
        nome_final = p['nome'] if p else nome
        pres.append(dict(id=hid(data, turno, sem_acento(nome_final)), data=data, turno=turno,
                         equipe=equipe_sec or (equipe_de_frente(p['frente']) if p else ''),
                         colaborador=nome_final, funcao=p['funcao'] if p else '', situacao=sit,
                         justificativa=just, tag='', encarregado=enc, fonte_tipo='whatsapp-livre', fonte_ref=h,
                         status='a-conferir' if p else 'a-conferir:sem-cadastro'))
    return ppu, [], pres


def separar_mensagens(texto):
    """Aceita um texto só, várias mensagens separadas por linha '---' ou o export do WhatsApp (dd/mm/aaaa hh:mm - Nome: ...)."""
    exp = re.compile(r'^\[?(\d{1,2}/\d{1,2}/\d{2,4})[ ,]+(\d{1,2}:\d{2})(?::\d{2})?\]?\s*[-–]?\s*([^:]{1,40}):\s', re.M)
    if len(exp.findall(texto)) >= 1 and exp.match(texto.lstrip()):
        partes, pos = [], [m for m in exp.finditer(texto)]
        for i, m in enumerate(pos):
            fim = pos[i + 1].start() if i + 1 < len(pos) else len(texto)
            partes.append((m.group(3).strip(), texto[m.end():fim].strip()))
        return partes
    return [('', t.strip()) for t in re.split(r'^\s*-{3,}\s*$', texto, flags=re.M) if t.strip()]


def cmd_whatsapp(a):
    texto = open(a.arquivo, encoding='utf-8').read() if a.arquivo != '-' else sys.stdin.read()
    fontes = {f['hash'] for f in ler('fontes')}
    tot = defaultdict(int)
    for remetente, msg in separar_mensagens(texto):
        h = hid(re.sub(r'\s+', ' ', msg))
        if h in fontes:
            tot['repetidas'] += 1
            continue
        if 'RELATÓRIO DIÁRIO DE PRODUÇÃO' in msg or 'PRESENÇA DA EQUIPE PPU' in msg:
            fmt, (ppu, oc, pres) = 'rdo-app-ppu', ler_app_ppu(msg, h)
        elif 'APONTAMENTO DE PRESENÇA' in msg:
            fmt, ppu, oc, pres = 'rdo-app-presenca', [], [], ler_presenca_app(msg, h)
        else:
            fmt, (ppu, oc, pres) = 'livre', ler_texto_livre(msg, h, a.grupo)
        tot['ppu'] += acrescentar('ppu', ppu)
        tot['ocorrencias'] += acrescentar('ocorrencias', oc)
        tot['presenca'] += acrescentar('presenca', pres)
        acrescentar('fontes', [dict(hash=h, recebido=dt.datetime.now().isoformat(timespec='minutes'),
                                    data=data_de(msg), grupo=a.grupo or '', remetente=remetente, formato=fmt,
                                    linhas=len(ppu) + len(oc) + len(pres), status='a-conferir',
                                    texto=msg[:4000])])
        fontes.add(h)
        tot['mensagens'] += 1
    print(json.dumps(tot, ensure_ascii=False))


# ---------------------------------------------------------------- retroativo
def cmd_importar_grade(a):
    import openpyxl
    wb = openpyxl.load_workbook(a.arquivo, data_only=True)
    ref = 'grade:' + os.path.basename(a.arquivo)
    novas = []
    for ws in wb.worksheets:
        if 'TROCADOR CALOR' not in ws.title.upper():
            continue
        datas = {c.column: c.value.date() for c in ws[6] if isinstance(c.value, dt.datetime)}
        item = tag = None
        for row in ws.iter_rows(min_row=8):
            vals = {c.column: c.value for c in row}
            if vals.get(2) not in (None, ''):
                item = str(vals[2])
            if vals.get(5) not in (None, ''):
                tag = str(vals[5]).strip()
            if not tag or tag.upper() in ('TOTAL',) or not vals.get(7):
                if tag and tag.upper() == 'TOTAL':
                    tag = None
                continue
            servico = 'abertura' if item in ('250', '240', '100.2') else 'desobstrucao'
            if 'GARANTIA' in sem_acento(tag):
                servico = 'garantia'
            grupo = 'aquecedor' if '- DIG' in ws.title.upper() else 'precipitacao'
            for col, d in datas.items():
                q = vals.get(col)
                if isinstance(q, (int, float)) and q:
                    novas.append(dict(id=hid(ref, ws.title, tag, vals[7], d, servico), data=d.isoformat(),
                                      turno=str(vals[7]), tag=tag, grupo=grupo, servico=servico, quantidade=q,
                                      retrabalho=0, encarregado='', equipe='desobstrucao',
                                      fonte_tipo='grade-medicao', fonte_ref=ref, status='confirmado',
                                      obs=f'item da planilha {item}'))
    cad = tags()
    for r in novas:
        k = chave_tag(r['tag'])
        if k not in cad and 'GARANTIA' not in k:
            cad[k] = dict(tag=r['tag'], grupo=r['grupo'], tipo='', tubos='', id_apresentacao='')
    gravar_trocadores(cad)
    print('linhas novas:', acrescentar('ppu', novas))


def gravar_trocadores(cad):
    gravar('trocadores', sorted(cad.values(), key=lambda r: r['tag']))


def cmd_importar_apresentacao(a):
    d = json.load(open(a.arquivo, encoding='utf-8'))
    tr = {t['id']: t for t in d['trocadores']}
    tipos = {t['id']: t for t in d['tiposTrocador']}
    turnos = {t['id']: t['nome'] for t in d['turnos']}
    # cadastro de trocadores
    cad = {}
    for t in d['trocadores']:
        tp = tipos.get(t.get('tipo'), {})
        g = 'aquecedor' if tp.get('grupo') == 'aquecedores' else 'precipitacao'
        cad[chave_tag(t['tag'])] = dict(tag=t['tag'], grupo=g, tipo=t.get('tipo', ''), tubos=t.get('tubosTotal') or '',
                                        id_apresentacao=t['id'])
    for k, r in tags().items():
        cad.setdefault(k, r)
    gravar_trocadores(cad)
    ref = 'apresentacao:4r9izcte4p'
    ate = a.ate or '9999'
    ppu = []
    for p in d['producao']:
        if p['data'] > ate:
            continue
        t = tr.get(p['trocador'])
        tag = t['tag'] if t else p['trocador']
        ppu.append(dict(id=hid(ref, p['id']), data=p['data'], turno=turnos.get(p['turno'], p['turno']), tag=tag,
                        grupo=grupo_da_tag(tag), servico='desobstrucao', quantidade=p['tubos'],
                        retrabalho=p.get('retrabalho', 0), encarregado=p.get('encarregado', ''),
                        equipe='desobstrucao', fonte_tipo='apresentacao', fonte_ref=ref, status='confirmado',
                        obs=p.get('obs', '')))
    oc = []
    for i in d.get('impactos', []):
        if i['data'] > ate:
            continue
        t = tr.get(i['trocador'])
        tp = next((x for x in d['tiposImpacto'] if x['id'] == i['tipo']), {})
        oc.append(dict(id=hid(ref, i['id']), data=i['data'], turno=turnos.get(i['turno'], i['turno']),
                       tag=t['tag'] if t else i['trocador'],
                       responsavel='Montisol' if tp.get('responsavel') == 'Contratada' else 'Hydro',
                       motivo=f"{tp.get('nome', i['tipo'])}: {i.get('descricao', '')}", inicio=i.get('inicio', ''),
                       fim=i.get('fim', ''), minutos='', impacto='', fonte_tipo='apresentacao', fonte_ref=ref,
                       status='confirmado'))
    ef = {e['id']: e for e in d.get('efetivo', [])}
    pres = []
    # apontamento nominal da apresentação só entra se não for dado de exemplo (ids apSEED)
    for ap in [x for x in d.get('apontamento', []) if not str(x['id']).startswith('apSEED')]:
        if ap['data'] > ate:
            continue
        e = ef.get(ap['colaborador'], {})
        pres.append(dict(id=hid(ref, ap['id']), data=ap['data'], turno=turnos.get(ap['turno'], ap['turno']),
                         equipe=ap.get('equipe', ''), colaborador=e.get('nome', ap['colaborador']),
                         funcao=e.get('funcao', ap.get('funcao', '')), situacao=ap['situacao'],
                         justificativa=ap.get('observacao', ''), tag=(tr.get(ap.get('trocador')) or {}).get('tag', ''),
                         encarregado=e.get('encarregado', ''), fonte_tipo='apresentacao', fonte_ref=ref,
                         status='confirmado'))
    print('ppu', acrescentar('ppu', ppu), 'ocorrencias', acrescentar('ocorrencias', oc),
          'presenca', acrescentar('presenca', pres), 'trocadores', len(cad))


def cmd_importar_bmm(a):
    import openpyxl
    wb = openpyxl.load_workbook(a.arquivo, data_only=True)
    ws = wb.worksheets[0]
    ref = 'bmm:' + os.path.basename(a.arquivo)
    q = qqp()
    novas = []
    for row in ws.iter_rows(min_row=12):
        it, qtd = row[1].value, row[13].value
        if isinstance(it, (int, float)) and str(int(it)) in q and isinstance(qtd, (int, float)) and qtd:
            it = str(int(it))
            if a.itens and it not in a.itens.split(','):
                continue
            novas.append(dict(id=hid(ref, a.periodo, it), periodo=a.periodo, item=it, quantidade=qtd,
                              faturador=q[it]['faturador'], fonte_tipo='bmm', fonte_ref=ref, status='a-conferir',
                              obs='quantidade do BMM enviado; sem apontamento diário na base'))
    print('lançamentos novos:', acrescentar('lancamentos', novas))


def cmd_importar_entrada(a):
    import openpyxl
    ws = openpyxl.load_workbook(a.arquivo, data_only=True)['ENTRADA']
    cab = [c.value for c in ws[3]]
    n = defaultdict(list)
    for row in ws.iter_rows(min_row=4, values_only=True):
        r = dict(zip(cab, row))
        if not r.get('tabela') or not r.get('data'):
            continue
        d = r['data'].date().isoformat() if hasattr(r['data'], 'date') else str(r['data'])[:10]
        base = dict(data=d, turno=r.get('turno') or '', fonte_tipo='entrada-manual',
                    fonte_ref='entrada:' + os.path.basename(a.arquivo), status='confirmado')
        if r['tabela'] == 'ppu':
            n['ppu'].append(dict(base, id=hid('ent', d, r.get('turno'), r.get('tag'), r.get('servico'), r.get('quantidade')),
                                 tag=r.get('tag') or '', grupo=grupo_da_tag(r.get('tag') or ''),
                                 servico=r.get('servico') or 'desobstrucao', quantidade=r.get('quantidade') or 0,
                                 retrabalho=0, encarregado=r.get('pessoa') or '', equipe='desobstrucao',
                                 obs=r.get('obs') or ''))
        elif r['tabela'] == 'hh':
            n['hh'].append(dict(base, id=hid('ent', d, r.get('turno'), r.get('pessoa'), r.get('hn'), r.get('he65')),
                                equipe=r.get('equipe') or '', colaborador=r.get('pessoa') or '',
                                funcao=r.get('funcao') or '', hn=r.get('hn') or 0, he65=r.get('he65') or 0,
                                he100=r.get('he100') or 0, adn=r.get('adn') or 0, os=r.get('os') or '',
                                obs=r.get('obs') or ''))
    for t, l in n.items():
        print(t, acrescentar(t, l))


def cmd_confirmar(a):
    for t in ('ppu', 'hh', 'presenca', 'ocorrencias', 'lancamentos', 'fontes'):
        base, k = ler(t), 0
        for r in base:
            chave = r.get('id') or r.get('hash')
            if chave in a.ids or (a.fonte and (r.get('fonte_ref') == a.fonte or r.get('hash') == a.fonte)):
                r['status'] = 'confirmado'
                k += 1
        if k:
            gravar(t, base)
            print(t, k)


def turno_cheio(t):
    """Turno de produção: Dia (Turno I, ADM), Tarde (Turno II) ou Noite (Turno III), qualquer que seja a fonte."""
    t = sem_acento(t)
    if t.startswith('TURNO III') or t.startswith('NOITE') or t.startswith('23') or t == 'T3':
        return 'Noite'
    if t.startswith('TURNO II') or t.startswith('TARDE') or t.startswith('15') or t == 'T2':
        return 'Tarde'
    return 'Dia'


# ---------------------------------------------------------------- cálculo da medição
def medir(n, so_confirmado=False):
    """Quantidade por item da QQP no período n, a partir da base. Devolve {item: (qtd, origem)}."""
    ini, fim = limites(n)
    ok = lambda r: (not so_confirmado or r['status'] == 'confirmado')
    noper = lambda r: r.get('data') and ini.isoformat() <= r['data'] <= fim.isoformat()
    tub = defaultdict(float)
    # mesma TAG/dia/turno vinda de duas fontes: vale a de maior prioridade
    prio = {'grade-medicao': 0, 'entrada-manual': 1, 'rdo-app-n8n': 1, 'rdo-app': 2, 'whatsapp-livre': 3, 'apresentacao': 4}
    melhor = {}
    for r in ler('ppu'):
        if not (noper(r) and ok(r)):
            continue
        k = (r['data'], turno_cheio(r['turno']), chave_tag(r['tag']), r['servico'])
        if k not in melhor or prio.get(r['fonte_tipo'], 9) < prio.get(melhor[k][0]['fonte_tipo'], 9):
            melhor[k] = [r]
        elif melhor[k][0]['fonte_tipo'] == r['fonte_tipo']:
            melhor[k].append(r)
    for rs in melhor.values():
        for r in rs:
            tub[(r['grupo'] or grupo_da_tag(r['tag']), r['servico'])] += num(r['quantidade'])
    med = defaultdict(float)
    T = tub[('precipitacao', 'desobstrucao')]
    med['30'] = T                          # prática atual (BMM 2): mão de obra em todos os tubos; ver R3
    med['40'] = min(T, FAIXA)
    med['50'] = max(T - FAIXA, 0)
    for (g, s), q in tub.items():
        if (g, s) in ITENS_PPU and (g, s) != ('precipitacao', 'desobstrucao'):
            mo, eq = ITENS_PPU[(g, s)]
            med[mo] += q
            if eq:
                med[eq] += q
    for r in ler('hh'):
        if not (noper(r) and ok(r)) or r['equipe'] not in EQUIPES_HH:
            continue
        for tipo in TIPO_HORA:
            it = item_hh(r['funcao'], tipo)
            if it and num(r[tipo]):
                med[it] += num(r[tipo])
    for r in ler('lancamentos'):
        if str(r['periodo']) == str(n) and ok(r):
            med[r['item']] += num(r['quantidade'])
    return {k: v for k, v in med.items() if v}, tub


def acumulado_ate(n):
    acc = defaultdict(float)
    for p in range(1, n):
        for it, q in medir(p)[0].items():
            acc[it] += q
    return acc


# ---------------------------------------------------------------- conferência
def conferir(n, hoje=None):
    hoje = hoje or dt.date.today()
    ini, fim = limites(n)
    med, tub = medir(n)
    q = qqp()
    R = []
    add = lambda cod, nivel, msg: R.append(dict(regra=cod, nivel=nivel, mensagem=msg))
    add('R1', 'ok', f'Medição nº {n}: {ini:%d/%m/%Y} a {fim:%d/%m/%Y}; entrega até {fim.replace(day=20):%d/%m/%Y}')
    T = tub[('precipitacao', 'desobstrucao')]
    if T > FAIXA:
        add('R3', 'atencao', f'Precipitação com {T:.0f} tubos: {T - FAIXA:.0f} acima da garantia (cobrados a mais, segundo o Lucas); '
                              f'a QQP só tem equipamento na faixa acima de 4.000 (item 50); confirmar que a mão de obra no item 30 '
                              f'(R$ {(T - FAIXA) * q["30"]["preco"]:,.2f}) é aceita')
    dias = (min(hoje, fim) - ini).days + 1
    tot_dias = (fim - ini).days + 1
    if dias > 0:
        for nome, g, meta in (('precipitação', ('precipitacao', 'desobstrucao'), GMM_PPT),
                              ('aquecedores de polpa', ('aquecedor', 'desobstrucao'), GMM_APG)):
            feito = tub[g] + (tub[('aquecedor', 'garantia')] if g[0] == 'aquecedor' else 0)
            esperado = meta * min(dias, tot_dias) / tot_dias
            nivel = 'ok' if feito >= meta or (hoje <= fim and feito >= esperado) else ('erro' if hoje > fim else 'atencao')
            extra = ''
            if n == 1:
                nivel, extra = ('ok' if feito >= meta else 'atencao'), f' (período parcial de {tot_dias} dias: conferir se a GMM é proporcional)'
            gar = tub[('aquecedor', 'garantia')] if g[0] == 'aquecedor' else 0
            if gar:
                extra += f'; {gar:.0f} tubos cobrados como garantia mínima (diferença paga porque a Hydro não liberou: precisa de evidência da não liberação por TAG e dia)'
            add('R4', nivel, f'GMM {nome}: {feito:.0f} de {meta} ({feito / meta:.0%}); ritmo esperado até hoje {esperado:.0f}{extra}')
    sem_hora = [r for r in ler('presenca') if ini.isoformat() <= r['data'] <= fim.isoformat()
                and r['equipe'] in EQUIPES_HH and r['situacao'] == 'presente']
    hh = [r for r in ler('hh') if ini.isoformat() <= r['data'] <= fim.isoformat() and r['equipe'] in EQUIPES_HH]
    if sem_hora and not hh:
        add('R5', 'atencao', f'{len(sem_hora)} presenças das equipes extras sem horas apontadas: HH do período ainda não sai da base')
    sem_item = sorted({r['funcao'] for r in hh if not item_hh(r['funcao'], 'hn')})
    if sem_item:
        add('R5', 'erro', 'Função sem item de HH na QQP: ' + ', '.join(sem_item))
    pend = defaultdict(int)
    for t in ('ppu', 'presenca', 'ocorrencias', 'lancamentos', 'hh'):
        for r in ler(t):
            if r['status'] != 'confirmado' and (r.get('periodo') == str(n) or (r.get('data') and ini.isoformat() <= r['data'] <= fim.isoformat())):
                pend[t] += 1
    if pend:
        add('DADOS', 'atencao', 'Linhas a conferir: ' + ', '.join(f'{k} {v}' for k, v in pend.items()))
    # dias sem registro de produção
    dias_com = {r['data'] for r in ler('ppu') if ini.isoformat() <= r['data'] <= fim.isoformat()}
    faltam = [d for d in (ini + dt.timedelta(i) for i in range((min(hoje, fim) - ini).days + 1)) if d.isoformat() not in dias_com]
    if faltam:
        add('DADOS', 'atencao', f'{len(faltam)} dia(s) sem produção registrada: ' + ', '.join(f'{d:%d/%m}' for d in faltam[:20]) + (' …' if len(faltam) > 20 else ''))
    # tubos acima do total do trocador
    cad = tags()
    por_tag = defaultdict(float)
    for r in ler('ppu'):
        if ini.isoformat() <= r['data'] <= fim.isoformat() and r['servico'] == 'desobstrucao':
            por_tag[chave_tag(r['tag'])] += num(r['quantidade'])
    for k, v in por_tag.items():
        tot = num((cad.get(k) or {}).get('tubos'))
        if tot and v > tot * 1.0001:
            add('DADOS', 'atencao', f'{cad[k]["tag"]}: {v:.0f} tubos no período, acima do total do trocador ({tot:.0f}); conferir duplicidade ou nova manutenção')
        if k not in cad:
            add('DADOS', 'atencao', f'TAG fora do cadastro: {k}')
    for it in ('10', '20'):
        if it not in med:
            add('VERBAS', 'atencao', f'Item {it} ({q[it]["descricao"]}) sem lançamento no período')
    # R9 saldo
    acc = acumulado_ate(n)
    valor = sum((acc[i] + med.get(i, 0)) * q[i]['preco'] for i in set(acc) | set(med) if i in q)
    add('R9', 'ok', f'Acumulado do contrato até a medição {n}: R$ {valor:,.2f}; saldo R$ {VALOR_CONTRATO - valor:,.2f}')
    for i in set(acc) | set(med):
        if i in q and int(i) < 120 and acc[i] + med.get(i, 0) > q[i]['qtd_contrato']:  # 120+ têm quantidade nominal 1 na QQP
            add('R9', 'erro', f'Item {i}: acumulado {acc[i] + med.get(i, 0):,.1f} acima da quantidade do contrato {q[i]["qtd_contrato"]:,.1f}')
    prazo = fim.replace(day=20)
    if fim < hoje <= prazo:
        add('R10', 'atencao', f'Faltam {(prazo - hoje).days} dia(s) para a entrega da medição {n}')
    return R


def cmd_conferir(a):
    n = a.periodo or periodo_de(dt.date.today())
    for r in conferir(n):
        print(f"[{r['nivel']:7}] {r['regra']:6} {r['mensagem']}")


# ---------------------------------------------------------------- análise por equipe
META_TURNO = {'A41': 200, 'A07': 50, 'A06': 50, 'ISC': 50, 'APG': 8, 'APC': 8}   # tubos por turno (tiposTrocador da apresentação)
PRAZO_DIAS = {'A41': 4, 'A07': 5, 'A06': 5, 'ISC': 8, 'APG': 23}
TIPO_TXT = {'A41': 'Resfriamento a vácuo (6 colmeias)', 'A07': 'Horizontal cáustico', 'A06': 'Horizontal cáustico',
            'APG': 'Aquecedor de polpa'}


def tipo_da_tag(tag):
    r = tags().get(chave_tag(tag)) or {}
    if r.get('tipo'):
        return r['tipo']
    k = chave_tag(tag)
    return 'APG' if re.match(r'HE2[A-D]', k) else 'A41' if k.startswith('HE41') else 'A06'


def producao_dedup(so_confirmado=False):
    """Linhas de desobstrução sem duplicar o mesmo dia, turno e TAG vindo de duas fontes."""
    prio = {'grade-medicao': 0, 'entrada-manual': 1, 'rdo-app-n8n': 1, 'rdo-app': 2, 'whatsapp-livre': 3, 'apresentacao': 4}
    melhor = {}
    for r in ler('ppu'):
        if r['servico'] != 'desobstrucao' or not num(r['quantidade']) or (so_confirmado and r['status'] != 'confirmado'):
            continue
        k = (r['data'], turno_cheio(r['turno']), chave_tag(r['tag']))
        if k not in melhor or prio.get(r['fonte_tipo'], 9) < prio.get(melhor[k][0]['fonte_tipo'], 9):
            melhor[k] = [r]
        elif melhor[k][0]['fonte_tipo'] == r['fonte_tipo']:
            melhor[k].append(r)
    return [dict(r, turno=k[1], quant=num(r['quantidade']), tipo=tipo_da_tag(r['tag'])) for k, rs in melhor.items() for r in rs]


def minutos(ini, fim):
    try:
        a = int(ini[:2]) * 60 + int(ini[3:5]); b = int(fim[:2]) * 60 + int(fim[3:5])
    except (ValueError, TypeError):
        return None
    return (b - a) % 1440


def analise_equipes():
    """Comportamento de cada turno (equipe de desobstrução) desde 28/08, por medição e no total.
    'Por trocador-turno' normaliza o trabalho em paralelo (vários trocadores no mesmo turno).
    A meta por turno da apresentação (200 tubos nos de 6 colmeias) não foi usada: está bem abaixo do realizado."""
    rows = producao_dedup()
    turnos = defaultdict(lambda: defaultdict(lambda: dict(tubos=0.0, metas={})))   # (turno, medição) -> (data, turno) -> acumulado
    for r in rows:
        n = periodo_de(r['data'])
        for ch in ((r['turno'], n), (r['turno'], 0), ('Todos', n), ('Todos', 0)):
            c = turnos[ch][(r['data'], r['turno'])]
            c['tubos'] += r['quant']
            c['metas'][chave_tag(r['tag'])] = 1
    res = {}
    for ch, d in turnos.items():
        tubos = sum(c['tubos'] for c in d.values())
        pares = sum(len(c['metas']) for c in d.values())
        por_dia = defaultdict(float)
        for (dia, _), c in d.items():
            por_dia[dia] += c['tubos']
        res[ch] = dict(turnos=len(d), dias=len({k[0] for k in d}), tubos=tubos, media=tubos / len(d),
                       maximo=max(c['tubos'] for c in d.values()), pares=pares,
                       por_par=tubos / pares)
    return res


def analise_trocadores():
    rows = producao_dedup()
    por = defaultdict(list)
    for r in rows:
        por[chave_tag(r['tag'])].append(r)
    out = []
    for k, rs in por.items():
        datas = sorted({r['data'] for r in rs})
        turnos = {(r['data'], r['turno']) for r in rs}
        tubos = sum(r['quant'] for r in rs)
        tipo = rs[0]['tipo']
        cad = tags().get(k) or {}
        total = num(cad.get('tubos'))
        ini, fim = dt.date.fromisoformat(datas[0]), dt.date.fromisoformat(datas[-1])
        by_t = defaultdict(float)
        for r in rs:
            by_t[r['turno']] += r['quant']
        out.append(dict(tag=rs[0]['tag'], tipo=tipo, grupo=rs[0]['grupo'], inicio=datas[0], fim=datas[-1],
                        dias_corridos=(fim - ini).days + 1, dias_producao=len(datas), turnos=len(turnos), tubos=tubos,
                        total=total, media_turno=tubos / len(turnos), meta_turno=META_TURNO.get(tipo, 50),
                        prazo=PRAZO_DIAS.get(tipo), Dia=by_t['Dia'], Tarde=by_t['Tarde'], Noite=by_t['Noite']))
    return sorted(out, key=lambda x: x['inicio'])


def analise_paradas():
    por = defaultdict(lambda: defaultdict(float))
    sem = 0
    for r in ler('ocorrencias'):
        m = num(r['minutos']) or minutos(r['inicio'], r['fim'])
        if m is None:
            sem += 1
            continue
        por[(r['responsavel'] or 'sem responsável', turno_cheio(r['turno']))]['min'] += m
        por[(r['responsavel'] or 'sem responsável', turno_cheio(r['turno']))]['n'] += 1
    return por, sem


def analise_absenteismo():
    """Por pessoa, a partir da presença nominal. Conta como ausência o que a apresentação marca: falta e atestado."""
    por = defaultdict(lambda: defaultdict(int))
    dias = defaultdict(set)
    nomes = {}
    for r in ler('presenca'):
        k = sem_acento(r['colaborador'])
        nomes[k] = (r['colaborador'], r['equipe'], r['funcao'])
        por[k][r['situacao']] += 1
        por[k]['previsto'] += 1 if r['situacao'] not in ('ferias', 'folga', 'afastado') else 0
        dias[k].add(r['data'])
    out = []
    for k, c in por.items():
        aus = c['falta'] + c['atestado']
        out.append(dict(colaborador=nomes[k][0], equipe=nomes[k][1], funcao=nomes[k][2], registros=sum(v for kk, v in c.items() if kk != 'previsto'),
                        presente=c['presente'] + c['normal'], falta=c['falta'], atestado=c['atestado'], ferias=c['ferias'],
                        folga=c['folga'], previsto=c['previsto'], taxa=(aus / c['previsto']) if c['previsto'] else 0))
    return sorted(out, key=lambda x: (-x['taxa'], x['colaborador'])), (min((d for s in dias.values() for d in s), default=''), max((d for s in dias.values() for d in s), default=''))


def cmd_analise(a):
    print('== Por turno (equipe de desobstrução) e medição')
    res = analise_equipes()
    for ch in sorted(res, key=lambda c: (c[1], ['Dia', 'Tarde', 'Noite', 'Todos'].index(c[0]))):
        r = res[ch]
        print(f"med {ch[1] or 'todas':>5} {ch[0]:6} turnos {r['turnos']:3} dias {r['dias']:3} tubos {r['tubos']:6.0f} média/turno {r['media']:6.1f} máx {r['maximo']:5.0f} por trocador-turno {r['por_par']:.0f}")
    print('== Por trocador')
    for t in analise_trocadores():
        print(f"{t['tag']:12} {t['tipo']:4} {t['inicio']}..{t['fim']} corridos {t['dias_corridos']:3} prod {t['dias_producao']:2} turnos {t['turnos']:3} tubos {t['tubos']:5.0f}/{t['total']:.0f} média {t['media_turno']:6.1f} meta {t['meta_turno']} D/T/N {t['Dia']:.0f}/{t['Tarde']:.0f}/{t['Noite']:.0f}")
    print('== Paradas')
    por, sem = analise_paradas()
    for k, v in sorted(por.items()):
        print(k, v['n'], 'paradas', v['min'], 'min')
    print('sem horário:', sem)
    print('== Absenteísmo nominal')
    ab, (i, f) = analise_absenteismo()
    print(len(ab), 'pessoas; registros de', i, 'a', f)


# ---------------------------------------------------------------- planilha
AZUL, AZUL2, AZUL3 = '#243185', '#2542e6', '#758aff'


def cmd_planilha(a):
    import xlsxwriter
    q = qqp()
    hoje = dt.date.today()
    nmax = max(periodo_de(hoje), 1)
    saida = a.saida or os.path.join(AQUI, 'controle-medicao-trocador-4600014468.xlsx')
    wb = xlsxwriter.Workbook(saida)
    F = lambda **k: wb.add_format({'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', **k})
    tit = F(bold=True, font_size=14, font_color=AZUL)
    sub = F(italic=True, font_color='#555555')
    cab = F(bold=True, font_color='white', bg_color=AZUL, border=1, text_wrap=True, align='center')
    txt = F(border=1, text_wrap=True)
    nro = F(border=1, num_format='#,##0.00')
    nr0 = F(border=1, num_format='#,##0')
    rs = F(border=1, num_format='R$ #,##0.00')
    tot = F(bold=True, border=1, bg_color='#E8EBF7', num_format='R$ #,##0.00')
    totq = F(bold=True, border=1, bg_color='#E8EBF7', num_format='#,##0')
    totl = F(bold=True, border=1, bg_color='#E8EBF7')
    niv = {'ok': F(border=1, bg_color='#DFF2E1'), 'atencao': F(border=1, bg_color='#FFF4CC'), 'erro': F(border=1, bg_color='#F8D7DA')}

    # LEIA-ME
    ws = wb.add_worksheet('LEIA-ME')
    ws.set_column(0, 0, 110)
    linhas = [
        ('Controle de medição — Trocador de Calor 4600014468 (Montisol + Fercama)', tit),
        (f'Gerada em {dt.datetime.now():%d/%m/%Y %H:%M} pelo assets/medicao/medicao.py. Não edite esta planilha: ela é refeita a partir da base (dados/*.csv).', sub),
        ('', None),
        ('Como funciona', F(bold=True, font_color=AZUL2, font_size=11)),
        ('1. Todo dia as mensagens do WhatsApp (RDO de campo e textos dos encarregados) entram na base como "a conferir".', None),
        ('2. Depois da conferência, as linhas viram "confirmado". Lançamento manual: aba ENTRADA, reimportada pelo script.', None),
        ('3. A planilha, os BMMs por período (16 a 15), a conferência das regras e a apresentação do Trocador saem da mesma base.', None),
        ('4. Mão de obra (verbas, HH e MO por unidade) é da Montisol; equipamento (itens 40, 50, 70, 110 e HM 570 a 600) é da Fercama.', None),
        ('', None),
        ('Abas', F(bold=True, font_color=AZUL2, font_size=11)),
        ('PAINEL: totais por medição e por faturador, GMM e saldo do contrato.', None),
        ('BMM_Pn: boletim da medição n no formato da Hydro (acumulado anterior, medido, acumulado, saldo), com o faturador de cada linha.', None),
        ('DIARIO_PPU: tubos e aberturas por dia, turno e TAG, com a fonte (grade, app, texto livre, apresentação).', None),
        ('PRESENCA, HH, OCORRENCIAS, LANCAMENTOS: demais registros da base. CONFERENCIA: regras R1 a R10. FONTES: mensagens lidas.', None),
        ('EQUIPES, TROCADORES, PARADAS, ABSENTEISMO: comportamento de cada turno e de cada trocador desde 28/08 e absenteísmo nominal (só onde há apontamento nominal real).', None),
        ('ENTRADA: modelo para lançamento manual (tabela ppu ou hh).', None),
        ('', None),
        ('Pontos em aberto (não decididos pela planilha)', F(bold=True, font_color=AZUL2, font_size=11)),
        ('• Mão de obra acima de 4.000 tubos/mês (item 30): a planilha segue a prática do BMM 2 (mede todos) e mostra o valor em discussão.', None),
        ('• Quem fatura o HM eventual (munck e hidrojato, itens 580 e 600). • Jornada por turno para gerar HH a partir da presença.', None),
        ('• Medição 1 (28/08 a 15/09): produção vem da apresentação; verbas e HH ainda sem fonte. Medição 3: dias sem registro desde 16/10.', None),
    ]
    for i, (t, f) in enumerate(linhas):
        ws.write(i, 0, t, f)

    # PAINEL
    wp = wb.add_worksheet('PAINEL')
    wp.set_column(0, 0, 12); wp.set_column(1, 2, 22); wp.set_column(3, 9, 16)
    wp.write(0, 0, 'Painel da medição — Trocador de Calor 4600014468', tit)
    wp.write(1, 0, f'Valor do contrato R$ {VALOR_CONTRATO:,.2f} · 60 meses desde 28/08/2026 · GMM 4.000 tubos/mês (precipitação) e 120 (aquecedores)', sub)
    hdr = ['Medição', 'Início', 'Fim', 'Montisol (R$)', 'Fercama (R$)', 'Total (R$)', 'Tubos precipitação', 'Tubos aquecedores', 'Aberturas aquecedor', 'Acumulado (R$)']
    for j, h in enumerate(hdr):
        wp.write(3, j, h, cab)
    acc_val = 0
    for n in range(1, nmax + 1):
        med, tub = medir(n)
        ini, fim = limites(n)
        mont = sum(v * q[i]['preco'] for i, v in med.items() if q[i]['faturador'] == 'Montisol')
        ferc = sum(v * q[i]['preco'] for i, v in med.items() if q[i]['faturador'] == 'Fercama')
        acc_val += mont + ferc
        r = 3 + n
        wp.write(r, 0, n, nr0); wp.write(r, 1, ini.strftime('%d/%m/%Y'), txt); wp.write(r, 2, fim.strftime('%d/%m/%Y'), txt)
        wp.write(r, 3, mont, rs); wp.write(r, 4, ferc, rs); wp.write_formula(r, 5, f'=D{r + 1}+E{r + 1}', rs, mont + ferc)
        wp.write(r, 6, tub[('precipitacao', 'desobstrucao')], nr0); wp.write(r, 7, tub[('aquecedor', 'desobstrucao')], nr0)
        wp.write(r, 8, tub[('aquecedor', 'abertura')], nro); wp.write(r, 9, acc_val, rs)
    r = 4 + nmax
    wp.write(r, 0, 'Total', totl)
    for j, col in ((3, 'D'), (4, 'E'), (5, 'F')):
        wp.write_formula(r, j, f'=SUM({col}5:{col}{r})', tot)
    wp.write(r + 2, 0, 'Saldo do contrato (R$)', totl); wp.write_formula(r + 2, 3, f'={VALOR_CONTRATO}-F{r + 1}', tot, VALOR_CONTRATO - acc_val)
    ch = wb.add_chart({'type': 'column', 'subtype': 'stacked'})
    for j, cor in ((3, AZUL), (4, AZUL3)):
        ch.add_series({'name': ['PAINEL', 3, j], 'categories': ['PAINEL', 4, 0, 3 + nmax, 0],
                       'values': ['PAINEL', 4, j, 3 + nmax, j], 'fill': {'color': cor}})
    ch.set_title({'name': 'Medição por período (R$)', 'name_font': {'size': 10}})
    ch.set_legend({'position': 'bottom'}); ch.set_size({'width': 640, 'height': 300})
    wp.insert_chart(r + 4, 0, ch)

    # BMMs
    for n in range(1, nmax + 1):
        bmm_aba(wb, n, q, F, tit, sub, cab, txt, nro, rs, tot, totl)

    # DIARIO_PPU, PRESENCA, HH, OCORRENCIAS, LANCAMENTOS, FONTES
    def aba(nome, tabela, larg=None):
        w = wb.add_worksheet(nome)
        cols = TABELAS[tabela] + (['periodo'] if 'data' in TABELAS[tabela] else [])
        for j, c in enumerate(cols):
            w.write(0, j, c, cab)
            w.set_column(j, j, (larg or {}).get(c, 14))
        for i, r in enumerate(ler(tabela), start=1):
            for j, c in enumerate(cols):
                v = periodo_de(r['data']) if c == 'periodo' and r.get('data') else r.get(c, '')
                if c in ('quantidade', 'hn', 'he65', 'he100', 'adn', 'minutos', 'retrabalho') and v != '':
                    w.write_number(i, j, num(v), nro)
                else:
                    w.write(i, j, v if v is not None else '', txt)
        w.freeze_panes(1, 0)
        w.autofilter(0, 0, max(len(ler(tabela)), 1), len(cols) - 1)
    aba('DIARIO_PPU', 'ppu', {'obs': 40, 'fonte_ref': 30, 'id': 11})
    aba('PRESENCA', 'presenca', {'colaborador': 30, 'justificativa': 30, 'fonte_ref': 30})
    aba('HH', 'hh', {'colaborador': 30})
    aba('OCORRENCIAS', 'ocorrencias', {'motivo': 45})
    aba('LANCAMENTOS', 'lancamentos', {'obs': 45, 'fonte_ref': 40})

    # ANALISE: equipes (turnos), trocadores, paradas e absenteísmo nominal
    we_ = wb.add_worksheet('EQUIPES')
    we_.set_column(0, 0, 10); we_.set_column(1, 9, 15)
    we_.write(0, 0, 'Comportamento de cada turno desde 28/08 (desobstrução)', tit)
    we_.write(1, 0, 'Turnos: Dia = Turno I (07:30 a 17:24) e ADM; Tarde = Turno II (15:30 a 00:50); Noite = Turno III (23:00 a 07:30). "Por trocador-turno" divide os tubos pelos trocadores trabalhados no mesmo turno.', sub)
    for j, h in enumerate(['Medição', 'Turno', 'Turnos com produção', 'Dias', 'Tubos', 'Média por turno', 'Máximo em um turno', 'Trocadores-turno', 'Tubos por trocador-turno']):
        we_.write(3, j, h, cab)
    res = analise_equipes()
    r = 4
    for ch in sorted(res, key=lambda c: (c[1] == 0, c[1], ['Dia', 'Tarde', 'Noite', 'Todos'].index(c[0]))):
        v = res[ch]
        vals = ['todas' if ch[1] == 0 else ch[1], ch[0], v['turnos'], v['dias'], v['tubos'], v['media'], v['maximo'], v['pares'], v['por_par']]
        for j, x in enumerate(vals):
            we_.write(r, j, x, txt if j < 2 else nr0 if j in (2, 3, 4, 6, 7) else nro)
        r += 1
    wt = wb.add_worksheet('TROCADORES')
    wt.set_column(0, 0, 14); wt.set_column(1, 16, 12)
    wt.write(0, 0, 'Desempenho por trocador desde 28/08', tit)
    cols = [('TAG', 'tag'), ('Tipo', 'tipo'), ('Início', 'inicio'), ('Fim', 'fim'), ('Dias corridos', 'dias_corridos'), ('Dias com produção', 'dias_producao'),
            ('Turnos', 'turnos'), ('Tubos', 'tubos'), ('Total do trocador', 'total'), ('Média por turno', 'media_turno'), ('Prazo (dias)', 'prazo'),
            ('Tubos Dia', 'Dia'), ('Tubos Tarde', 'Tarde'), ('Tubos Noite', 'Noite')]
    for j, (h, _) in enumerate(cols):
        wt.write(2, j, h, cab)
    for i, t in enumerate(analise_trocadores(), start=3):
        for j, (_, k) in enumerate(cols):
            v = t[k]
            wt.write(i, j, v if v is not None else '', nro if isinstance(v, float) else txt)
    wt.freeze_panes(3, 1)
    wp_ = wb.add_worksheet('PARADAS')
    wp_.set_column(0, 3, 16)
    wp_.write(0, 0, 'Paradas por responsável e turno', tit)
    for j, h in enumerate(['Responsável', 'Turno', 'Paradas', 'Minutos']):
        wp_.write(2, j, h, cab)
    por, sem_h = analise_paradas()
    for i, (k, v) in enumerate(sorted(por.items()), start=3):
        wp_.write(i, 0, k[0], txt); wp_.write(i, 1, k[1], txt); wp_.write(i, 2, v['n'], nr0); wp_.write(i, 3, v['min'], nr0)
    wp_.write(4 + len(por), 0, f'{sem_h} parada(s) sem horário não entram.', sub)
    wa_ = wb.add_worksheet('ABSENTEISMO')
    wa_.set_column(0, 0, 32); wa_.set_column(1, 2, 20); wa_.set_column(3, 10, 11)
    ab, (d0, d1) = analise_absenteismo()
    wa_.write(0, 0, 'Absenteísmo nominal por pessoa', tit)
    wa_.write(1, 0, f'Cobertura da base nominal: {d0 or "nenhum dia"} a {d1 or "-"}. Ausência que conta = falta e atestado (critério da apresentação); férias e folga saem do previsto. Os dados de exemplo da apresentação (ids apSEED) foram excluídos.', sub)
    for j, h in enumerate(['Colaborador', 'Equipe', 'Função', 'Registros', 'Presente', 'Falta', 'Atestado', 'Férias', 'Folga', 'Previsto', 'Taxa']):
        wa_.write(3, j, h, cab)
    pct = F(border=1, num_format='0.0%')
    for i, x in enumerate(ab, start=4):
        for j, k in enumerate(['colaborador', 'equipe', 'funcao', 'registros', 'presente', 'falta', 'atestado', 'ferias', 'folga', 'previsto']):
            wa_.write(i, j, x[k], txt if j < 3 else nr0)
        wa_.write(i, 10, x['taxa'], pct)
    wa_.freeze_panes(4, 1)
    # CONFERENCIA
    wc = wb.add_worksheet('CONFERENCIA')
    wc.set_column(0, 1, 10); wc.set_column(2, 2, 10); wc.set_column(3, 3, 120)
    for j, h in enumerate(['Medição', 'Regra', 'Nível', 'Mensagem']):
        wc.write(0, j, h, cab)
    i = 1
    for n in range(1, nmax + 1):
        for r in conferir(n, hoje):
            f = niv[r['nivel']]
            wc.write(i, 0, n, f); wc.write(i, 1, r['regra'], f); wc.write(i, 2, r['nivel'], f); wc.write(i, 3, r['mensagem'], f)
            i += 1

    aba('FONTES', 'fontes', {'texto': 80, 'grupo': 30})

    # QQP
    wq = wb.add_worksheet('QQP')
    hq = ['item', 'descricao', 'unidade', 'quantidade', 'preco_unitario', 'faturador']
    wq.set_column(1, 1, 80); wq.set_column(0, 0, 8); wq.set_column(2, 5, 14)
    for j, h in enumerate(hq):
        wq.write(0, j, h, cab)
    for i, (it, r) in enumerate(sorted(q.items(), key=lambda x: int(x[0])), start=1):
        wq.write(i, 0, int(it), nr0); wq.write(i, 1, r['descricao'], txt); wq.write(i, 2, r['unidade'], txt)
        wq.write(i, 3, r['qtd_contrato'], nro); wq.write(i, 4, r['preco'], rs); wq.write(i, 5, r['faturador'], txt)

    # ENTRADA
    we = wb.add_worksheet('ENTRADA')
    we.write(0, 0, 'Lançamento manual — preencha a partir da linha 4 e rode: medicao.py importar-entrada <esta planilha>', tit)
    we.write(1, 0, 'tabela = ppu (tubos/aberturas por TAG) ou hh (horas das equipes extras). servico = desobstrucao ou abertura.', sub)
    he = ['tabela', 'data', 'turno', 'tag', 'servico', 'quantidade', 'equipe', 'pessoa', 'funcao', 'hn', 'he65', 'he100', 'adn', 'os', 'obs']
    for j, h in enumerate(he):
        we.write(2, j, h, cab)
        we.set_column(j, j, 14)
    we.data_validation(3, 0, 500, 0, {'validate': 'list', 'source': ['ppu', 'hh']})
    we.data_validation(3, 4, 500, 4, {'validate': 'list', 'source': ['desobstrucao', 'abertura']})
    we.data_validation(3, 6, 500, 6, {'validate': 'list', 'source': ['descontaminacao', 'area31', 'desobstrucao', 'lavagem-acida']})
    we.data_validation(3, 1, 500, 1, {'validate': 'date', 'criteria': '>=', 'value': dt.datetime(2026, 8, 28)})
    wb.close()
    print(saida)


def bmm_aba(wb, n, q, F, tit, sub, cab, txt, nro, rs, tot, totl):
    ini, fim = limites(n)
    med, _ = medir(n)
    acc = acumulado_ate(n)
    ws = wb.add_worksheet(f'BMM_P{n}')
    ws.set_column(0, 0, 7); ws.set_column(1, 1, 62); ws.set_column(2, 2, 8); ws.set_column(3, 12, 14); ws.set_column(13, 13, 11)
    ws.write(0, 0, 'Boletim de Medição — Hydro Alunorte', tit)
    ws.write(1, 0, f'Contrato 4600014468 · Montisol Construção e Manutenção Ltda / Fercama · Manutenção dos trocadores de calor', sub)
    ws.write(2, 0, f'Medição nº {n} · Período {ini:%d/%m/%Y} a {fim:%d/%m/%Y} · Entrega até {fim.replace(day=20):%d/%m/%Y} · Conta contábil 626140', sub)
    h = ['Item', 'Descrição', 'Unid.', 'Qtd contrato', 'Preço unit.', 'Valor contrato', 'Acum. anterior (qtd)',
         'Acum. anterior (R$)', 'Medido (qtd)', 'Medido (R$)', 'Acumulado (qtd)', 'Acumulado (R$)', 'Saldo (qtd)', 'Faturador']
    for j, x in enumerate(h):
        ws.write(4, j, x, cab)
    ws.set_row(4, 30)
    r = 5
    for it, d in sorted(q.items(), key=lambda x: int(x[0])):
        ant, m = acc.get(it, 0), med.get(it, 0)
        R = r + 1
        ws.write(r, 0, int(it), txt); ws.write(r, 1, d['descricao'], txt); ws.write(r, 2, d['unidade'], txt)
        ws.write(r, 3, d['qtd_contrato'], nro); ws.write(r, 4, d['preco'], rs)
        ws.write_formula(r, 5, f'=D{R}*E{R}', rs, d['qtd_contrato'] * d['preco'])
        ws.write(r, 6, ant, nro); ws.write_formula(r, 7, f'=G{R}*E{R}', rs, ant * d['preco'])
        ws.write(r, 8, m, nro); ws.write_formula(r, 9, f'=I{R}*E{R}', rs, m * d['preco'])
        ws.write_formula(r, 10, f'=G{R}+I{R}', nro, ant + m); ws.write_formula(r, 11, f'=K{R}*E{R}', rs, (ant + m) * d['preco'])
        ws.write_formula(r, 12, f'=D{R}-K{R}', nro, d['qtd_contrato'] - ant - m); ws.write(r, 13, d['faturador'], txt)
        r += 1
    last = r
    ws.write(r, 1, 'TOTAL', totl)
    for j, c in ((5, 'F'), (7, 'H'), (9, 'J'), (11, 'L')):
        ws.write_formula(r, j, f'=SUM({c}6:{c}{last})', tot)
    for k, fat in enumerate(('Montisol', 'Fercama')):
        rr = r + 1 + k
        ws.write(rr, 1, f'Medido no período — {fat}', totl)
        ws.write_formula(rr, 9, f'=SUMIF(N6:N{last},"{fat}",J6:J{last})', tot)
    ws.freeze_panes(5, 2)
    ws.autofilter(4, 0, last - 1, 13)


# ---------------------------------------------------------------- apresentação
TURNO_APRES = {'T': 'T1', 'D': 'T1', 'A': 'T1', 'TURNO I': 'T1', 'TA': 'T2', 'TURNO II': 'T2', 'N': 'T3', 'TURNO III': 'T3'}


def turno_apres(t):
    s = sem_acento(t)
    if s.startswith('TURNO III') or s.startswith('NOITE') or s.startswith('23'): return 'T3'
    if s.startswith('TURNO II') or s.startswith('TARDE') or s.startswith('15'): return 'T2'
    return 'T1'


def cmd_apresentacao(a):
    p = os.path.join(a.pasta, 'data.json')
    d = json.load(open(p, encoding='utf-8'))
    por_tag = {chave_tag(t['tag']): t['id'] for t in d['trocadores']}
    ja = {(x['data'], x['turno'], x['trocador']) for x in d['producao']}
    novos, sem_tag = [], set()
    for r in ler('ppu'):
        if r['fonte_tipo'] == 'apresentacao' or r['servico'] != 'desobstrucao' or r['status'] != 'confirmado':
            continue
        tid = por_tag.get(chave_tag(r['tag']))
        if not tid:
            sem_tag.add(r['tag'])
            continue
        k = (r['data'], turno_apres(r['turno']), tid)
        if k in ja:
            continue
        ja.add(k)
        novos.append(dict(id='pmed' + r['id'], data=r['data'], turno=k[1], trocador=tid, tubos=num(r['quantidade']),
                          retrabalho=num(r['retrabalho']), encarregado=r['encarregado'], equipamento='emuh816aj0',
                          inicio='', fim='', obs=f"base de medição ({r['fonte_tipo']})"))
    print(f'{len(novos)} registro(s) de produção novos para a apresentação; TAGs sem cadastro na apresentação: {sorted(sem_tag) or "nenhuma"}')
    if a.aplicar and novos:
        d['producao'] += novos
        json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('data.json atualizado; salve a apresentação (apresentacao_salvar).')


# ---------------------------------------------------------------- backup e migração
def cmd_backup(a):
    pasta = os.path.join(BACKUP, dt.date.today().isoformat())
    os.makedirs(pasta, exist_ok=True)
    tot = {}
    for t, cols in TABELAS.items():
        linhas = ler(t)
        k = CHAVE.get(t, 'id')
        with open(os.path.join(pasta, t + '.csv'), 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            w.writerows(sorted(linhas, key=lambda r: (r.get('data') or r.get('periodo') or '', r.get(k, ''))))
        tot[t] = len(linhas)
    limite = dt.date.today() - dt.timedelta(days=a.manter)
    for d in os.listdir(BACKUP):
        try:
            if dt.date.fromisoformat(d) < limite:
                shutil.rmtree(os.path.join(BACKUP, d))
        except ValueError:
            pass
    print(pasta, json.dumps(tot, ensure_ascii=False))


def cmd_migrar_csv(a):
    pasta = a.pasta or DADOS
    for t in TABELAS:
        p = os.path.join(pasta, t + '.csv')
        if os.path.exists(p):
            with open(p, encoding='utf-8', newline='') as f:
                print(t, acrescentar(t, list(csv.DictReader(f))))


# ---------------------------------------------------------------- envios do app RDO (n8n, com aprovação)
def n8n(metodo, caminho_, corpo=None):
    chave = os.environ.get('N8N_API_KEY')
    if not chave:
        sys.exit('N8N_API_KEY não definida')
    req = urllib.request.Request(N8N_URL.rstrip('/') + '/api/v1' + caminho_, method=metodo,
                                 data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={'X-N8N-API-KEY': chave, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


def linhas_do_envio(p):
    """Converte um envio aprovado do app (contrato versão 1) em linhas da base, já confirmadas."""
    l, h = p['lancamento'], 'n8n:' + p['id']
    data, turno = l.get('data', ''), l.get('turno', '')
    base = dict(fonte_tipo='rdo-app-n8n', fonte_ref=h, status='confirmado')
    equipe = equipe_de_frente(l['frente']) if l.get('frente') else ('desobstrucao' if l.get('modalidade') == 'ppu' else '')
    ppu, oc, pres, hh = [], [], [], []
    for eq in l.get('equipamentos') or []:
        tag = (tags().get(chave_tag(eq.get('tag', ''))) or {}).get('tag', eq.get('tag', ''))
        q = num((eq.get('prod') or {}).get('desob'))
        if q and (eq.get('servico') or 'desobstrucao') == 'desobstrucao':
            at = eq.get('ativ') or {}
            ppu.append(dict(base, id=hid(h, tag, 'desob'), data=data, turno=turno, tag=tag, grupo=grupo_da_tag(tag),
                            servico='desobstrucao', quantidade=q, retrabalho=0, encarregado=l.get('encarregado', ''),
                            equipe='desobstrucao', obs='; '.join(x for x in (at.get('situacao'), at.get('pend')) if x)))
        for i, pa in enumerate(eq.get('paradas') or []):
            oc.append(dict(base, id=hid(h, tag, 'par', i), data=data, turno=turno, tag=tag, responsavel=pa.get('resp', ''),
                           motivo=pa.get('motivo', ''), inicio=pa.get('ini', ''), fim=pa.get('fim', ''),
                           minutos=minutos(pa.get('ini', ''), pa.get('fim', '')) or '', impacto=pa.get('impacto', '')))
    for pe in l.get('pessoas') or []:
        nome = pe.get('nome', '').strip()
        if not nome:
            continue
        sit = {'afastado': 'ferias'}.get(pe.get('status'), pe.get('status') or '')
        pres.append(dict(base, id=hid(data, norm_turno(turno), sem_acento(nome)), data=data, turno=turno, equipe=equipe,
                         colaborador=nome, funcao=pe.get('funcao', ''), situacao=sit, justificativa=pe.get('just', ''),
                         tag=pe.get('deveria', ''), encarregado=l.get('encarregado', '')))
        horas = {k: pe.get(k) for k in TIPO_HORA if pe.get(k) not in (None, '')}
        if horas:
            hh.append(dict(base, id=hid(h, nome, 'hh'), data=data, turno=turno, equipe=equipe, colaborador=nome,
                           funcao=pe.get('funcao', ''), os='; '.join(l.get('os_executadas') or []),
                           obs='horas informadas no app', **{k: horas.get(k, 0) for k in TIPO_HORA}))
    return ppu, oc, pres, hh


def cmd_sincronizar_n8n(a):
    linhas, cursor = [], None
    while True:
        r = n8n('GET', f'/data-tables/{N8N_TABELA}/rows?limit=250' + (f'&cursor={cursor}' if cursor else ''))
        linhas += r.get('data', [])
        cursor = r.get('nextCursor')
        if not cursor:
            break
    contagem = defaultdict(int)
    for x in linhas:
        contagem[x.get('status') or 'sem status'] += 1
    aprovados = [x for x in linhas if (x.get('status') or '').strip().lower() == 'aprovado']
    print('no n8n:', dict(contagem))
    agora = dt.datetime.now().isoformat(timespec='minutes')
    for x in aprovados:
        try:
            p = json.loads(x['payload'])
        except (TypeError, ValueError):
            print('payload inválido:', x.get('envio_id'))
            continue
        ppu, oc, pres, hh = linhas_do_envio(p)
        if a.simular:
            print(f"{p['id']}: {len(ppu)} produção, {len(oc)} paradas, {len(pres)} presença, {len(hh)} HH (simulado)")
            continue
        n = acrescentar('ppu', ppu) + acrescentar('ocorrencias', oc) + acrescentar('presenca', pres) + acrescentar('hh', hh)
        l = p['lancamento']
        acrescentar('recebidos', [dict(id=p['id'], recebido_em=x.get('recebido_em', ''), data=l.get('data', ''),
                                       turno=l.get('turno', ''), modalidade=l.get('modalidade', ''),
                                       encarregado=l.get('encarregado', ''), aprovado_em=x.get('updatedAt', ''),
                                       registrado_em=agora, obs_lucas=x.get('obs_lucas', ''), linhas=n, payload=x['payload'])])
        acrescentar('fontes', [dict(hash='n8n:' + p['id'], recebido=x.get('recebido_em', ''), data=l.get('data', ''),
                                    grupo='app RDO (n8n)', remetente=l.get('encarregado', ''), formato='rdo-app-n8n',
                                    linhas=n, status='confirmado', texto=(p.get('texto_whatsapp') or '')[:4000])])
        n8n('PATCH', f'/data-tables/{N8N_TABELA}/rows/update',
            {'filter': {'type': 'and', 'filters': [{'columnName': 'envio_id', 'condition': 'eq', 'value': p['id']}]},
             'data': {'status': 'registrado', 'registrado_em': agora}})
        print(f"{p['id']}: {n} linha(s) registradas")
    if not aprovados:
        print('nenhum envio aprovado para registrar')


# ---------------------------------------------------------------- linha de comando
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = ap.add_subparsers(dest='cmd', required=True)
    x = s.add_parser('whatsapp'); x.add_argument('arquivo'); x.add_argument('--grupo', default='')
    x = s.add_parser('importar-grade'); x.add_argument('arquivo')
    x = s.add_parser('importar-apresentacao'); x.add_argument('arquivo'); x.add_argument('--ate')
    x = s.add_parser('importar-bmm'); x.add_argument('arquivo'); x.add_argument('--periodo', type=int, required=True); x.add_argument('--itens')
    x = s.add_parser('importar-entrada'); x.add_argument('arquivo')
    x = s.add_parser('confirmar'); x.add_argument('ids', nargs='*'); x.add_argument('--fonte')
    x = s.add_parser('planilha'); x.add_argument('--saida')
    x = s.add_parser('conferir'); x.add_argument('--periodo', type=int)
    x = s.add_parser('analise')
    x = s.add_parser('backup'); x.add_argument('--manter', type=int, default=60)
    x = s.add_parser('migrar-csv'); x.add_argument('pasta', nargs='?')
    x = s.add_parser('sincronizar-n8n'); x.add_argument('--simular', action='store_true')
    x = s.add_parser('apresentacao'); x.add_argument('pasta'); x.add_argument('--aplicar', action='store_true')
    a = ap.parse_args()
    {'whatsapp': cmd_whatsapp, 'importar-grade': cmd_importar_grade, 'importar-apresentacao': cmd_importar_apresentacao,
     'importar-bmm': cmd_importar_bmm, 'importar-entrada': cmd_importar_entrada, 'confirmar': cmd_confirmar,
     'planilha': cmd_planilha, 'conferir': cmd_conferir, 'analise': cmd_analise, 'backup': cmd_backup, 'migrar-csv': cmd_migrar_csv, 'sincronizar-n8n': cmd_sincronizar_n8n, 'apresentacao': cmd_apresentacao}[a.cmd](a)


if __name__ == '__main__':
    main()
