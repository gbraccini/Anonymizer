<#
.SYNOPSIS
    Apre un tunnel SSH locale verso il servizio della prova Docker.

.DESCRIPTION
    Inoltra la porta locale 127.0.0.1:8766 alla porta 18765 del server remoto, dove
    il container della prova ascolta solo in locale. Lo script si ferma senza
    toccare processi se la porta locale e' gia occupata, avvia ssh in background
    in modalita non interattiva con verifica rigorosa della chiave dell'host e
    attende fino a circa 15 secondi che il tunnel sia in ascolto.
    Il processo ssh resta attivo dopo la fine dello script: per chiudere il tunnel
    va terminato tramite il PID riportato.

.PARAMETER SshHost
    Destinazione SSH (alias di configurazione o utente@host). L'host deve essere
    gia presente tra gli host noti e l'accesso deve avvenire con chiave, senza
    richieste interattive.

.EXAMPLE
    .\Open-DebianTrial.ps1 -SshHost trial-alias

    Apre il tunnel e, se va a buon fine, stampa l'URL locale da aprire nel browser.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$SshHost
)

$ErrorActionPreference = 'Stop'

$trialPort = 8766
$trialUrl = "http://127.0.0.1:$trialPort"
if (Get-NetTCPConnection -State Listen -LocalPort $trialPort -ErrorAction SilentlyContinue) {
    throw "Porta $trialPort gia occupata. Nessun processo modificato. Verifica il tunnel esistente."
}

$sshPath = (Get-Command ssh -CommandType Application -ErrorAction Stop).Source
$tunnelArgs = @(
    '-N', '-T',
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'ConnectTimeout=10',
    '-L', '127.0.0.1:8766:127.0.0.1:18765',
    $SshHost
)
$tunnel = Start-Process -FilePath $sshPath -ArgumentList $tunnelArgs -WindowStyle Hidden -PassThru
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($tunnel.HasExited) {
        throw 'Tunnel SSH non avviato. Verifica connessione, chiave SSH e host gia riconosciuto.'
    }
    if (Get-NetTCPConnection -State Listen -LocalPort $trialPort -ErrorAction SilentlyContinue) {
        Write-Output "Tunnel pronto: $trialUrl (PID SSH $($tunnel.Id))."
        return
    }
    Start-Sleep -Milliseconds 250
}
Write-Warning "Avvio tunnel non confermato. PID SSH $($tunnel.Id); verifica la connessione."
