import json
import boto3
import base64
import uuid
from io import BytesIO
from datetime import datetime
from decimal import Decimal
from requests_toolbelt.multipart import decoder

ROUTES = {}

def route(path, method):
    def decorator(func):
        ROUTES[(path, method)] = func
        return func
    return decorator

def make_response(status_code, body, headers=None):
    if headers is None:
        headers = {"Content-Type": "application/json"}
    if not isinstance(body, str):
        body = json.dumps(body)
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": body
    }

# Local S3 client
s3 = boto3.client(
    "s3",
    region_name="us-east-1",
    endpoint_url="http://host.docker.internal:4566",
    aws_access_key_id="test",
    aws_secret_access_key="test"
)
BUCKET_NAME = "my-bucket"

# Local DynamoDB client
dynamodb = boto3.resource(
    "dynamodb",
    endpoint_url="http://host.docker.internal:8000",
    region_name="us-east-1",
    aws_access_key_id="test",
    aws_secret_access_key="test"
)
table = dynamodb.Table("Invoices")

def parse_multipart(event):
    """Parse multipart/form-data from API Gateway proxy event using requests-toolbelt."""
    form_data = {}
    file_data = None

    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    content_type = headers.get("content-type")
    
    if not content_type or not content_type.startswith("multipart/form-data"):
        return form_data, file_data

    if event.get("isBase64Encoded"):
        body_bytes = base64.b64decode(event["body"])
    else:
        body_bytes = event["body"].encode("utf-8")

    decoded = decoder.MultipartDecoder(body_bytes, content_type)

    for part in decoded.parts:
        content_disposition_header = part.headers.get(b"Content-Disposition", b"")
        if b"filename" in content_disposition_header:
            filename_bytes = content_disposition_header.split(b"filename=")[1].strip(b'"')
            file_data = {
                "filename": filename_bytes.decode("utf-8", "ignore"),
                "content": part.content
            }
        else:
            name_bytes = content_disposition_header.split(b"name=")[1].strip(b'"')
            try:
                form_data[name_bytes.decode("utf-8")] = part.content.decode("utf-8")
            except UnicodeDecodeError:
                form_data[name_bytes.decode("utf-8")] = part.content.decode("latin-1")

    return form_data, file_data

def decimal_to_float(obj):
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

