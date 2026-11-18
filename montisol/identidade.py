#!/usr/bin/env python3
# Consulta a identidade visual da Montisol; só lê o tokens.json e as imagens do vault.
# precisa: nada
"""Consulta (somente leitura) da identidade visual da Montisol: cores, logos, ícones, fotos, layouts e regras.

Lê `tokens.json` da pasta da identidade visual no vault e imprime caminhos absolutos dos arquivos. Não grava nada.
A pasta: variável IDENTIDADE_DIR, depois $BEACONOS_VAULT/projects/montisol/assets/identidade-visual, depois
/vault/projects/montisol/assets/identidade-visual.
Só biblioteca padrão do Python 3.

Uso:
  identidade.py resumo
  identidade.py cores [--oficiais]
  identidade.py logo [--fundo claro|escuro|azul] [--formato horizontal|vertical] [--alta]
  identidade.py icone <busca> [--fundo claro|escuro]     (busca por nome ou tema: ideia, seguranca, equipe...)
  identidade.py icones                                    (lista todos)
  identidade.py foto [--orientacao horizontal|vertical|quadrada]
  identidade.py layouts | layout <número ou busca>
  identidade.py regras
  identidade.py institucional
Opção: --json em qualquer comando para saída em JSON.
"""
import argparse
import json
import os
import sys
import unicodedata

SUB = os.path.join("projects", "montisol", "assets", "identidade-visual")


def achar_pasta():
    # o código fica no repositório de scripts; o tokens.json e as imagens, no vault
    cand = [os.environ.get("IDENTIDADE_DIR"),
            os.path.join(os.environ["BEACONOS_VAULT"], SUB) if os.environ.get("BEACONOS_VAULT") else None,
            os.path.join("/vault", SUB)]
    cand = [c for c in cand if c]
    for c in cand:
        if os.path.isfile(os.path.join(c, "tokens.json")):
            return c
    sys.exit("Pasta da identidade visual não encontrada (sem o tokens.json). Tentei:\n  " + "\n  ".join(cand))


AQUI = achar_pasta()
T = json.load(open(os.path.join(AQUI, "tokens.json"), encoding="utf-8"))


