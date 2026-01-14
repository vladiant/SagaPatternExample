import os
import json
import uuid
import time
import pika
from flask import Flask, request, jsonify
from threading import Thread

app = Flask(__name__)

# In-memory storage for orders
orders = {}

# RabbitMQ connection settings
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")


def get_rabbitmq_connection():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    return pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
    )


def publish_event(event_type, data):
    """Publish event to RabbitMQ"""
    connection = get_rabbitmq_connection()
    channel = connection.channel()

    channel.exchange_declare(
        exchange="saga_events", exchange_type="topic", durable=True
    )

    message = json.dumps(data)
    channel.basic_publish(
        exchange="saga_events",
        routing_key=event_type,
        body=message,
        properties=pika.BasicProperties(delivery_mode=2),
    )

    connection.close()
    print(f"Published event: {event_type} - {data}")


def handle_saga_response(ch, method, properties, body):
    """Handle responses from other services"""
    event_data = json.loads(body)
    order_id = event_data["order_id"]

    if order_id not in orders:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    order = orders[order_id]

    if method.routing_key == "inventory.reserved":
        order["status"] = "inventory_reserved"
        order["steps"].append("inventory_reserved")
        print(f"Order {order_id}: Inventory reserved")

    elif method.routing_key == "inventory.failed":
        order["status"] = "failed"
        order["error"] = event_data.get("error", "Inventory reservation failed")
        print(f"Order {order_id}: Inventory failed - {order['error']}")

    elif method.routing_key == "payment.completed":
        order["status"] = "payment_completed"
        order["steps"].append("payment_completed")
        print(f"Order {order_id}: Payment completed")

    elif method.routing_key == "payment.failed":
        order["status"] = "compensating"
        order["error"] = event_data.get("error", "Payment failed")
        # Trigger compensation: release inventory
        publish_event("inventory.release", {"order_id": order_id})
        print(f"Order {order_id}: Payment failed, compensating...")

    elif method.routing_key == "delivery.scheduled":
        order["status"] = "completed"
        order["steps"].append("delivery_scheduled")
        print(f"Order {order_id}: Delivery scheduled - Order completed!")

    elif method.routing_key == "delivery.failed":
        order["status"] = "compensating"
        order["error"] = event_data.get("error", "Delivery scheduling failed")
        # Trigger full compensation
        publish_event("payment.refund", {"order_id": order_id})
        publish_event("inventory.release", {"order_id": order_id})
        print(f"Order {order_id}: Delivery failed, compensating...")

    elif method.routing_key == "inventory.released":
        order["steps"].append("inventory_released")
        if order["status"] == "compensating":
            order["status"] = "failed"
        print(f"Order {order_id}: Inventory released (compensation)")

    elif method.routing_key == "payment.refunded":
        order["steps"].append("payment_refunded")
        if order["status"] == "compensating":
            order["status"] = "failed"
        print(f"Order {order_id}: Payment refunded (compensation)")

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consumer():
    """Start consuming messages from RabbitMQ"""
    time.sleep(5)  # Wait for RabbitMQ to be ready

    connection = get_rabbitmq_connection()
    channel = connection.channel()

    channel.exchange_declare(
        exchange="saga_events", exchange_type="topic", durable=True
    )

    result = channel.queue_declare(queue="order_service_queue", durable=True)
    queue_name = result.method.queue

    # Bind to all response events
    response_events = [
        "inventory.reserved",
        "inventory.failed",
        "inventory.released",
        "payment.completed",
        "payment.failed",
        "payment.refunded",
        "delivery.scheduled",
        "delivery.failed",
    ]

    for event in response_events:
        channel.queue_bind(exchange="saga_events", queue=queue_name, routing_key=event)

    channel.basic_consume(queue=queue_name, on_message_callback=handle_saga_response)

    print("Order Service: Started consuming messages")
    channel.start_consuming()


@app.route("/orders", methods=["POST"])
def create_order():
    """Create a new order and start the saga"""
    data = request.json
    order_id = str(uuid.uuid4())

    order = {
        "order_id": order_id,
        "user_id": data["user_id"],
        "product_id": data["product_id"],
        "quantity": data["quantity"],
        "amount": data["amount"],
        "status": "pending",
        "steps": ["order_created"],
        "error": None,
    }

    orders[order_id] = order

    # Start saga by reserving inventory
    publish_event(
        "inventory.reserve",
        {
            "order_id": order_id,
            "product_id": data["product_id"],
            "quantity": data["quantity"],
        },
    )

    return jsonify({"order_id": order_id, "status": "pending"}), 201


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    """Get order status"""
    if order_id not in orders:
        return jsonify({"error": "Order not found"}), 404

    return jsonify(orders[order_id]), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    # Start message consumer in background thread
    consumer_thread = Thread(target=start_consumer, daemon=True)
    consumer_thread.start()

    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=False)
