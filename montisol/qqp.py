#!/usr/bin/env python3
# Consulta a QQP do contrato Trocador de Calor (Montisol); só lê o CSV do vault.
# precisa: nada
"""Consulta a QQP (Quadro de Quantidades e Preços, Anexo B) do contrato Trocador de Calor 4600014468.

Somente leitura: abre o CSV, filtra e imprime. Não grava arquivo nenhum e não calcula medição.
Só biblioteca padrão do Python 3.

Uso:
  qqp.py resumo                      totais por categoria e total geral
  qqp.py categorias                  categorias e grupos que existem
  qqp.py item 250 260                itens pelo número da QQP
  qqp.py buscar "mecânico montador"  procura no texto da descrição, função e categoria (sem acento, sem maiúscula)
  qqp.py funcao "mecânico montador"  preços de HH de uma função (normal, HE 65%, HE 100%, adicional noturno)
  qqp.py hh                          tabela de todas as funções de HH com os 4 preços
  qqp.py listar [--categoria TEXTO]  lista os itens (todos ou de uma categoria)

Opções (depois do comando):
  --csv CAMINHO     o CSV da QQP, só com este nome (padrão: variável QQP_CSV, depois
                    $BEACONOS_VAULT/projects/montisol/assets/qqp/, depois /vault/projects/montisol/assets/qqp/)
  --formato tabela|json|csv   (padrão: tabela)
"""
import argparse
import csv
import json
import os
import sys
import unicodedata

NOME_CSV = "qqp-trocador-calor-4600014468.csv"
TIPOS = [("normal", "Hora normal"), ("he65", "HE 65%"), ("he100", "HE 100%"), ("adicional_noturno", "Ad. noturno")]


def achar_csv(arg):
    # o código fica no repositório de scripts; o CSV, no vault. Só o arquivo da QQP é lido.
    if arg and os.path.basename(os.path.realpath(arg)) != NOME_CSV:
        sys.exit(f"--csv aceita só o arquivo {NOME_CSV}")
    candidatos = []
    if arg:
        candidatos.append(arg)
    if os.environ.get("QQP_CSV"):
        candidatos.append(os.environ["QQP_CSV"])
    cofre = os.environ.get("BEACONOS_VAULT")
    sub = os.path.join("projects", "montisol", "assets", "qqp", NOME_CSV)
    if cofre:
        candidatos.append(os.path.join(cofre, sub))
    candidatos.append(os.path.join("/vault", sub))
    for c in candidatos:
        if os.path.isfile(c):
            return c
    sys.exit("CSV da QQP não encontrado. Tentei:\n  " + "\n  ".join(candidatos))


