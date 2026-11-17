# Toy pipeline: fetch → summarize → publish

This small producer exercises the public SDK without depending on the insurance application.
It sends OTLP spans and opted-in toy evidence to a running Autopsy instance.

From the repository root, install the SDK and register its manifest once:

```powershell
python -m pip install -e .\autopsy-sdk[configure,upload]
$env:AUTOPSY_ENDPOINT = 'http://127.0.0.1:8080'
$env:AUTOPSY_API_KEY = 'your-local-autopsy-key'
autopsy register .\pipeline-autopsy\examples\toy_pipeline\manifest.yaml --endpoint $env:AUTOPSY_ENDPOINT --key $env:AUTOPSY_API_KEY
python .\pipeline-autopsy\examples\toy_pipeline\run.py --fault none
python .\pipeline-autopsy\examples\toy_pipeline\run.py --fault short_body
python .\pipeline-autopsy\examples\toy_pipeline\run.py --fault publish_timeout
```

The example uses synthetic content and enables E2 only for the three allow-listed toy artifact kinds. `short_body` supplies a page that violates the manifest's minimum body length. `publish_timeout` raises a timeout in the publish stage. Each invocation uses a stable run ID so its trace is easy to find in the local Autopsy UI/API.

To record an opt-in local case for replay, set `AUTOPSY_RECORD_DIR` to a directory. Ingest writes `trace.json`, `manifest.yaml`, and a draft `expected.yaml`; accepted E2 artifact uploads are saved under `artifacts/`. Review the draft expectation before using a recording as an L1 case.
