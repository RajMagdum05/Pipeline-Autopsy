"""Command line tools for Pipeline Autopsy."""
import argparse
import json
import sys
from pathlib import Path


def register_file(path, endpoint, key, *, client=None):
    """Register one YAML or JSON manifest and return its HTTP response."""
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("Install autopsy-sdk[cli] to register YAML manifests") from exc
    manifest_path = Path(path)
    content = manifest_path.read_text(encoding="utf-8")
    try:
        if manifest_path.suffix.lower() == ".json":
            manifest = json.loads(content)
            content_type = "application/json"
            body = json.dumps(manifest)
        else:
            manifest = yaml.safe_load(content)
            content_type = "application/yaml"
            body = content
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a YAML or JSON object")
    name, version = manifest.get("pipeline"), manifest.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("Manifest must include string pipeline and version fields")

    owns_client = client is None
    if owns_client:
        import httpx
        client = httpx.Client(timeout=10.0)
    try:
        return client.put(
            f"{endpoint.rstrip('/')}/v1/pipelines/{name}/versions/{version}",
            content=body,
            headers={"Content-Type": content_type, "X-Autopsy-Api-Key": key},
        )
    finally:
        if owns_client:
            client.close()


def main(argv=None, *, client=None):
    parser = argparse.ArgumentParser(prog="autopsy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("register", help="register a pipeline manifest")
    register.add_argument("file")
    register.add_argument("--endpoint", required=True)
    register.add_argument("--key", required=True)
    args = parser.parse_args(argv)

    try:
        response = register_file(args.file, args.endpoint, args.key, client=client)
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        print(f"autopsy: {exc}", file=sys.stderr)
        return 2
    print(response.text)
    return 0 if response.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
