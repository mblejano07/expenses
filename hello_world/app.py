import json
import boto3
import base64
import uuid
from datetime import datetime
from multipart import MultipartParser
from io import BytesIO

FAKE_DB = {}  # for testing purposes only
ROUTES = {}

def route(path, method):
    def decorator(func):
        ROUTES[(path, method)] = func
        return func
    return decorator

s3 = boto3.client("s3")
BUCKET_NAME = "your-bucket-name"  # Replace this when ready

def parse_multipart(event):
    content_type = event["headers"].get("Content-Type") or event["headers"].get("content-type")
    body_bytes = base64.b64decode(event["body"])
    parser = MultipartParser(BytesIO(body_bytes), content_type)

    result = {}
    file_data = None

    for part in parser.parts():
        if part.filename:
            file_data = {
                "filename": part.filename,
                "content": part.file,
            }
        else:
            result[part.name] = part.text

    return result, file_data

@route("/invoices", "POST")
def create_invoice_handler(event):
    try:
        content_type = event["headers"].get("Content-Type") or event["headers"].get("content-type")

        if content_type.startswith("multipart/form-data"):
            body, file_data = parse_multipart(event)

            if file_data:
                file_key = f"invoices/{uuid.uuid4()}_{file_data['filename']}"
                s3.upload_fileobj(file_data["content"], BUCKET_NAME, file_key)
                body["file_url"] = f"https://{BUCKET_NAME}.s3.amazonaws.com/{file_key}"
            else:
                body["file_url"] = "no-file-uploaded"

        elif content_type.startswith("application/json"):
            body = json.loads(event.get("body", "{}"))
            body["file_url"] = "no-file-uploaded"
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Unsupported Content-Type"})
            }

        required_fields = [
            "reference_id", "company_name", "tin", "invoice_number", "transaction_date",
            "items", "encoder", "payee", "payee_account", "approver"
        ]
        for field in required_fields:
            if field not in body:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": f"Missing field: {field}"})
                }

        items = json.loads(body["items"]) if isinstance(body["items"], str) else body["items"]
        for item in items:
            for f in ["id", "particulars", "project_class", "account", "vatable", "amount"]:
                if f not in item:
                    return {
                        "statusCode": 400,
                        "body": json.dumps({"error": f"Missing item field: {f}"})
                    }

        reference_id = body["reference_id"]
        if reference_id in FAKE_DB:
            return {
                "statusCode": 409,
                "body": json.dumps({"error": "Invoice already exists"})
            }

        invoice_data = {
            "reference_id": reference_id,
            "company_name": body["company_name"],
            "tin": body["tin"],
            "invoice_number": body["invoice_number"],
            "transaction_date": body["transaction_date"],
            "items": items,
            "encoder": body["encoder"],
            "payee": body["payee"],
            "payee_account": body["payee_account"],
            "approver": body["approver"],
            "file_url": body.get("file_url", "no-file-uploaded"),
            "encoding_date": datetime.utcnow().isoformat(),
            "status": "Pending"
        }

        FAKE_DB[reference_id] = invoice_data

        return {
            "statusCode": 201,
            "body": json.dumps({"message": "Invoice created", "data": invoice_data})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

@route("/invoices", "GET")
def get_all_invoices(event):
    invoices = list(FAKE_DB.values())
    return {
        "statusCode": 200,
        "body": json.dumps(invoices),
        "headers": {"Content-Type": "application/json"},
    }

@route("/invoices/{reference_id}", "GET")
def get_invoice_handler(event):
    reference_id = event["pathParameters"]["reference_id"]
    invoice = FAKE_DB.get(reference_id)

    if invoice:
        return {
            "statusCode": 200,
            "body": json.dumps(invoice)
        }
    else:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Invoice not found"})
        }

@route("/invoices/{reference_id}", "PUT")
def update_invoice_handler(event):
    reference_id = event["pathParameters"]["reference_id"]
    body = json.loads(event.get("body", "{}"))

    if reference_id not in FAKE_DB:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Invoice not found"})
        }

    allowed_fields = ["company_name", "tin", "transaction_date", "items"]
    updated_fields = {key: value for key, value in body.items() if key in allowed_fields}

    if not updated_fields:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No valid fields to update"})
        }

    FAKE_DB[reference_id].update(updated_fields)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Invoice updated",
            "data": FAKE_DB[reference_id]
        })
    }

@route("/invoices/{reference_id}", "DELETE")
def delete_invoice_handler(event):
    reference_id = event["pathParameters"]["reference_id"]

    if reference_id in FAKE_DB:
        del FAKE_DB[reference_id]
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Invoice deleted"})
        }
    else:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Invoice not found"})
        }

@route("/invoices/{reference_id}/items", "POST")
def add_item_to_invoice(event):
    reference_id = event["pathParameters"]["reference_id"]
    body = json.loads(event.get("body", "{}"))

    required_fields = ["id", "particulars", "project_class", "account", "vatable", "amount"]
    for field in required_fields:
        if field not in body:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Missing item field: {field}"})
            }

    if reference_id not in FAKE_DB:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Invoice not found"})
        }

    FAKE_DB[reference_id]["items"].append(body)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Item added",
            "data": body
        })
    }

@route("/invoices/{reference_id}/items/{item_id}", "DELETE")
def delete_item_from_invoice(event):
    reference_id = event["pathParameters"]["reference_id"]
    item_id = event["pathParameters"]["item_id"]

    if reference_id not in FAKE_DB:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Invoice not found"})
        }

    original_items = FAKE_DB[reference_id]["items"]
    updated_items = [item for item in original_items if str(item.get("id")) != item_id]

    if len(updated_items) == len(original_items):
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Item not found"})
        }

    FAKE_DB[reference_id]["items"] = updated_items

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Item {item_id} deleted"})
    }

def lambda_handler(event, context):
    path = event.get("path")
    method = event.get("httpMethod")
    
    # First, try to get exact match
    handler = ROUTES.get((path, method))
    if handler:
        return handler(event)

    # Try to match dynamic routes like /invoices/{reference_id}
    for (route_path, route_method), handler in ROUTES.items():
        if route_method != method:
            continue

        route_parts = route_path.strip("/").split("/")
        path_parts = path.strip("/").split("/")

        if len(route_parts) != len(path_parts):
            continue

        path_params = {}
        matched = True
        for route_part, path_part in zip(route_parts, path_parts):
            if route_part.startswith("{") and route_part.endswith("}"):
                key = route_part[1:-1]
                path_params[key] = path_part
            elif route_part != path_part:
                matched = False
                break

        if matched:
            event["pathParameters"] = path_params
            return handler(event)

    return {"statusCode": 404, "body": "Not Found"}