def sa(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")


def p(rel):
    return os.path.join(AQUI, rel)


def out(args, obj, texto):
    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(texto)


def cmd_resumo(a):
    c = T["cores"]["oficiais"]
    txt = ["Identidade visual Montisol (fonte: " + T["fonte"] + ")", "",
           "Cores oficiais: " + ", ".join(f"{x['nome']} {x['hex']}" for x in c),
           "Fontes: " + T["tipografia"]["titulos"] + "; corpo: " + T["tipografia"]["corpo"],
           f"Logos: {len(T['logos'])} arquivos; ícones: {len(T['icones']['lista'])} (branco e preto); fotos: {len(T['fotos']['lista'])}; layouts: {len(T['layouts'])}",
           "Formato: " + T["formato_slide"]["proporcao"] + " (" + T["formato_slide"]["viewBox"] + ")",
           "Redes: " + T["redes"]["instagram"] + " e " + T["redes"]["site"], "",
           "Regra do logo: " + T["regras_logo"][0], "Pasta: " + AQUI]
    out(a, {"cores": c, "tipografia": T["tipografia"], "pasta": AQUI}, "\n".join(txt))


def cmd_cores(a):
    listas = [("OFICIAIS", T["cores"]["oficiais"])]
    if not a.oficiais:
        listas.append(("OBSERVADAS NO MODELO (apoio)", T["cores"]["observadas_no_modelo"]))
    txt = []
    for tit, l in listas:
        txt.append(tit)
        txt += [f"  {x['hex']}  {x['nome']}: {x['uso']}" for x in l]
    txt.append("Nota: " + T["cores"]["nota"])
    out(a, {k: v for k, v in T["cores"].items() if k != "nota" and (not a.oficiais or k == "oficiais")}, "\n".join(txt))


def cmd_logo(a):
    fundo = a.fundo or "claro"
    cor = "colorido" if fundo == "claro" else "branco"
    fmt = a.formato or "vertical"
    cand = [l for l in T["logos"] if l["variante"] == fmt and l["cor"] == cor]
    if a.alta:
        cand = [l for l in T["logos"] if "alta-resolucao" in l["arquivo"]] or cand
    if not cand:
        cand = [l for l in T["logos"] if l["cor"] == cor][:1]
    res = [dict(l, caminho=p(l["arquivo"])) for l in cand]
    txt = [f"Fundo {fundo}, formato {fmt}:"] + [f"  {r['caminho']}  ({r['pixels']}, {r['cor']})" for r in res]
    txt += ["Regras:"] + ["  - " + r for r in T["regras_logo"]]
    out(a, {"logo": res, "regras": T["regras_logo"]}, "\n".join(txt))


def cmd_icone(a):
    q = sa(a.busca)
    achados = [i for i in T["icones"]["lista"] if q in sa(i["nome"]) or any(q in sa(t) or sa(t) in q for t in i["tags"])]
    pasta = T["icones"]["pasta_preto" if (a.fundo or "claro") == "claro" else "pasta_branco"]
    res = [dict(i, caminho=p(f"{pasta}/{i['arquivo']}")) for i in achados]
    txt = [f"{len(res)} ícone(s) para '{a.busca}' (versão {'preta' if pasta.endswith('preto') else 'branca'}):"]
    txt += [f"  {r['caminho']}  [{', '.join(r['tags'])}]" for r in res] or ["  nenhum; use `icones` para ver todos"]
    out(a, res, "\n".join(txt))


def cmd_icones(a):
    txt = [f"  {i['arquivo']}  [{', '.join(i['tags'])}]" for i in T["icones"]["lista"]]
    out(a, T["icones"]["lista"], T["icones"]["estilo"] + "\n" + "\n".join(txt))


def cmd_foto(a):
    fs = [f for f in T["fotos"]["lista"] if not a.orientacao or f["orientacao"] == a.orientacao]
    res = [dict(f, caminho=p("fotos/" + f["arquivo"])) for f in fs]
    out(a, {"regra": T["fotos"]["regra"], "fotos": res}, T["fotos"]["regra"] + "\n" + "\n".join(f"  {r['caminho']} ({r['orientacao']}, {r['pixels']})" for r in res))


def cmd_layouts(a):
    out(a, T["layouts"], "\n".join(f"  {l['slide']:>2}  {l['nome']}: {l['descricao']}" for l in T["layouts"]))


def cmd_layout(a):
    q = sa(a.busca)
    achados = [l for l in T["layouts"] if q == str(l["slide"]) or q in sa(l["nome"]) or q in sa(l["descricao"])]
    res = [dict(l, miniatura=p(f"modelo-slides/slide{l['slide']:02d}.jpg")) for l in achados]
    out(a, res, "\n".join(f"  slide {r['slide']}: {r['nome']}: {r['descricao']}\n     miniatura: {r['miniatura']}" for r in res) or "nenhum layout encontrado")


def cmd_regras(a):
    out(a, {"logo": T["regras_logo"], "elementos_fixos": T["elementos_fixos"], "gerais": T["regras_gerais"]},
        "Logo:\n" + "\n".join("  - " + r for r in T["regras_logo"]) + "\nElementos fixos:\n" + "\n".join("  - " + r for r in T["elementos_fixos"]) +
        "\nGerais:\n" + "\n".join("  - " + r for r in T["regras_gerais"]))


def cmd_inst(a):
    i = T["institucional"]
    out(a, i, f"Missão: {i['missao']}\nVisão: {i['visao']}\nValores:\n" + "\n".join("  - " + v for v in i["valores"]) + "\nNota: " + i["nota"])


def main():
    pai = argparse.ArgumentParser(add_help=False)
    pai.add_argument("--json", action="store_true")
    ap = argparse.ArgumentParser(description="Consulta da identidade visual da Montisol (somente leitura)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resumo", parents=[pai])
    s = sub.add_parser("cores", parents=[pai]); s.add_argument("--oficiais", action="store_true")
    s = sub.add_parser("logo", parents=[pai]); s.add_argument("--fundo", choices=["claro", "escuro", "azul"]); s.add_argument("--formato", choices=["horizontal", "vertical"]); s.add_argument("--alta", action="store_true")
    s = sub.add_parser("icone", parents=[pai]); s.add_argument("busca"); s.add_argument("--fundo", choices=["claro", "escuro"])
    sub.add_parser("icones", parents=[pai])
    s = sub.add_parser("foto", parents=[pai]); s.add_argument("--orientacao", choices=["horizontal", "vertical", "quadrada"])
    sub.add_parser("layouts", parents=[pai])
    s = sub.add_parser("layout", parents=[pai]); s.add_argument("busca")
    sub.add_parser("regras", parents=[pai])
    sub.add_parser("institucional", parents=[pai])
    a = ap.parse_args()
    {"resumo": cmd_resumo, "cores": cmd_cores, "logo": cmd_logo, "icone": cmd_icone, "icones": cmd_icones, "foto": cmd_foto,
     "layouts": cmd_layouts, "layout": cmd_layout, "regras": cmd_regras, "institucional": cmd_inst}[a.cmd](a)


if __name__ == "__main__":
    main()
