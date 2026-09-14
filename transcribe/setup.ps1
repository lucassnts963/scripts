# Remove entradas anteriores
@('HKCU:\Software\Classes\SystemFileAssociations\audio\shell\TranscribeAudio', 'HKCU:\Software\Classes\WhisperActions') | ForEach-Object {
    if (Test-Path $_) { Remove-Item -Path $_ -Recurse -Force }
}

# Registra o menu principal
$parent = 'HKCU:\Software\Classes\SystemFileAssociations\audio\shell\TranscribeAudio'
New-Item -Path $parent -Force | Out-Null
Set-ItemProperty -Path $parent -Name 'MUIVerb' -Value 'Transcrever com Whisper'
Set-ItemProperty -Path $parent -Name 'ExtendedSubCommandsKey' -Value 'WhisperActions'

$batPath = "C:\dev\scripts\transcribe\run_transcribe.bat"

# Definição com escape Unicode puro (independente de codificação de arquivo)
$items = @(
    @{ Key='01_Padrao'; Name="Padr$([char]0x00E3)o (Modelo Base)"; Args='' },
    @{ Key='02_Timestamps'; Name="Padr$([char]0x00E3)o + Timestamps"; Args='--timestamps' },
    @{ Key='03_Rapido'; Name="R$([char]0x00E1)pido (Modelo Tiny)"; Args='-m tiny' },
    @{ Key='04_Precisao'; Name="Alta Precis$([char]0x00E3)o (Modelo Small)"; Args='-m small' },
    @{ Key='05_PTBR'; Name="Portugu$([char]0x00EA)s (PT-BR) + Timestamps"; Args='-l pt --timestamps' },
    @{ Key='06_Diarizacao'; Name="Identificar Falantes (Diariza$([char]0x00E7)$([char]0x00E3)o)"; Args='--diarize --timestamps' }
)

foreach ($it in $items) {
    $keyPath = "HKCU:\Software\Classes\WhisperActions\shell\$($it.Key)"
    New-Item -Path $keyPath -Force | Out-Null
    Set-ItemProperty -Path $keyPath -Name '(Default)' -Value $it.Name

    $cmdPath = "$keyPath\command"
    New-Item -Path $cmdPath -Force | Out-Null

    $arg = if ($it.Args) { " " + $it.Args } else { "" }
    # Chamada direta e limpa para o .bat sem o emaranhado de aspas do CMD
    $execStr = "`"$batPath`" `"%1`"$arg"
    Set-ItemProperty -Path $cmdPath -Name '(Default)' -Value $execStr
}

Stop-Process -Name explorer -Force
Write-Host "[OK] Menu configurado com sucesso!" -ForegroundColor Green
