@echo off
title Configurando Menu de Contexto Whisper

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$PythonPath = 'C:\dev\venv\Scripts\python.exe';" ^
  "$ScriptPath = 'C:\dev\scripts\transcribe\transcribe.py';" ^
  "if (-not (Test-Path $PythonPath)) { Write-Warning \"[!] Python nao encontrado em: $PythonPath\" };" ^
  "if (-not (Test-Path $ScriptPath)) { Write-Warning \"[!] Script nao encontrado em: $ScriptPath\" };" ^
  "@('HKCU:\Software\Classes\SystemFileAssociations\audio\shell\TranscribeAudio', 'HKCU:\Software\Classes\WhisperActions') | ForEach-Object { if (Test-Path $_) { Remove-Item -Path $_ -Recurse -Force } };" ^
  "$parent = 'HKCU:\Software\Classes\SystemFileAssociations\audio\shell\TranscribeAudio';" ^
  "New-Item -Path $parent -Force | Out-Null;" ^
  "Set-ItemProperty -Path $parent -Name 'MUIVerb' -Value 'Transcrever com Whisper';" ^
  "Set-ItemProperty -Path $parent -Name 'ExtendedSubCommandsKey' -Value 'WhisperActions';" ^
  "$items = @(" ^
    "@{ Key='01_Padrao'; Name=\"Padr$([char]0x00E3)o (Modelo Base)\"; Args='' }," ^
    "@{ Key='02_Timestamps'; Name=\"Padr$([char]0x00E3)o + Timestamps\"; Args='--timestamps' }," ^
    "@{ Key='03_Rapido'; Name=\"R$([char]0x00E1)pido (Modelo Tiny)\"; Args='-m tiny' }," ^
    "@{ Key='04_Precisao'; Name=\"Alta Precis$([char]0x00E3)o (Modelo Small)\"; Args='-m small' }," ^
    "@{ Key='05_PTBR'; Name=\"Portugu$([char]0x00EA)s (PT-BR) + Timestamps\"; Args='-l pt --timestamps' }," ^
    "@{ Key='06_Diarizacao'; Name=\"Identificar Falantes (Diariza$([char]0x00E7)$([char]0x00E3)o)\"; Args='--diarize --timestamps' }" ^
  ");" ^
  "foreach ($it in $items) {" ^
    "$p = \"HKCU:\Software\Classes\WhisperActions\shell\$($it.Key)\";" ^
    "New-Item -Path $p -Force | Out-Null;" ^
    "Set-ItemProperty -Path $p -Name '(Default)' -Value $it.Name;" ^
    "$c = \"$p\command\";" ^
    "New-Item -Path $c -Force | Out-Null;" ^
    "$a = if ($it.Args) { ' ' + $it.Args } else { '' };" ^
    "$cmd = 'cmd.exe /k \"\"' + $PythonPath + '\" \"' + $ScriptPath + '\" \"%1\"' + $a + '\"';" ^
    "Set-ItemProperty -Path $c -Name '(Default)' -Value $cmd;" ^
  "};" ^
  "Write-Host '[*] Reiniciando Explorer...' -ForegroundColor Cyan;" ^
  "Stop-Process -Name explorer -Force;" ^
  "Write-Host '[✓] Concluido com sucesso!' -ForegroundColor Green;"

pause
