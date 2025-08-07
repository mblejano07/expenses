import json

FAKE_DB = {} #for testing purposes only
ROUTES = {}

def route(path, method):
    def decorator(func):
        ROUTES[(path, method)] = func
        return func
    return decorator

# @route("/hello", "GET")
# def hello_handler(event):
#     return {"statusCode": 200, "body": "Hello!"}

# @route("/goodbye", "GET")
# def goodbye_handler(event):
#     return {"statusCode": 200, "body": "Goodbye!"}

@route("/invoices", "POST")
def create_invoice_handler(event):
    try:
        body = json.loads(event.get("body", "{}"))

        # Basic validation (feel free to expand as needed)
        required_fields = ["reference_id","company_name", "tin", "invoice_number", "transaction_date", "items"]
        for field in required_fields:
            if field not in body:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": f"Missing field: {field}"})
                }

        # Process items
        items = body["items"]
        for item in items:
            item_fields = ["id", "particulars", "project_class", "account", "vatable", "amount"]
            for f in item_fields:
                if f not in item:
                    return {
                        "statusCode": 400,
                        "body": json.dumps({"error": f"Missing item field: {f}"})
                    }
                
        # Store in fake DB using invoice_number as the key
        reference_id = body["reference_id"]

        if reference_id in FAKE_DB:
            return {
                "statusCode": 409,
                "body": json.dumps({"error": "Invoice already exists"})
            }

        FAKE_DB[reference_id] = body

        # For now, just return the received data as confirmation
        return {
            "statusCode": 201,
            "body": json.dumps({
                "message": "Invoice received",
                "data": body
            })
        }

    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON"})
        }

@route("/invoices", "GET")
def get_all_invoices(event):
    # Dummy example list of invoices
    invoices = [
        {"reference_id": "082025-001", "amount": 1500},
        {"reference_id": "082025-002", "amount": 2200},
    ]
    return {
        "statusCode": 200,
        "body": json.dumps(invoices),
        "headers": {"Content-Type": "application/json"},
    }

@route("/invoices/{reference_id}", "GET")
def get_invoice_handler(event):
    reference_id = event["pathParameters"]["reference_id"]

    # Replace with actual database/query logic
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

    # Check if invoice exists
    if reference_id not in FAKE_DB:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Invoice not found"})
        }

    # Validate fields to update
    allowed_fields = ["company_name", "tin", "transaction_date", "items"]
    updated_fields = {key: value for key, value in body.items() if key in allowed_fields}

    if not updated_fields:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No valid fields to update"})
        }

    # Example update logic (overwrite fields)
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

        # Example: /invoices/{reference_id}
        if "{" in route_path:
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
