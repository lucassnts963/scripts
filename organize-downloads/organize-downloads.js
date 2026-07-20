#!/usr/bin/env node
'use strict';

/**
 * organize-downloads
 * Organiza uma pasta (por padrão, a de Downloads do usuário) movendo cada
 * arquivo para uma subpasta de acordo com seu tipo.
 *
 * Uso:
 *   node organize-downloads.js [opções]
 *
 * Opções:
 *   -d, --dir <caminho>   Pasta a organizar (padrão: ~/Downloads)
 *   -n, --dry-run         Só mostra o que faria, sem mover nada
 *   -h, --help            Mostra esta ajuda
 *
 * Sem dependências externas — usa apenas os módulos nativos do Node.
 * Idempotente: rodar de novo não quebra nada (subpastas de categoria são ignoradas).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

// Extensão (sem ponto, minúscula) -> nome da subpasta de categoria.
const CATEGORIES = {
  Imagens: ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'heic', 'tiff', 'ico'],
  Documentos: ['pdf', 'doc', 'docx', 'txt', 'md', 'rtf', 'odt', 'xls', 'xlsx', 'csv', 'ppt', 'pptx', 'odp', 'ods', 'epub'],
  Videos: ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v'],
  Audio: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'wma'],
  Compactados: ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'iso'],
  Programas: ['exe', 'msi', 'deb', 'appimage', 'dmg', 'pkg', 'apk', 'bat'],
  Codigo: ['js', 'ts', 'jsx', 'tsx', 'py', 'java', 'c', 'cpp', 'h', 'cs', 'go', 'rs', 'rb', 'php', 'html', 'css', 'json', 'xml', 'yml', 'yaml', 'sh'],
};

const OUTROS = 'Outros';

// Todas as pastas de categoria — usadas para não reprocessar o que já foi organizado.
const CATEGORY_DIRS = new Set([...Object.keys(CATEGORIES), OUTROS]);

// Mapa reverso extensão -> categoria, montado uma vez.
const EXT_TO_CATEGORY = {};
for (const [category, exts] of Object.entries(CATEGORIES)) {
  for (const ext of exts) EXT_TO_CATEGORY[ext] = category;
}

function parseArgs(argv) {
  const opts = { dir: path.join(os.homedir(), 'Downloads'), dryRun: false, help: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '-d' || arg === '--dir') {
      opts.dir = argv[++i];
    } else if (arg === '-n' || arg === '--dry-run') {
      opts.dryRun = true;
    } else if (arg === '-h' || arg === '--help') {
      opts.help = true;
    } else {
      console.error(`Opção desconhecida: ${arg}`);
      opts.help = true;
    }
  }
  return opts;
}

function printHelp() {
  console.log(`organize-downloads — organiza uma pasta movendo arquivos por tipo.

Uso:
  node organize-downloads.js [opções]

Opções:
  -d, --dir <caminho>   Pasta a organizar (padrão: ~/Downloads)
  -n, --dry-run         Só mostra o que faria, sem mover nada
  -h, --help            Mostra esta ajuda`);
}

function categoryFor(fileName) {
  const ext = path.extname(fileName).slice(1).toLowerCase();
  if (!ext) return OUTROS;
  return EXT_TO_CATEGORY[ext] || OUTROS;
}

/**
 * Retorna um caminho de destino que não colide com arquivo existente,
 * acrescentando " (1)", " (2)", ... antes da extensão quando necessário.
 */
function resolveCollision(destDir, fileName) {
  let candidate = path.join(destDir, fileName);
  if (!fs.existsSync(candidate)) return candidate;

  const ext = path.extname(fileName);
  const base = path.basename(fileName, ext);
  let i = 1;
  do {
    candidate = path.join(destDir, `${base} (${i})${ext}`);
    i++;
  } while (fs.existsSync(candidate));
  return candidate;
}

/** Move respeitando cross-device (rename falha entre volumes -> copia e apaga). */
function moveFile(src, dest) {
  try {
    fs.renameSync(src, dest);
  } catch (err) {
    if (err.code === 'EXDEV') {
      fs.copyFileSync(src, dest);
      fs.unlinkSync(src);
    } else {
      throw err;
    }
  }
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    printHelp();
    return;
  }

  const dir = path.resolve(opts.dir);
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
    console.error(`Pasta não encontrada: ${dir}`);
    process.exitCode = 1;
    return;
  }

  console.log(`Organizando: ${dir}${opts.dryRun ? '  (dry-run)' : ''}\n`);

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const counts = {};
  let moved = 0;

  for (const entry of entries) {
    if (!entry.isFile()) continue;            // ignora subpastas
    if (entry.name.startsWith('.')) continue; // ignora arquivos ocultos

    const category = categoryFor(entry.name);
    const src = path.join(dir, entry.name);
    const destDir = path.join(dir, category);
    const dest = resolveCollision(destDir, entry.name);

    if (opts.dryRun) {
      console.log(`  ${entry.name}  ->  ${category}/${path.basename(dest)}`);
    } else {
      fs.mkdirSync(destDir, { recursive: true });
      moveFile(src, dest);
      console.log(`  ${entry.name}  ->  ${category}/${path.basename(dest)}`);
    }

    counts[category] = (counts[category] || 0) + 1;
    moved++;
  }

  console.log('');
  if (moved === 0) {
    console.log('Nada para organizar. 🎉');
  } else {
    const resumo = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([cat, n]) => `${cat}: ${n}`)
      .join(', ');
    console.log(`${opts.dryRun ? 'Moveria' : 'Movidos'} ${moved} arquivo(s) — ${resumo}`);
  }
}

main();
