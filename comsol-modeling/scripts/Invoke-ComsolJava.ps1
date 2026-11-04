# Compatible with Windows PowerShell 5.1 and PowerShell 7; no COMSOL starts by default.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$ConfigPath,
    [string]$JobFile,
    [string]$PreferencesFile,
    [string]$PermissionsReviewFile,
    [string]$InputModel,
    [string[]]$RuntimeInput,
    [switch]$Execute,
    [string]$ReviewedSourceSha256,
    [string]$OperationReview,
    [ValidateSet('build','modify','inspect')][string]$Operation = 'inspect',
    [string[]]$Scope,
    [string]$CurrentAuthorization,
    [string]$Python = 'python'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 initializes PSScriptRoot after parameter defaults.
if (-not $PSBoundParameters.ContainsKey('ConfigPath')) {
    $ConfigPath = Join-Path $PSScriptRoot '../assets/environment.local.json'
}

function Resolve-File([string]$Path) {
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer) { throw "Expected a file: $Path" }
    return $item.FullName
}

function Hash-Bytes([byte[]]$Bytes) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}

function Assert-Snapshot($Snapshot) {
    foreach ($entry in $Snapshot.inputs) {
        if (-not (Test-Path -LiteralPath $entry.path -PathType Leaf) -or
            (Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw ('Prepared runtime input changed: ' + $entry.path)
        }
    }
}

function Assert-Copy([string]$Path, [string]$ExpectedHash) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
        throw ('Prepared copy changed: ' + $Path)
    }
}

function Invoke-PythonJson([string[]]$Arguments) {
    $previousEncoding = [Console]::OutputEncoding
    try {
        # Python emits UTF-8 explicitly; Windows PowerShell 5.1 must decode it likewise.
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $text = & $Python @Arguments
        return @{ Text = ($text -join [Environment]::NewLine); Code = $LASTEXITCODE }
    } finally { [Console]::OutputEncoding = $previousEncoding }
}

