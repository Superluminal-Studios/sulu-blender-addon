# Blender Addon Leaf Pack: Runbook

## Local dev loop

1. Install addon in Blender from this repo source.
2. Configure backend/farm constants for target environment.
3. Test login, project list, submit (ZIP and PROJECT), and download flows.

## Test suite

```bash
python3 -m pytest tests -v
```

## Manual smoke checklist

- Password login succeeds.
- Browser login handshake succeeds.
- Projects and jobs load for target org.
- Submit pipeline completes all stages and registers job.
- Download worker syncs outputs for selected job.

Escalation:
1. Addon team verifies operator/worker logs.
2. Backend team verifies app-host auth/project endpoints.
3. Queue team verifies farm route/session state.
