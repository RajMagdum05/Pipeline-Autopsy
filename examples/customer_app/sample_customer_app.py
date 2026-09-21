"""
Sample External Customer Application.

Demonstrates a real external customer pipeline integrating with Autopsy strictly via `autopsy_sdk`.
Contains ZERO imports from `autopsy` internal backend modules.

Flow:
Service A (Order Gateway)
    ↓
Service B (Payment Processor) -> Simulates Timeout / GatewayError
    ↓
Service C (Inventory Allocator) -> Propagated Failure
"""
import os
import sys
import time

# Ensure packages/autopsy-sdk is importable
sdk_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../packages/autopsy-sdk"))
if sdk_path not in sys.path:
    sys.path.insert(0, sdk_path)

from autopsy_sdk import Autopsy


def run_customer_pipeline(endpoint: str = "http://localhost:8000", api_key: str = "sk_live_customer_test_key"):
    print("=" * 70)
    print("RUNNING EXTERNAL CUSTOMER APPLICATION VIA AUTOPSY SDK")
    print("=" * 70)

    # 1. Initialize Autopsy SDK Client as an external customer
    autopsy = Autopsy(
        api_key=api_key,
        endpoint=endpoint,
        project_id="proj_ecommerce_prod",
        service_name="ecommerce_checkout_flow",
        environment="production",
    )

    exec_id = autopsy.start_execution()
    print(f"[SDK] Initialized Autopsy SDK for Execution ID: {exec_id}")
    print(f"[SDK] Target OTLP Endpoint: {autopsy.config.get_otlp_endpoint()}")

    # 2. Execute Service A -> Service B -> Service C
    try:
        with autopsy.span("service_a_order_gateway", attributes={"order.id": "ord_9901", "cart.total": 249.99}) as s_a:
            print("[Customer App] Step 1: Processing order ingress in Service A (Order Gateway)...")
            time.sleep(0.05)
            s_a.add_event("order_validated", {"items_count": 3})

            # Service B
            try:
                with autopsy.span("service_b_payment_processor", attributes={"payment.method": "credit_card", "amount": 249.99}) as s_b:
                    print("[Customer App] Step 2: Requesting payment processing in Service B...")
                    time.sleep(0.08)
                    s_b.add_event("contacting_payment_gateway", {"gateway": "stripe_v2"})

                    # Simulate intentional root failure
                    raise TimeoutError("Payment gateway timed out after 5000ms response window")
            except TimeoutError as exc:
                print(f"[Customer App] Service B captured operational failure: {exc}")
                # Service C downstream consequence
                with autopsy.span("service_c_inventory_allocator", attributes={"order.id": "ord_9901"}) as s_c:
                    print("[Customer App] Step 3: Service C aborting allocation due to upstream payment failure...")
                    s_c.set_status_error("Inventory reservation cancelled: Payment processing failed upstream")
                    s_c.add_event("allocation_aborted", {"reason": "payment_failure"})
                    time.sleep(0.02)

    except Exception as general_err:
        print(f"[Customer App] Pipeline terminated with error: {general_err}")

    # 3. Flush buffered telemetry to Autopsy backend
    print("[SDK] Flushing telemetry to Autopsy...")
    flushed = autopsy.flush(timeout_seconds=5.0)
    print(f"[SDK] Telemetry flush completed (success={flushed})")
    return exec_id


if __name__ == "__main__":
    endpoint_url = os.getenv("AUTOPSY_ENDPOINT", "http://localhost:8000")
    run_customer_pipeline(endpoint=endpoint_url)
