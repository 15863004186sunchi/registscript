import json
import sys
import os
from datetime import datetime

REQUIRED_FIELDS = ["id_token", "access_token", "account_id", "email", "type", "expired"]

def validate_token_file(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error: Failed to parse JSON: {e}")
        return False

    missing = [k for k in REQUIRED_FIELDS if not str(data.get(k, "")).strip()]
    if missing:
        print(f"FAILED: Missing or empty fields: {missing}")
        return False

    # Check account_id is not the default fallback value
    if data["account_id"] == "2ab60b7c-6e4d-4a3b-a012-b7d522f5b149":
        print("WARNING: account_id is using the default fallback value. This might cause issues in some panels.")

    # Check expiration date format
    try:
        datetime.strptime(data["expired"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        print(f"WARNING: 'expired' field ({data['expired']}) is not in expected format YYYY-MM-DDTHH:MM:SSZ")

    print(f"SUCCESS: Token file {os.path.basename(file_path)} is valid.")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_token.py <path_to_token_json>")
        sys.exit(1)
    
    success = validate_token_file(sys.argv[1])
    sys.exit(0 if success else 1)
