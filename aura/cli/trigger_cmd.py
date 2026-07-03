import typer
import json
import os
import glob
from orchestrator.webhook_listener import start_listener

trigger_app = typer.Typer(help="Manage CI/CD webhook triggers")

@trigger_app.command("listen")
def listen(host: str = "0.0.0.0", port: int = 8099):
    """Start the inbound webhook listener for CI/CD integrations."""
    start_listener(host, port)

@trigger_app.command("process")
def process():
    """Process pending webhook triggers and queue them for execution."""
    trigger_dir = "triggers/pending"
    if not os.path.exists(trigger_dir):
        print("No pending triggers found.")
        return
        
    files = glob.glob(os.path.join(trigger_dir, "*.json"))
    if not files:
        print("No pending triggers found.")
        return
        
    # Debug Fix: Load and sort by received_at to ensure strict FIFO processing
    records = []
    for file_path in files:
        try:
            with open(file_path, 'r') as f:
                record = json.load(f)
                record["_file_path"] = file_path
                records.append(record)
        except Exception as e:
            print(f"[AURA] Warning: Failed to read {file_path}: {e}")
            
    records.sort(key=lambda x: x.get("received_at", ""))
    
    for record in records:
        file_path = record.pop("_file_path")
        print(f"[AURA] Processing trigger {record['trigger_id']} (Received: {record['received_at']})...")
        
        # In Phase 17, this will push to a proper task queue. 
        # For Phase 16, we acknowledge and archive.
        # from orchestrator.run_engine import execute_test
        # execute_test(record['payload'])
        
        os.makedirs("triggers/processed", exist_ok=True)
        os.replace(file_path, os.path.join("triggers/processed", os.path.basename(file_path)))
        print(f"[AURA] Trigger {record['trigger_id']} processed and archived.")