@route("/invoices", "POST")
def create_invoice_handler(event):
    try:
        content_type = event["headers"].get("Content-Type") or event["headers"].get("content-type")

        if content_type.startswith("multipart/form-data"):
            body, file_data = parse_multipart(event)

            if file_data:
                file_obj = BytesIO(file_data["content"])
                file_key = f"invoices/{uuid.uuid4()}_{file_data['filename']}"
                s3.upload_fileobj(file_obj, BUCKET_NAME, file_key)
                body["file_url"] = f"http://localhost:4566/{BUCKET_NAME}/{file_key}"
            else:
                body["file_url"] = "no-file-uploaded"

        elif content_type.startswith("application/json"):
            body = json.loads(event.get("body", "{}"))
            body["file_url"] = "no-file-uploaded"
        else:
            return make_response(400, {"error": "Unsupported Content-Type"})

        required_fields = [
            "reference_id", "company_name", "tin", "invoice_number", "transaction_date",
            "items", "encoder", "payee", "payee_account", "approver"
        ]
        for field in required_fields:
            if field not in body:
                return make_response(400, {"error": f"Missing field: {field}"})

        items = json.loads(body["items"]) if isinstance(body["items"], str) else body["items"]
        for item in items:
            for f in ["id", "particulars", "project_class", "account", "vatable", "amount"]:
                if f not in item:
                    return make_response(400, {"error": f"Missing item field: {f}"})

        existing = table.get_item(Key={"reference_id": body["reference_id"]})
        if "Item" in existing:
            return make_response(409, {"error": "Invoice already exists"})

        invoice_data = {
            "reference_id": body["reference_id"],
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

        table.put_item(Item=invoice_data)
        return make_response(201, {"message": "Invoice created", "data": invoice_data})

    except Exception as e:
        return make_response(500, {"error": str(e)})

@route("/invoices", "GET")
def get_all_invoices(event):
    try:
        response = table.scan()
        invoices = [decimal_to_float(item) for item in response.get("Items", [])]
        return make_response(200, invoices)
    except Exception as e:
        return make_response(500, {"error": str(e)})

@route("/invoices/{reference_id}", "GET")
def get_invoice_handler(event):
    try:
        reference_id = event["pathParameters"]["reference_id"]
        response = table.get_item(Key={"reference_id": reference_id})
        if "Item" in response:
            return make_response(200, decimal_to_float(response["Item"]))
        return make_response(404, {"error": "Invoice not found"})
    except Exception as e:
        return make_response(500, {"error": str(e)})

@route("/invoices/{reference_id}", "PUT")
def update_invoice_handler(event):
    try:
        reference_id = event["pathParameters"]["reference_id"]
        body = json.loads(event.get("body", "{}"))
        allowed_fields = ["company_name", "tin", "transaction_date", "items"]

        response = table.get_item(Key={"reference_id": reference_id})
        if "Item" not in response:
            return make_response(404, {"error": "Invoice not found"})

        update_expr = []
        expr_attr_values = {}
        for field in allowed_fields:
            if field in body:
                update_expr.append(f"{field} = :{field}")
                expr_attr_values[f":{field}"] = body[field]

        if not update_expr:
            return make_response(400, {"error": "No valid fields to update"})

        table.update_item(
            Key={"reference_id": reference_id},
            UpdateExpression="SET " + ", ".join(update_expr),
            ExpressionAttributeValues=expr_attr_values
        )

        return make_response(200, {"message": "Invoice updated"})
    except Exception as e:
        return make_response(500, {"error": str(e)})

@route("/invoices/{reference_id}", "DELETE")
def delete_invoice_handler(event):
    try:
        reference_id = event["pathParameters"]["reference_id"]
        table.delete_item(Key={"reference_id": reference_id})
        return make_response(200, {"message": "Invoice deleted"})
    except Exception as e:
        return make_response(500, {"error": str(e)})

@route("/invoices/{reference_id}/items", "POST")
def add_item_to_invoice(event):
    try:
        reference_id = event["pathParameters"]["reference_id"]
        body = json.loads(event.get("body", "{}"))
        required_fields = ["id", "particulars", "project_class", "account", "vatable", "amount"]

        for field in required_fields:
            if field not in body:
                return make_response(400, {"error": f"Missing item field: {field}"})

        invoice = table.get_item(Key={"reference_id": reference_id})
        if "Item" not in invoice:
            return make_response(404, {"error": "Invoice not found"})

        items = invoice["Item"].get("items", [])
        items.append(body)

        table.update_item(
            Key={"reference_id": reference_id},
            UpdateExpression="SET items = :items",
            ExpressionAttributeValues={":items": items}
        )

        return make_response(200, {"message": "Item added", "data": body})
    except Exception as e:
        return make_response(500, {"error": str(e)})

@route("/invoices/{reference_id}/items/{item_id}", "DELETE")
def delete_item_from_invoice(event):
    try:
        reference_id = event["pathParameters"]["reference_id"]
        item_id = event["pathParameters"]["item_id"]

        invoice = table.get_item(Key={"reference_id": reference_id})
        if "Item" not in invoice:
            return make_response(404, {"error": "Invoice not found"})

        original_items = invoice["Item"].get("items", [])
        updated_items = [item for item in original_items if str(item.get("id")) != item_id]

        if len(updated_items) == len(original_items):
            return make_response(404, {"error": "Item not found"})

        table.update_item(
            Key={"reference_id": reference_id},
            UpdateExpression="SET items = :items",
            ExpressionAttributeValues={":items": updated_items}
        )

        return make_response(200, {"message": f"Item {item_id} deleted"})
    except Exception as e:
        return make_response(500, {"error": str(e)})

def lambda_handler(event, context):
    path = event.get("path")
    method = event.get("httpMethod")

    handler = ROUTES.get((path, method))
    if handler:
        return handler(event)

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

    return make_response(404, {"error": "Not Found"})