$sourcePath = Resolve-File $Source
if ([IO.Path]::GetExtension($sourcePath) -cne '.java') { throw 'Source must be a .java file, never an MPH input.' }
$sourceText = [IO.File]::ReadAllText($sourcePath)
if ($sourceText -match '(?m)^\s*package\s+[\w.]+\s*;') { throw 'This entry point supports one package-free Java source; use a separately reviewed runner for multi-file projects.' }
$className = [IO.Path]::GetFileNameWithoutExtension($sourcePath)
if ($className -notmatch '^[A-Za-z_$][A-Za-z0-9_$]*$') { throw 'Use a Java class filename with an ASCII identifier.' }
$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$configFile = Resolve-File $ConfigPath
$configBytes = [IO.File]::ReadAllBytes($configFile)
$configHash = Hash-Bytes $configBytes
$config = [Text.Encoding]::UTF8.GetString($configBytes).TrimStart([char]0xFEFF) | ConvertFrom-Json
$root = [IO.Path]::GetFullPath([string]$config.comsol_root)
$compiler = Resolve-File (Join-Path $root 'bin/win64/comsolcompile.exe')
$batch = Resolve-File (Join-Path $root 'bin/win64/comsolbatch.exe')
$runPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunDirectory)
if (Test-Path -LiteralPath $runPath) { throw 'RunDirectory must be a new directory; this prevents stale classes and accidental output replacement.' }
$preferencesPath = $null
$preferencesHash = $null
$permissionsReviewPath = $null
if ($PreferencesFile) {
    $preferencesPath = Resolve-File $PreferencesFile
    $preferencesHash = (Get-FileHash -LiteralPath $preferencesPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($PermissionsReviewFile) { $permissionsReviewPath = Resolve-File $PermissionsReviewFile }
$jobPath = $null
if ($JobFile) { $jobPath = Resolve-File $JobFile }
$gatePath = Resolve-File (Join-Path $PSScriptRoot 'modeling_gate.py')
$runtimeFiles = @($sourcePath, $configFile, $compiler, $batch, $PSCommandPath, $gatePath,
    (Resolve-File (Join-Path $PSScriptRoot 'operation_review.py')),
    (Resolve-File (Join-Path $PSScriptRoot 'contract_v2.py')),
    (Resolve-File (Join-Path $PSScriptRoot '../references/model-manifest.schema.json')),
    (Resolve-File (Join-Path $PSScriptRoot '../references/operation-review.schema.json')))
if ($jobPath) { $runtimeFiles += $jobPath }
if ($preferencesPath) { $runtimeFiles += $preferencesPath }
if ($permissionsReviewPath) { $runtimeFiles += $permissionsReviewPath }
foreach ($path in $RuntimeInput) { $runtimeFiles += (Resolve-File $path) }
$reviewPath = $null
$reviewHash = $null
if ($OperationReview) {
    $reviewPath = Resolve-File $OperationReview
    $reviewBytes = [IO.File]::ReadAllBytes($reviewPath)
    $reviewHash = Hash-Bytes $reviewBytes
    $reviewRecord = [Text.Encoding]::UTF8.GetString($reviewBytes).TrimStart([char]0xFEFF) | ConvertFrom-Json
    foreach ($pin in $reviewRecord.pins) { $runtimeFiles += [string]$pin.path }
}
$bindingArgs = @('--operation', $Operation, '--run-directory', $runPath)
if ($jobPath) { $bindingArgs += @('--job', $jobPath) }
if ($InputModel) { $bindingArgs += @('--input-model', (Resolve-File $InputModel)) }
foreach ($runtimeFile in $runtimeFiles) { $bindingArgs += @('--require-file', $runtimeFile) }
$describeArgs = @('-X', 'utf8', '-B', $gatePath, '--describe-inputs') + $bindingArgs
$snapshotProcess = Invoke-PythonJson $describeArgs
if ($snapshotProcess.Code -ne 0) { throw 'Could not describe actual runtime inputs.' }
$snapshot = $snapshotProcess.Text | ConvertFrom-Json
$jobHash = $null
if ($jobPath) { $jobHash = @($snapshot.inputs | Where-Object { $_.path -eq $jobPath })[0].sha256 }
# Separate per-invocation contexts; no user/installation preferences are edited.
$contexts = [ordered]@{}
foreach ($stageName in @('compile','batch')) {
    $context = [ordered]@{}
    foreach ($name in @('configuration','workspace','prefs','tmp','recovery')) {
        $context[$name] = Join-Path $runPath ('_runtime/' + $stageName + '/' + $name)
    }
    $contexts[$stageName] = $context
}
function Context-Arguments($Context) {
    return @('-migrateprefs', 'off', '-configuration', $Context.configuration,
        '-data', $Context.workspace, '-prefsdir', $Context.prefs,
        '-tmpdir', $Context.tmp, '-recoverydir', $Context.recovery)
}
$compileArgs = @(Context-Arguments $contexts.compile) + @('-verbose', [IO.Path]::GetFileName($sourcePath))
$batchArgs = @(Context-Arguments $contexts.batch) + @('-inputfile', ($className + '.class'), '-nosave', '-batchlog', 'comsol-batch.log')
$plan = [ordered]@{
    execution_requested = [bool]$Execute
    powershell_version = $PSVersionTable.PSVersion.ToString()
    expected_comsol_major_minor = [string]$config.expected_major_minor
    version_status = 'not_checked_at_runtime'
    source = $sourcePath
    source_sha256 = $sourceHash
    config_file = $configFile
    config_sha256 = $configHash
    preferences_file = $preferencesPath
    preferences_sha256 = $preferencesHash
    permissions_review_file = $permissionsReviewPath
    permission_readiness = $(if ($preferencesPath -and $permissionsReviewPath) { "requires_scope_review" } else { "pending_explicit_profile_and_review" })
    private_contexts = $contexts
    job_file = $jobPath
    job_sha256 = $jobHash
    input_bindings = $snapshot
    operation = $Operation
    scope = $Scope
    operation_review = $OperationReview
    operation_review_sha256 = $reviewHash
    execution_readiness = 'not_assessed'
    authorization_granted = $false
    working_directory = $runPath
    compiler = $compiler
    compiler_arguments = $compileArgs
    batch = $batch
    batch_arguments = $batchArgs
    model_validation = 'not_run'
    independent_reload = 'not_run_requires_separate_inspect'
    limitation = 'Command plan is not a COMSOL execution sandbox; review Java and job inputs before authorized execution.'
}
if (-not $Execute) { $plan | ConvertTo-Json -Depth 8; return }
if (-not $ReviewedSourceSha256 -or $ReviewedSourceSha256.ToLowerInvariant() -ne $sourceHash) {
    throw 'Execution requires ReviewedSourceSha256 matching the reviewed source and current task authorization.'
}
if (-not $OperationReview -or -not $Scope -or [string]::IsNullOrWhiteSpace($CurrentAuthorization)) {
    throw 'Execution requires an independent operation review, explicit scope and a current authorization record. Ready is not authorization.'
}
if (-not $preferencesPath -or -not $permissionsReviewPath) {
    throw 'Execution requires explicit PreferencesFile and PermissionsReviewFile; no broad file/property permissions are enabled by default.'
}
if ([string]::IsNullOrWhiteSpace([IO.File]::ReadAllText($permissionsReviewPath))) { throw 'PermissionsReviewFile must describe required access and actual isolation limits.' }
$gateArgs = @('-X', 'utf8', '-B', $gatePath, '--review', $reviewPath) + $bindingArgs + @('--scope') + $Scope
$gateResult = Invoke-PythonJson $gateArgs
if ($gateResult.Code -ne 0) { throw ('Operation review is not ready or inputs changed: ' + $gateResult.Text) }
if ((Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reviewHash) { throw 'Operation review changed during preparation.' }
$plan.operation_review = $reviewPath
$plan.execution_readiness = 'ready_for_declared_scope'
$plan['operation_review_sha256'] = $reviewHash
$plan['current_authorization_record'] = $CurrentAuthorization
if ($snapshot.side_errors.Count -ne 0) { throw 'Actual runtime input bindings are incomplete or invalid.' }
Assert-Snapshot $snapshot
if ((Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $configHash) { throw 'Environment configuration changed after parsing.' }

# Once reserved, retain the entire attempt even if staging or execution fails.
New-Item -ItemType Directory -Path $runPath -ErrorAction Stop | Out-Null
$stage = 'staging'
$stages = @()
$locationPushed = $false
$failure = $null
$completion = 'failed'
try {
    foreach ($context in $contexts.Values) {
        foreach ($directory in $context.Values) { New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null }
        Copy-Item -LiteralPath $preferencesPath -Destination (Join-Path $context.prefs 'comsol.prefs') -ErrorAction Stop
        Assert-Copy (Join-Path $context.prefs 'comsol.prefs') $preferencesHash
    }
# Copy first, then hash the copied source to bind execution to the reviewed bytes.
Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runPath ([IO.Path]::GetFileName($sourcePath))) -ErrorAction Stop
$copiedSource = Join-Path $runPath ([IO.Path]::GetFileName($sourcePath))
Assert-Copy $copiedSource $sourceHash
if ($jobPath) {
    Copy-Item -LiteralPath $jobPath -Destination (Join-Path $runPath 'job.properties') -ErrorAction Stop
    Assert-Copy (Join-Path $runPath 'job.properties') $jobHash
}
$plan | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runPath 'execution-plan.json') -Encoding UTF8
Push-Location -LiteralPath $runPath
$locationPushed = $true
    $stage = 'compile_preflight'
    $gateResult = Invoke-PythonJson $gateArgs
    if ($gateResult.Code -ne 0) { throw 'Prepared runtime input changed before compilation.' }
    if ((Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reviewHash) { throw 'Operation review changed before compilation.' }
    Assert-Snapshot $snapshot
    Assert-Copy $copiedSource $sourceHash
    if ($jobPath) { Assert-Copy (Join-Path $runPath 'job.properties') $jobHash }
    Assert-Copy (Join-Path $contexts.compile.prefs 'comsol.prefs') $preferencesHash
    $stage = 'compile'
    & $compiler @compileArgs *> 'compile.log'
    $stages += [ordered]@{stage = 'compile'; exit_code = $LASTEXITCODE; validation = 'not_inferred'}
    if ($LASTEXITCODE -ne 0) { throw "Java compilation failed with exit code $LASTEXITCODE; inspect compile.log." }
    if (-not (Test-Path -LiteralPath ($className + '.class') -PathType Leaf)) { throw 'Compiler produced no expected class file.' }
    # Derived class files get their own record; the original operation review remains immutable.
    $classPins = @()
    foreach ($compiled in @(Get-ChildItem -LiteralPath $runPath -Filter '*.class' -File)) {
        $classPins += [ordered]@{path = $compiled.FullName; sha256 = (Get-FileHash -LiteralPath $compiled.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    [ordered]@{record_type = 'derived_runtime_pins'; operation_review_sha256 = $reviewHash; source_sha256 = $sourceHash; files = $classPins; comsol_model_check_performed = $false} |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'compiled-pins.json' -Encoding UTF8
    $stage = 'batch_preflight'
    $gateResult = Invoke-PythonJson $gateArgs
    if ($gateResult.Code -ne 0) { throw 'Prepared runtime input changed before batch execution.' }
    if ((Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reviewHash) { throw 'Operation review changed before batch execution.' }
    Assert-Snapshot $snapshot
    Assert-Copy $copiedSource $sourceHash
    if ($jobPath) { Assert-Copy (Join-Path $runPath 'job.properties') $jobHash }
    foreach ($pin in $classPins) {
        if ((Get-FileHash -LiteralPath $pin.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin.sha256) { throw 'Derived class changed before batch execution.' }
    }
    if (@(Get-ChildItem -LiteralPath $runPath -Filter '*.class' -File).Count -ne $classPins.Count) { throw 'Derived class set changed before batch execution.' }
    Assert-Copy (Join-Path $contexts.batch.prefs 'comsol.prefs') $preferencesHash
    $stage = 'batch'
    & $batch @batchArgs *> 'launcher.log'
    $stages += [ordered]@{stage = 'batch'; exit_code = $LASTEXITCODE; validation = 'not_inferred'}
    if ($LASTEXITCODE -ne 0) { throw "Java batch failed with exit code $LASTEXITCODE; inspect launcher.log and comsol-batch.log." }
    $stage = 'post_execution_bindings'
    Assert-Snapshot $snapshot
    Assert-Copy $copiedSource $sourceHash
    if ($jobPath) { Assert-Copy (Join-Path $runPath 'job.properties') $jobHash }
    foreach ($pin in $classPins) { Assert-Copy $pin.path $pin.sha256 }
    if (@(Get-ChildItem -LiteralPath $runPath -Filter '*.class' -File).Count -ne $classPins.Count) { throw 'Derived class set changed during batch execution.' }
    # The runner deliberately cannot award a model pass from generic Java output.
    $completion = 'pending_evidence'
    $stage = 'independent_review_required'
    Write-Output 'Launcher exited 0; model status remains pending_evidence. Review detailed reports; build/modify additionally require a separate fresh inspect invocation after saving.'
} catch {
    $failure = $_.Exception.Message
    throw
} finally {
    $logs = @()
    foreach ($name in @('compile.log','launcher.log','comsol-batch.log','compiled-pins.json','execution-plan.json')) {
        $file = Join-Path $runPath $name
        if (Test-Path -LiteralPath $file -PathType Leaf) { $logs += [ordered]@{path=$file; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()} }
    }
    [ordered]@{record_type='modeling_stage_record'; operation=$Operation; last_stage=$stage;
        status=$completion; failure=$failure; stages=$stages; logs=$logs;
        source_sha256=$sourceHash; operation_review_sha256=$reviewHash; input_bindings=$snapshot;
        model_validation='not_assessed'; independent_reload=$(if ($Operation -eq 'inspect') { 'not_assessed_requires_evidence' } else { 'not_run_requires_separate_inspect' });
        authorization_granted=$false; note='Records invocation only; no model pass or future authorization.'} |
        ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $runPath 'stage-record.json') -Encoding UTF8
    if ($locationPushed) { Pop-Location }
}

