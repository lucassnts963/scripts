#!/usr/bin/env python3
# Avisos de retorno de férias da equipe do Trocador (Montisol); só lê a tabela do vault.
# precisa: nada
"""Avisos de retorno de férias da equipe do Trocador de Calor (Montisol).

Lê a tabela de `projects/montisol/wiki/_estado/ferias.md` (única fonte das datas; não grava nada) e avisa:
  - quando falta MENOS de 5 dias para o retorno do colaborador;
  - no DIA do retorno;
  - sempre que o retorno cair em SÁBADO ou DOMINGO: o colaborador não pode voltar em fim de semana.
O "Último dia" da tabela é o último dia de férias; o retorno é o dia seguinte.
Só biblioteca padrão do Python 3. Sem nenhum aviso, não imprime nada (bom para agendamento); use --sempre para ver o status.

Uso:
  ferias.py                      avisos de hoje (padrão = verificar)
  ferias.py verificar --hoje 2026-11-05 --dias 5
  ferias.py listar               todos: período, retorno, dias que faltam
  ferias.py verificar --formato json

Opções: --arquivo CAMINHO de um ferias.md (padrão: variável FERIAS_MD, depois o vault), --hoje AAAA-MM-DD, --dias N (padrão 5),
        --sempre (imprime também quando não há aviso), --formato texto|json
"""
import argparse
import datetime as dt
import json
import os
import sys

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
SUB = os.path.join("projects", "montisol", "wiki", "_estado", "ferias.md")


def achar_md(arg):
    # o código fica no repositório de scripts; a tabela, no vault. Só um arquivo ferias.md é lido.
    if arg and os.path.basename(os.path.realpath(arg)) != "ferias.md":
        sys.exit("--arquivo aceita só um arquivo ferias.md")
    cand = [arg, os.environ.get("FERIAS_MD"),
            os.path.join(os.environ.get("BEACONOS_VAULT", ""), SUB) if os.environ.get("BEACONOS_VAULT") else None,
            os.path.join("/vault", SUB)]
    cand = [c for c in cand if c]
    for c in cand:
        if os.path.isfile(c):
            return c
    sys.exit("Tabela de férias não encontrada. Tentei:\n  " + "\n  ".join(cand))


def data(txt):
    return dt.datetime.strptime(txt.strip(), "%d/%m/%Y").date()


def fmt(d):
    return d.strftime("%d/%m")


def nome_dia(d):
    return DIAS[d.weekday()]


def pascoa(ano):
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(ano, mes, dia)


def feriados(ano):
    """Feriados nacionais (só informativo; municipais, como os de Barcarena, não entram)."""
    fixos = {(1, 1): "Confraternização Universal", (4, 21): "Tiradentes", (5, 1): "Dia do Trabalho",
             (9, 7): "Independência", (10, 12): "Nossa Senhora Aparecida", (11, 2): "Finados",
             (11, 15): "Proclamação da República", (11, 20): "Consciência Negra", (12, 25): "Natal"}
    out = {dt.date(ano, m, d): n for (m, d), n in fixos.items()}
    out[pascoa(ano) - dt.timedelta(days=2)] = "Sexta-feira Santa"
    return out


def primeiro_dia_util(d):
    fer = feriados(d.year)
    while d.weekday() >= 5 or d in fer:
        d += dt.timedelta(days=1)
        fer = feriados(d.year)
    return d


def ler(caminho):
    linhas = [l.strip() for l in open(caminho, encoding="utf-8") if l.strip().startswith("|")]
    cab = None
    regs = []
    for l in linhas:
        cel = [c.strip() for c in l.strip("|").split("|")]
        if cab is None:
            if any(c.lower() == "colaborador" for c in cel):
                cab = [c.lower() for c in cel]
            continue
        if set("".join(cel)) <= set("-: "):
            continue
        r = dict(zip(cab, cel))
        try:
            regs.append({
                "nome": r["colaborador"], "funcao": r.get("função", ""), "equipe": r.get("equipe", ""),
                "inicio": data(r["início"]), "ultimo_dia": data(r["último dia"]),
                "confirmado": r.get("fim confirmado", "sim").lower().startswith("s"), "obs": r.get("obs", ""),
            })
        except (KeyError, ValueError) as e:
            sys.exit(f"Linha da tabela com data inválida ou coluna faltando ({e}): {l}")
    if cab is None:
        sys.exit("Tabela com a coluna 'Colaborador' não encontrada em " + caminho)
    for r in regs:
        r["retorno"] = r["ultimo_dia"] + dt.timedelta(days=1)
    return regs