def ler(caminho):
    with open(caminho, "r", encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    for r in linhas:
        r["item"] = int(r["item"])
        for k in ("quantidade", "preco_unitario", "valor_total"):
            r[k] = float(r[k])
        r["participacao_pct"] = int(r["participacao_pct"])
    return linhas


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tabela(cabecalho, linhas):
    larg = [len(c) for c in cabecalho]
    for l in linhas:
        for i, c in enumerate(l):
            larg[i] = max(larg[i], len(str(c)))
    fmt = "  ".join("{:<" + str(w) + "}" for w in larg)
    out = [fmt.format(*cabecalho), fmt.format(*["-" * w for w in larg])]
    out += [fmt.format(*[str(c) for c in l]) for l in linhas]
    return "\n".join(out)


def emitir(formato, cabecalho, linhas, registros=None):
    if formato == "json":
        reg = registros if registros is not None else [dict(zip(cabecalho, l)) for l in linhas]
        print(json.dumps(reg, ensure_ascii=False, indent=2))
    elif formato == "csv":
        w = csv.writer(sys.stdout, delimiter=";", lineterminator="\n")
        w.writerow(cabecalho)
        w.writerows(linhas)
    else:
        print(tabela(cabecalho, linhas) if linhas else "(nada encontrado)")


def linha_item(r):
    return [r["item"], r["categoria"], r["descricao"], r["unidade"], brl(r["quantidade"]), brl(r["preco_unitario"]), brl(r["valor_total"])]


CAB_ITEM = ["item", "categoria", "descricao", "un", "qtd", "preco_unit", "valor_total"]


def cmd_resumo(dados, fmt):
    por = {}
    for r in dados:
        por.setdefault(r["categoria"], [0, 0.0])
        por[r["categoria"]][0] += 1
        por[r["categoria"]][1] += r["valor_total"]
    total = sum(r["valor_total"] for r in dados)
    linhas = [[c, n, brl(v), f"{v / total * 100:.1f}%".replace(".", ",")] for c, (n, v) in sorted(por.items(), key=lambda x: -x[1][1])]
    linhas.append(["TOTAL", len(dados), brl(total), "100,0%"])
    emitir(fmt, ["categoria", "itens", "valor_total", "parte"], linhas)
    div = [r["item"] for r in dados if not r["valor_confere"].startswith("sim")]
    if div and fmt == "tabela":
        print("\nItens em que quantidade x preço unitário difere do valor total do PDF (arredondamento da QQP): "
              + ", ".join(map(str, div)))


def cmd_categorias(dados, fmt):
    vistos = {}
    for r in dados:
        vistos.setdefault((r["grupo"], r["categoria"]), 0)
        vistos[(r["grupo"], r["categoria"])] += 1
    emitir(fmt, ["grupo", "categoria", "itens"], [[g, c, n] for (g, c), n in vistos.items()])


def cmd_item(dados, fmt, numeros):
    alvo = {int(n) for n in numeros}
    achados = [r for r in dados if r["item"] in alvo]
    faltam = sorted(alvo - {r["item"] for r in achados})
    emitir(fmt, CAB_ITEM, [linha_item(r) for r in achados], achados)
    if faltam:
        print(f"Itens que não existem na QQP: {', '.join(map(str, faltam))}", file=sys.stderr)


def cmd_buscar(dados, fmt, texto):
    chave = sem_acento(texto)
    achados = [r for r in dados if chave in sem_acento(" ".join([r["descricao"], r["funcao"], r["categoria"], r["grupo"]]))]
    emitir(fmt, CAB_ITEM, [linha_item(r) for r in achados], achados)


def hh_por_funcao(dados):
    m = {}
    for r in dados:
        if r["tipo_hora"]:
            m.setdefault(r["funcao"], {})[r["tipo_hora"]] = r
    return m


def cmd_funcao(dados, fmt, nome):
    chave = sem_acento(nome)
    m = hh_por_funcao(dados)
    achadas = [f for f in m if chave in sem_acento(f)]
    if not achadas:
        print(f"Nenhuma função de HH com '{nome}'. Funções: " + ", ".join(m), file=sys.stderr)
        return
    linhas, regs = [], []
    for f in achadas:
        for t, rot in TIPOS:
            r = m[f].get(t)
            if r:
                linhas.append([f, rot, r["item"], brl(r["preco_unitario"])])
                regs.append({"funcao": f, "tipo": t, "item": r["item"], "preco_unitario": r["preco_unitario"]})
    emitir(fmt, ["funcao", "tipo", "item", "preco_hh_R$"], linhas, regs)


def cmd_hh(dados, fmt):
    m = hh_por_funcao(dados)
    linhas, regs = [], []
    for f, d in m.items():
        linhas.append([f] + [brl(d[t]["preco_unitario"]) if t in d else "-" for t, _ in TIPOS] + [f"{min(r['item'] for r in d.values())}-{max(r['item'] for r in d.values())}"])
        regs.append({"funcao": f, **{t: (d[t]["preco_unitario"] if t in d else None) for t, _ in TIPOS}})
    emitir(fmt, ["funcao"] + [rot for _, rot in TIPOS] + ["itens"], linhas, regs)


def cmd_listar(dados, fmt, categoria):
    sel = dados
    if categoria:
        chave = sem_acento(categoria)
        sel = [r for r in dados if chave in sem_acento(r["categoria"] + " " + r["grupo"])]
    emitir(fmt, CAB_ITEM, [linha_item(r) for r in sel], sel)


def main():
    pai = argparse.ArgumentParser(add_help=False)
    pai.add_argument("--csv")
    pai.add_argument("--formato", choices=["tabela", "json", "csv"], default="tabela")
    ap = argparse.ArgumentParser(description="Consulta (somente leitura) da QQP do contrato Trocador de Calor 4600014468")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resumo", parents=[pai])
    sub.add_parser("categorias", parents=[pai])
    sub.add_parser("hh", parents=[pai])
    p = sub.add_parser("item", parents=[pai]); p.add_argument("numeros", nargs="+")
    p = sub.add_parser("buscar", parents=[pai]); p.add_argument("texto")
    p = sub.add_parser("funcao", parents=[pai]); p.add_argument("nome")
    p = sub.add_parser("listar", parents=[pai]); p.add_argument("--categoria")
    a = ap.parse_args()
    dados = ler(achar_csv(a.csv))
    if a.cmd == "resumo": cmd_resumo(dados, a.formato)
    elif a.cmd == "categorias": cmd_categorias(dados, a.formato)
    elif a.cmd == "hh": cmd_hh(dados, a.formato)
    elif a.cmd == "item": cmd_item(dados, a.formato, a.numeros)
    elif a.cmd == "buscar": cmd_buscar(dados, a.formato, a.texto)
    elif a.cmd == "funcao": cmd_funcao(dados, a.formato, a.nome)
    elif a.cmd == "listar": cmd_listar(dados, a.formato, a.categoria)


if __name__ == "__main__":
    main()
