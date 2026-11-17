"""Run a tiny fetch → summarize → publish pipeline through autopsy-sdk."""
import argparse
import os

import autopsy_sdk as autopsy


def run(fault, endpoint, api_key):
    os.environ["AUTOPSY_EVIDENCE_LEVEL"] = "E2"
    os.environ["AUTOPSY_EVIDENCE_KINDS"] = "page,summary,post"
    traces_endpoint = f"{endpoint.rstrip('/')}/v1/traces"
    autopsy.configure(
        service_name="toy-summarizer",
        endpoint=endpoint,
        extra_otlp_endpoint=traces_endpoint,
        api_key=api_key,
        evidence_kinds=["page", "summary", "post"],
    )
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    run_id = f"toy_{'healthy' if fault == 'none' else fault}"
    try:
        with autopsy.run(run_id=run_id) as current_run:
            with autopsy.stage("fetch") as stage:
                body = "A compact example body with useful detail." if fault != "short_body" else "too short"
                page = {"title": "Example", "body": body}
                page_id = stage.record_artifact("page", page)
                if fault == "short_body":
                    stage.check("schema.minLength", kind="schema", result="fail", action="continued",
                                target=page_id, field="body", observed=str(len(body)), expected=">=20")

            with autopsy.stage("summarize", inputs=[page_id]) as stage:
                summary = {"text": f"Summary: {body}"}
                summary_id = stage.record_artifact("summary", summary)

            with autopsy.stage("publish", inputs=[summary_id]) as stage:
                if fault == "publish_timeout":
                    raise TimeoutError("toy publisher timed out")
                stage.record_artifact("post", {"published": True, "summary": summary["text"]})

            current_run.set_outcome("success")
    except TimeoutError:
        if fault != "publish_timeout":
            raise
    finally:
        autopsy.flush(timeout=10.0)
        autopsy.shutdown(timeout=10.0)
    print(f"submitted run {run_id} (fault={fault}) to {endpoint}")
    return run_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault", choices=("none", "short_body", "publish_timeout"), default="none")
    parser.add_argument("--endpoint", default=os.getenv("AUTOPSY_ENDPOINT", "http://127.0.0.1:8080"))
    parser.add_argument("--key", default=os.getenv("AUTOPSY_API_KEY"))
    args = parser.parse_args()
    run(args.fault, args.endpoint, args.key)


if __name__ == "__main__":
    main()
