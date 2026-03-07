# Sulu Blender Add-on Leaf Pack: Runtime Diagram

```mermaid
flowchart LR
  Artist[Blender user] --> Addon[panels.py + operators.py]
  Addon --> Session[storage.py]
  Addon --> Context[preferences.py + project_context.py]

  Addon --> Submit[submit_operator.py]
  Submit --> SubmitWorker[submit_worker.py]
  SubmitWorker --> Backend[/api/* and /api/farm/*]
  SubmitWorker --> Storage[(R2 / S3)]

  Addon --> Download[download_operator.py]
  Download --> DownloadWorker[download_worker.py]
  DownloadWorker --> Backend
  DownloadWorker --> Storage
```

Primary integration sources:
- `pocketbase_auth.py`
- `utils/request_utils.py`
- `transfers/submit/submit_worker.py`
- `transfers/download/download_worker.py`
