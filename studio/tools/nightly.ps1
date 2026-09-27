<#
Unattended rebuild runner: runs headless Claude sessions ("continue building <code>") subject by subject, and paces
them against the plan's 5-hour usage windows.

usage:
  powershell -ExecutionPolicy Bypass -File _studio\tools\nightly.ps1 [options]

  -Subjects mppo,cs,ds2,om,cf   order to work in (default all five)
  -Modules 1                    modules to finish per subject per pass (an intake or plan session counts toward none)
  -UntilDone                    keep making passes over the subjects until every one is complete (or a whole pass
                                changes nothing); without it the runner makes one pass and stops
  -Model auto|opus|sonnet       auto (default): Opus only where judgement sets the pattern, Sonnet elsewhere (see Pick-Model)
  -Usage buffer|max             buffer (default): keep -BufferPct of every window free for your own use;
                                max: no pacing at all, run until the real limit, sleep to the reset, carry on
  -BufferPct 15                 the share of each window left free in buffer mode
  -Capacity 60                  starting guess of one window, in Opus-minutes; replaced by what the runner measures
  -MaxSessions 4                per subject, per pass
  -StartAt 04:05                optional: wait until this time first (default: start now)
  -Scheduled                    for Task Scheduler (install_task.ps1): exit silently if a runner is already going or
                                every subject is complete, so a repeating trigger costs nothing
  -DryRun                       no Claude calls, no commits; checks the pacing, status and logs

How pacing works:
- Usage is counted in Opus-minutes: session minutes x model weight (Opus 1.0, Sonnet 0.4).
- Window capacity (buffer mode only) = median of the last 5 usages measured at a limit hit (floor 40), else -Capacity.
  Your own use of Claude in the same window lowers those samples, which is why it is a median, not a minimum.
- A session's estimate = 1.25 x the average of past sessions of the same step and model, else a default per step.
- Buffer mode, before each session: if (used in this window + estimate) > capacity x (1 - buffer), sleep to the reset.
- Either mode, if the limit is hit: the reset time is read from Claude's message ("resets 2:10pm"), the runner logs
  a heartbeat every 30 min while it sleeps, logs the wake-up and relaunches the same subject (rebuild_status.py
  picks up the partial work: a module is only "done" once its Practice sets and log line exist).
