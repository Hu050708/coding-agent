# Independent demo evaluation

Keep this directory outside the workspace handed to ClearLoop. It validates a
candidate copy of `examples/date_boundary_bug` with:

```powershell
python evaluation/verify_date_boundary.py PATH_TO_CANDIDATE
```

Acceptance requires the candidate's own tests to pass, at least one additional
collected test beyond the four-test baseline, correct end-of-day behavior, and
unchanged unfiltered CLI output.

The evaluator launches the candidate's tests and CLI as local subprocesses. It
removes API-key-like environment variables and avoids writing caches into the
candidate, but it is not an OS sandbox. Run it only on a trusted, disposable
demo copy—not on arbitrary downloaded code.
