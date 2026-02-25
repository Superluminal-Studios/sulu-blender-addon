# Blender Addon Leaf Pack: Runtime Diagram

```mermaid
flowchart LR
  Blender[Blender UI + addon] --> Auth[auth operators]
  Auth --> PB[/api/* PocketBase]

  Blender --> SubmitOp[submit operator]
  SubmitOp --> SubmitWorker[submit_worker.py subprocess]
  SubmitWorker --> Farm[/farm/{org}/api/*]
  SubmitWorker --> R2[(Object storage / R2)]

  Blender --> DownloadOp[download operator]
  DownloadOp --> DownloadWorker[download_worker.py subprocess]
  DownloadWorker --> Farm
  DownloadWorker --> R2
```

Detailed architecture reference: `../../ARCHITECTURE.md`.