After every session the subject's git repo gets a checkpoint commit ("auto: ..."), so a bad session can be undone.
Reset times are read in three shapes: "resets 2:10pm", "resets Mon 9am", "resets Sep 28, 9am". If none matches, the wait
falls back to 60 min, growing by 60 min per repeated hit (cap 6 h), and the log says the time was guessed. Hitting the
limit never counts toward giving up (up to 30 waits per session); only real errors do (4 per session).
Crash recovery: while a session runs, _studio\logs\current.json names it. If the runner starts and finds that file, the
last run died mid-session (laptop off, window closed): whatever that session left is committed as "auto: interrupted
session" (so it can be undone), and the subject's next session runs on Opus and is told to run run_all.py first and
repair any half-written file before continuing.
Only one runner at a time: _studio\logs\runner.lock holds the PID.
Logs: _studio\logs\history.md (every session, every run), _studio\logs\<date>\summary.md, run.log, <code>-<n>.txt.
#>
param(
  [string[]]$Subjects = @("mppo", "cs", "ds2", "om", "cf"),
  [int]$Modules = 1,
  [switch]$UntilDone,
  [ValidateSet("auto", "opus", "sonnet")][string]$Model = "auto",
  [ValidateSet("buffer", "max")][string]$Usage = "buffer",
  [int]$BufferPct = 15,
  [double]$Capacity = 60,
  [int]$MaxSessions = 4,
  [string]$StartAt = "",
  [switch]$Scheduled,
  [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$Subjects = @($Subjects | ForEach-Object { $_ -split "," } | Where-Object { $_ })
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Logs = Join-Path $Root "_studio\logs"
New-Item -ItemType Directory -Force $Logs | Out-Null

# ---------- one runner at a time (dry runs use their own lock)
$LockFile = Join-Path $Logs $(if ($DryRun) { "dryrun.lock" } else { "runner.lock" })
if (Test-Path $LockFile) {
  $holder = (Get-Content $LockFile -Raw).Trim()
  if ($holder -and $holder -ne "$PID" -and (Get-Process -Id ([int]$holder) -ErrorAction SilentlyContinue)) {
    if (-not $Scheduled) { Write-Host "another runner is already running (PID $holder, lock $LockFile); stop it first or wait for it to finish" }
    exit $(if ($Scheduled) { 0 } else { 1 })
  }
}
"$PID" | Out-File -Encoding ascii $LockFile

if ($DryRun) {   # dry runs never touch the real logs or pacing state
  $real = Join-Path $Logs "usage.json"; $Logs = Join-Path $Logs "dryrun"
  if (Test-Path $Logs) { Remove-Item -Recurse -Force $Logs }
  New-Item -ItemType Directory -Force $Logs | Out-Null
  if (Test-Path $real) { Copy-Item $real (Join-Path $Logs "usage.json") }
}
$LogDir = Join-Path $Logs (Get-Date -Format "yyyy-MM-dd")
New-Item -ItemType Directory -Force $LogDir | Out-Null
$RunLog = Join-Path $LogDir "run.log"
function Log($m) { $l = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m; $l | Out-File -Append -Encoding utf8 $RunLog; Write-Host $l }

# keep the machine awake while running
Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[W.P]::SetThreadExecutionState([uint32]"0x80000041") | Out-Null

$Weight = @{ "opus" = 1.0; "sonnet" = 0.4 }
$DefaultEst = @{ "intake" = 8; "plan" = 50; "module" = 45; "finish" = 30 }   # Opus-minutes
$Buffer = if ($Usage -eq "max") { 0 } else { $BufferPct / 100 }

# ---------- usage state (persists across runs)
$CurFile = Join-Path $Logs "current.json"      # names the session in flight; still there at startup = the last run died mid-session
$Recover = @{}                                  # subjects whose next session must repair an interrupted one
$UsageFile = Join-Path $Logs "usage.json"
$U = if (Test-Path $UsageFile) { Get-Content $UsageFile -Raw | ConvertFrom-Json } else { $null }
if (-not $U) { $U = [pscustomobject]@{ window_start = $null; window_reset = $null; samples = @(); sessions = @() } }
function Save-Usage { $U | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 $UsageFile }
function Cap {
  $s = @(@($U.samples | Where-Object { $_ -gt 5 }) | Select-Object -Last 5 | Sort-Object)
  if (-not $s.Count) { return $Capacity }
  $med = if ($s.Count % 2) { $s[[int][math]::Floor($s.Count / 2)] } else { ($s[$s.Count / 2 - 1] + $s[$s.Count / 2]) / 2 }
  [math]::Max(40, [math]::Round($med, 1))
}
function Ensure-Window {
  $now = Get-Date
  if (-not $U.window_reset -or $now -ge [datetime]$U.window_reset) {
    $U.window_start = $now.ToString("o"); $U.window_reset = $now.AddHours(5).ToString("o"); Save-Usage
  }
}
function Used {
  $ws = [datetime]$U.window_start
  $x = 0; foreach ($s in $U.sessions) { if ([datetime]$s.end -ge $ws) { $x += [double]$s.units } }; [math]::Round($x, 1)
}
function Estimate($step, $model) {
  $past = @($U.sessions | Where-Object { $_.step -eq $step -and $_.model -eq $model -and $_.ok })
  if ($past.Count) { 1.25 * ($past | Measure-Object -Property units -Average).Average } else { 1.25 * $DefaultEst[$step] * $Weight[$model] }
}
# Reads the reset time from the limit message. Returns @{ time; guessed; note }.
# Shapes: "resets 2:10pm" | "resets Mon 9am" / "resets Monday at 9:00 am" | "resets Sep 28, 9am" / "resets Sep 28 at 9am".
$ResetRx = "(?i)resets?\s+(?:on\s+)?(?:(?<wd>mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+(?:at\s+)?)?(?:(?<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?(?<h>\d{1,2})(?::(?<m>\d{2}))?\s*(?<ap>am|pm)"
function Parse-Reset($text, $hits = 1) {
  $now = Get-Date
  $guess = { $mins = [math]::Min(60 * [math]::Max(1, $hits), 360); @{ time = $now.AddMinutes($mins); guessed = $true; note = "no reset time found in the message; guessing +$mins min" } }
  if ($text -notmatch $ResetRx) { return (& $guess) }
  $g = $matches
  $h = [int]$g['h'] % 12; if ($g['ap'].ToLower() -eq "pm") { $h += 12 }
  $m = if ($g['m']) { [int]$g['m'] } else { 0 }
  try {
    if ($g['mon']) {
      $mo = [array]::IndexOf(@("jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"), $g['mon'].ToLower()) + 1
      $t = (Get-Date -Year $now.Year -Month $mo -Day ([int]$g['day'])).Date.AddHours($h).AddMinutes($m)
      if ($t -le $now) { $t = $t.AddYears(1) }
    } elseif ($g['wd']) {
      $want = @{ mon = 1; tue = 2; wed = 3; thu = 4; fri = 5; sat = 6; sun = 0 }[$g['wd'].ToLower()]
      $t = $now.Date.AddHours($h).AddMinutes($m)
      while ([int]$t.DayOfWeek -ne $want -or $t -le $now) { $t = $t.AddDays(1) }
    } else {
      $t = $now.Date.AddHours($h).AddMinutes($m); if ($t -le $now) { $t = $t.AddDays(1) }
    }
  } catch { return (& $guess) }
  if ($t -gt $now.AddDays(8)) { return (& $guess) }
  @{ time = $t; guessed = $false; note = "reset time read from the message: '$($g[0])'" }
}
function Sleep-Until($t, $why) {
  $t = ([datetime]$t).AddMinutes(3)
  Log "waiting until $($t.ToString('ddd HH:mm')) ($why)"
  if ($DryRun) { Log "still waiting until $($t.ToString('HH:mm')) (dry run: heartbeat)"; Log "awake: resuming"; return }
  $beat = (Get-Date).AddMinutes(30)
  while ((Get-Date) -lt $t) {
    Start-Sleep -Seconds 60
    if ((Get-Date) -ge $beat -and (Get-Date) -lt $t) { Log "still waiting until $($t.ToString('HH:mm'))"; $beat = (Get-Date).AddMinutes(30) }
  }
  Log "awake: resuming"
}

# ---------- status, step and model choice
$env:PYTHONIOENCODING = "utf-8"
function Status($code) { (& python "_studio\tools\rebuild_status.py" $code 2>&1 | Out-String) }
function Done-Count($s) { @(($s -split "`n") | Where-Object { $_ -match "^\s+\[x\]" }).Count }
function Step($s) {
  $n = (($s -split "`n") | Where-Object { $_ -like "NEXT:*" }) -join " "
  if ($n -match "step 0") { "intake" } elseif ($n -match "step 1") { "plan" } elseif ($n -match "step 2") { "module" }
  elseif ($n -match "step 3") { "finish" } else { "complete" }
}
function Tests($code) {
  $t = (& python "_studio\tests\run_all.py" $code 2>&1 | Out-String)
  $t | Out-File -Encoding utf8 (Join-Path $LogDir "$code-tests.txt")
  if ($t -match "skeleton") { "skeleton" } elseif ($t -match "ALL OK") { "PASS" } else { "FAIL" }
}
function Modules($s) { (($s -split "`n") | ForEach-Object { if ($_ -match "^\s+\[(x|~| )\]\s+(\S+)") { $matches[2] + ":" + @{"x"="done"; "~"="started"; " "="todo"}[$matches[1]] } }) -join " " }
# auto: Opus where judgement sets the pattern (the plan, a subject's first module, the finish: examiner pattern,
# errata, Revision), or after a Sonnet session that failed tests or changed nothing; Sonnet for intake and later modules.
function Pick-Model($code, $step, $status) {
  if ($Model -ne "auto") { return $Model }
  $last = @($U.sessions | Where-Object { $_.subject -eq $code }) | Select-Object -Last 1
  if ($Recover[$code]) { return "opus" }
  if ($last -and $last.model -eq "sonnet" -and ($last.tests -eq "FAIL" -or $last.progress -eq "no change")) { return "opus" }
  switch ($step) {
    "intake" { "sonnet" } "plan" { "opus" } "finish" { "opus" }
    "module" { if ((Done-Count $status) -eq 0) { "opus" } else { "sonnet" } }
    default { "sonnet" }
  }
}
# checkpoint: one commit in the subject's own repo after every session that changed files
function Checkpoint($code, $msg) {
  if ($DryRun -or -not (Test-Path (Join-Path $code ".git"))) { return }
  $dirty = & git -C $code status --porcelain 2>$null
  if (-not $dirty) { return }
  & git -C $code add -A 2>&1 | Out-Null
  & git -C $code commit -q -m $msg -m "Co-Authored-By: Claude <noreply@anthropic.com>" 2>&1 | Out-Null
  Log "${code}: checkpoint commit $((& git -C $code rev-parse --short HEAD 2>$null)) ($msg)"
}

# ---------- logs
$History = Join-Path $Logs "history.md"
if (-not (Test-Path $History)) {
  "# Rebuild runs (all nights)`n`n| date | start | end | min | subject | session | step | model | units | window used/cap | claude | progress | tests | modules after | next step |`n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|" | Out-File -Encoding utf8 $History
}
$hdr = "| date | start | end | min | subject | session | step | model | units | window used/cap | claude | progress | tests | modules after | next step |"
if (-not ((Get-Content $History -Raw) -match [regex]::Escape($hdr))) {
  "`n## From $(Get-Date -Format 'yyyy-MM-dd'): paced runner (units = Opus-minutes)`n`n$hdr`n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|" | Out-File -Append -Encoding utf8 $History
}
$Rows = @()
function Hist($r) { $script:Rows += $r; $r | Out-File -Append -Encoding utf8 $History }

$prompt0 = "continue building {0}. This is an unattended run: nobody can answer questions. Follow term2/CLAUDE.md, section Rebuilding a subject, exactly. Where a judgement call is needed, take it and record it in the {0}/CLAUDE.md log for review. Do the step rebuild_status.py names, finish it completely, then stop with the usual short report. A module counts as done only when its digest, lessons, Practice sets (with a module: field) and a passing run_all.py exist and the {0}/CLAUDE.md log has a line 'rebuild: <module-id> done ...'; if rebuild_status.py shows a module as started with items missing, complete exactly those first."
$promptFix = " The last run of python _studio/tests/run_all.py {0} FAILED: run it first and fix every failure before anything else."
$promptRecover = " The previous session on {0} was cut off (the machine or the runner stopped mid-session), so files may be half-written. Before anything else: run git -C {0} status and git -C {0} log -3 to see what it left, run python _studio/tests/run_all.py {0}, and repair every half-written or invalid file (truncated YAML, missing fields, a digest that stops mid-way) or finish it. Then continue with the step rebuild_status.py names."

try {
  if ($StartAt) {
    $when = [datetime]::ParseExact($StartAt, "HH:mm", $null); if ($when -lt (Get-Date)) { $when = $when.AddDays(1) }
    Sleep-Until $when.AddMinutes(-3) "start time"
  }
  if ($Scheduled -and -not @($Subjects | Where-Object { (Step (Status $_)) -ne "complete" }).Count) { exit 0 }   # nothing left to do: stay silent

  # crash recovery: a leftover marker means the last run died while a session was running
  if (Test-Path $CurFile) {
    $c = $null; try { $c = Get-Content $CurFile -Raw | ConvertFrom-Json } catch {}
    Remove-Item -Force $CurFile
    if ($c -and $c.subject) {
      Log "RECOVERY: the last run stopped mid-session ($($c.subject), $($c.step) on $($c.model), started $($c.start)); its partial work is saved as a commit and the next $($c.subject) session repairs it"
      $Recover[$c.subject] = $true
      Checkpoint $c.subject "auto: interrupted session ($($c.step) on $($c.model)); partial work saved for review"
    }
  }
  Log "runner started (PID $PID): $($Subjects -join ', ') | model $Model | usage $Usage$(if ($Usage -eq 'buffer') { " ($BufferPct% free, capacity $(Cap) Opus-min/window)" }) | $Modules module(s) per subject per pass$(if ($UntilDone) { ' | until done' })"

  $pass = 0
  do {
    $pass++; $passChanged = $false
    if ($UntilDone) { Log "##### pass $pass" }
    foreach ($code in $Subjects) {
      Log "=== $code"
      $s0 = Status $code
      $target = (Done-Count $s0) + $Modules
      $same = 0
      for ($n = 1; $n -le $MaxSessions; $n++) {
        $before = Status $code
        $step = Step $before
        if ($step -eq "complete") { Log "${code}: rebuild complete"; break }
        if ((Done-Count $before) -ge $target) { Log "${code}: $Modules module(s) finished this pass; next subject"; break }
        $mdl = Pick-Model $code $step $before
        $est = [math]::Round((Estimate $step $mdl), 1)

        # pace (buffer mode only): will this session fit in the current window with the buffer kept free?
        Ensure-Window
        $cap = Cap; $limit = [math]::Round($cap * (1 - $Buffer), 1)
        if ($Usage -eq "buffer" -and (Used) + $est -gt $limit -and (Used) -gt 0) {
          Sleep-Until $U.window_reset "window $(Used)/$cap used; next $step on $mdl needs ~$est, limit $limit"
          if ($DryRun) { $U.window_reset = (Get-Date).ToString("o") }
          Ensure-Window
        }

        $lastRun = @($U.sessions | Where-Object { $_.subject -eq $code -and $_.ok }) | Select-Object -Last 1
        $prompt = ($prompt0 -f $code) + $(if ($lastRun -and $lastRun.tests -eq "FAIL") { $promptFix -f $code } else { "" }) + $(if ($Recover[$code]) { $promptRecover -f $code } else { "" })
        $out = Join-Path $LogDir "$code-$n.txt"
        $t0 = Get-Date; $ok = $false; $errs = 0; $limitHits = 0; $lastMins = 0; $j = $null
        Log "$code session ${n}: $step on $mdl (est ~$est, window $(Used)$(if ($Usage -eq 'buffer') { "/$cap" }))$(if ($Recover[$code]) { ' [repairing an interrupted session first]' } elseif ($prompt -ne ($prompt0 -f $code)) { ' [fix failing tests first]' })"
        if (-not $DryRun) { [pscustomobject]@{ subject = $code; step = $step; model = $mdl; start = $t0.ToString("o"); pid = $PID } | ConvertTo-Json | Out-File -Encoding utf8 $CurFile }
        while (-not $ok -and $errs -lt 4 -and $limitHits -lt 30) {
          if ($DryRun) { Log "$code session $n try $($errs + $limitHits + 1): launching claude (dry run)"; "dry run: $step on $mdl" | Out-File -Encoding utf8 $out; $ok = $true; break }
          Log "$code session $n try $($errs + $limitHits + 1): launching claude"
          $ts = Get-Date
          $raw = & claude -p $prompt --model $mdl --output-format json --permission-mode bypassPermissions 2>&1 | Out-String
          $exit = $LASTEXITCODE
          $j = $null; try { $j = $raw | ConvertFrom-Json } catch {}
          $text = if ($j -and $j.result) { $j.result } else { $raw }
          $text | Out-File -Encoding utf8 $out
          $mins = ((Get-Date) - $ts).TotalMinutes; $lastMins = $mins
          $isLimit = ($raw -match "hit your .{0,20}limit|usage limit|limit reached|limit will reset") -and ($exit -ne 0 -or ($j -and $j.is_error))
          if ($isLimit) {
            $limitHits++
            $U.samples = @($U.samples) + @([math]::Round((Used) + $mins * $Weight[$mdl], 1))
            $pr = Parse-Reset $raw $limitHits
            $reset = $pr.time
            $U.window_reset = $reset.ToString("o"); Save-Usage
            Log "$code session $n hit the limit after $([int]$mins) min ($(($text -split "`n" | Select-Object -Last 1).Trim()))"
            Log "$($pr.note) -> resuming $($reset.ToString('ddd HH:mm'))$(if ($pr.guessed) { ' (GUESSED: check the message in ' + $out + ')' })"
            $U.sessions = @($U.sessions) + @([pscustomobject]@{ subject = $code; step = $step; model = $mdl; start = $ts.ToString("o"); end = (Get-Date).ToString("o"); units = [math]::Round($mins * $Weight[$mdl], 1); ok = $false; tests = ""; progress = "" })
            Save-Usage
            Checkpoint $code "auto: $step (partial, cut off by the usage limit; $mdl)"
            Sleep-Until $reset "usage reset"
            Ensure-Window
          } elseif ($exit -eq 0) { $ok = $true }
          else { $errs++; Log "$code session $n error $errs/4 (exit $exit): $(($text -split "`n" | Select-Object -Last 2) -join ' '); retrying in 5 min"; Start-Sleep -Seconds 300 }
        }
        if (Test-Path $CurFile) { Remove-Item -Force $CurFile }   # the session ended normally (or gave up): not an interruption
        $Recover.Remove($code)
        $mins = ((Get-Date) - $t0).TotalMinutes
        $after = Status $code
        $tests = if ($DryRun) { "skipped" } else { Tests $code }
        $prog = if ($after -eq $before) { "no change" } else { "changed" }
        if ($prog -eq "changed") { $passChanged = $true }
        $units = if ($DryRun) { $est } else { [math]::Round($lastMins * $Weight[$mdl], 1) }   # the final attempt only: earlier cut-off attempts were already booked, and waiting is not usage
        if ($ok) {
          $U.sessions = @($U.sessions) + @([pscustomobject]@{ subject = $code; step = $step; model = $mdl; start = $t0.ToString("o"); end = (Get-Date).ToString("o"); units = $units; ok = $true; tests = $tests; progress = $prog })
          Save-Usage
        }
        $nextAfter = (($after -split "`n" | Where-Object { $_ -like "NEXT:*" }) -join " ") -replace "\|", "/"
        Checkpoint $code "auto: $step on $mdl, tests $tests; $($nextAfter.Trim())"
        $cost = if ($j -and $j.total_cost_usd) { " ($([math]::Round($j.total_cost_usd, 2)) USD-eq)" } else { "" }
        Hist ("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8}{9} | {10}/{11} | {12} | {13} | {14} | {15} | {16} |" -f (Get-Date -Format "yyyy-MM-dd"), $t0.ToString("HH:mm"), (Get-Date -Format "HH:mm"),
          [int]$mins, $code, $n, $step, $mdl, $units, $cost, (Used), $(if ($Usage -eq 'buffer') { Cap } else { "-" }), $(if ($ok) { "ok" } else { "GAVE UP" }), $prog, $tests, (Modules $after), $nextAfter.Trim())
        if (-not $ok) { Log "$code session $n gave up; next subject"; break }
        Log ("$code session $n done in $([int]$mins) min (tests: $tests, $prog). Status:`n" + $after.Trim())
        if ($prog -eq "no change") { $same++ } else { $same = 0 }
        if ($same -ge 2) { Log "${code}: two sessions with no change; next subject"; break }
      }
    }
    $left = @($Subjects | Where-Object { (Step (Status $_)) -ne "complete" })
    if ($UntilDone -and $left.Count -and -not $passChanged) { Log "pass $pass changed nothing; stopping (check the session reports)" }
    if ($DryRun -and $UntilDone) { Log "dry run: one pass only"; break }
  } while ($UntilDone -and $left.Count -and $passChanged)
  if (-not $left.Count) { Log "all subjects complete" }
  Log "runner finished"

  # summary for this run
  $sum = @("# Run of $(Get-Date -Format 'yyyy-MM-dd')", "", "Finished $(Get-Date -Format 'HH:mm'). Model: $Model. Usage: $Usage. Passes: $pass.", "",
    "## Sessions", "", "| date | start | end | min | subject | session | step | model | units | window used/cap | claude | progress | tests | modules after | next step |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|") + $Rows
  $sum += @("", "## Where each subject stands", "")
  foreach ($code in $Subjects) { $sum += @("``````", (Status $code).Trim(), "``````", "") }
  $sum += @("Per-session reports: ``<subject>-<n>.txt``; tests: ``<subject>-tests.txt``; timeline: ``run.log``; all runs: ``..\history.md``; pacing state: ``..\usage.json``.",
    "Judgement calls made during the run are in each subject's ``CLAUDE.md`` log; every session is a commit in the subject's repo (``git log``).")
  $sum | Out-File -Encoding utf8 (Join-Path $LogDir "summary.md")
  Log "summary -> $(Join-Path $LogDir 'summary.md')"
}
finally {
  if ((Test-Path $LockFile) -and ((Get-Content $LockFile -Raw).Trim() -eq "$PID")) { Remove-Item -Force $LockFile }
  [W.P]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
}