def avaliar(regs, hoje, limite):
    saida = []
    for r in regs:
        dias = (r["retorno"] - hoje).days
        fim_semana = r["retorno"].weekday() >= 5
        a = {"nome": r["nome"], "funcao": r["funcao"], "equipe": r["equipe"], "retorno": r["retorno"].isoformat(),
             "dia_semana": nome_dia(r["retorno"]), "dias_para_retorno": dias, "retorno_em_fim_de_semana": fim_semana,
             "fim_confirmado": r["confirmado"], "avisos": []}
        if r["ultimo_dia"] < r["inicio"]:
            a["avisos"].append("DATA INVÁLIDA: o último dia é anterior ao início; corrigir a tabela.")
        elif dias == 0:
            a["avisos"].append(f"VOLTA HOJE ({nome_dia(r['retorno'])}, {fmt(r['retorno'])}).")
        elif 0 < dias < limite:
            a["avisos"].append(f"Falta{'m' if dias > 1 else ''} {dias} dia{'s' if dias > 1 else ''} para o retorno "
                               f"({nome_dia(r['retorno'])}, {fmt(r['retorno'])}).")
        if a["avisos"] and fim_semana and dias >= 0:
            util = primeiro_dia_util(r["retorno"])
            fer = feriados(r["retorno"].year)
            seg = r["retorno"] + dt.timedelta(days=(7 - r["retorno"].weekday()))
            extra = ""
            if seg in fer:
                extra = f" (segunda {fmt(seg)} é feriado nacional: {fer[seg]})"
            a["avisos"].append(f"ATENÇÃO: o retorno cai em {nome_dia(r['retorno']).upper()} ({fmt(r['retorno'])}). "
                               f"O colaborador NÃO pode voltar em sábado nem domingo: reprogramar o retorno. "
                               f"Primeiro dia útil: {nome_dia(util)}, {fmt(util)}{extra}.")
        if a["avisos"] and not r["confirmado"]:
            a["avisos"].append("A data final ainda não foi confirmada na tabela; confirmar com o Lucas/RH.")
        saida.append(a)
    return saida


def main():
    pai = argparse.ArgumentParser(add_help=False)
    pai.add_argument("--arquivo")
    pai.add_argument("--hoje")
    pai.add_argument("--dias", type=int, default=5)
    pai.add_argument("--sempre", action="store_true")
    pai.add_argument("--formato", choices=["texto", "json"], default="texto")
    ap = argparse.ArgumentParser(description="Avisos de retorno de férias (somente leitura)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("verificar", parents=[pai])
    sub.add_parser("listar", parents=[pai])
    a = ap.parse_args(sys.argv[1:] if sys.argv[1:] and sys.argv[1] in ("verificar", "listar") else ["verificar"] + sys.argv[1:])
    hoje = dt.date.fromisoformat(a.hoje) if a.hoje else dt.date.today()
    regs = ler(achar_md(a.arquivo))
    res = avaliar(regs, hoje, a.dias)

    if a.cmd == "listar":
        if a.formato == "json":
            print(json.dumps(res, ensure_ascii=False, indent=2)); return
        print(f"Férias em {hoje.strftime('%d/%m/%Y')} ({nome_dia(hoje)}):")
        for r, x in sorted(zip(regs, res), key=lambda t: t[0]["retorno"]):
            marca = " [fim a confirmar]" if not r["confirmado"] else ""
            fds = " [RETORNO EM FIM DE SEMANA]" if x["retorno_em_fim_de_semana"] else ""
            d = x["dias_para_retorno"]
            quando = "já voltou" if d < 0 else ("volta hoje" if d == 0 else f"faltam {d} dias")
            print(f"- {r['nome']} ({r['funcao']}, {r['equipe']}): {r['inicio']:%d/%m} a {r['ultimo_dia']:%d/%m}; "
                  f"retorno {nome_dia(r['retorno'])} {r['retorno']:%d/%m/%Y}, {quando}{marca}{fds}")
        return

    com = [x for x in res if x["avisos"]]
    if a.formato == "json":
        print(json.dumps(com if com or not a.sempre else res, ensure_ascii=False, indent=2)); return
    if not com:
        if a.sempre:
            em = sum(1 for x in res if x["dias_para_retorno"] >= 0)
            print(f"Sem avisos de férias em {hoje.strftime('%d/%m/%Y')} ({em} colaborador(es) ainda de férias).")
        return
    print(f"Férias: avisos de {hoje.strftime('%d/%m/%Y')} ({nome_dia(hoje)})")
    for x in sorted(com, key=lambda x: x["dias_para_retorno"]):
        print(f"\n{x['nome']} ({x['funcao']}, {x['equipe']})")
        for av in x["avisos"]:
            print(f"  - {av}")


if __name__ == "__main__":
    main()
