# Production architecture notes

Before mass usage, the analyser should run with:

- Persistent job records outside process memory
- Object storage for reports, clips and JSON outputs
- Queue-ready job states: queued, processing, retrying, complete, failed
- Usage limits for video length, concurrent jobs and daily jobs
- Evidence quality scoring so weak analysis produces a shorter report
- Engine version metadata on every result
- Observability for download, frame extraction, OpenAI calls and report generation

Recommended runtime path:

```text
Frontend -> API -> Job record -> Worker -> Object storage -> Report record
```

Recommended stored output per job:

```text
job status
analysis engine version
prompt version
model version
match facts
match evidence
classified events
tactical sequences
momentum phases
report markdown/html
clip references
```
