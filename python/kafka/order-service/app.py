import os
import json
import uuid
import time
from kafka import KafkaProducer, KafkaConsumer
from flask import Flask, request, jsonify
from threading import Thread

app = Flask(__name__)

# In-memory storage for orders
orders = {}

# Kafka connection settings
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# Create Kafka producer with relaxed timeouts
producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    acks='all',
    retries=3,
    request_timeout_ms=30000
)


def publish_event(event_type, data):
    """Publish event to Kafka"""
    try:
        producer.send(event_type, value=data)
        producer.flush(timeout=5)
        print(f"Published event: {event_type} - {data}")
    except Exception as e:
        print(f"Error publishing event: {e}")


def handle_saga_response(message):
    """Handle responses from other services"""
    try:
        event_data = json.loads(message.value.decode('utf-8'))
        event_type = message.topic
        order_id = event_data["order_id"]

        if order_id not in orders:
            return

        order = orders[order_id]

        if event_type == "inventory.reserved":
            order["status"] = "inventory_reserved"
            order["steps"].append("inventory_reserved")
            print(f"Order {order_id}: Inventory reserved")

        elif event_type == "inventory.failed":
            order["status"] = "failed"
            order["error"] = event_data.get("error", "Inventory reservation failed")
            print(f"Order {order_id}: Inventory failed - {order['error']}")

        elif event_type == "payment.completed":
            order["status"] = "payment_completed"
            order["steps"].append("payment_completed")
            print(f"Order {order_id}: Payment completed")

        elif event_type == "payment.failed":
            order["status"] = "compensating"
            order["error"] = event_data.get("error", "Payment failed")
            # Trigger compensation: release inventory
            publish_event("inventory.release", {"order_id": order_id})
            print(f"Order {order_id}: Payment failed, compensating...")

        elif event_type == "delivery.scheduled":
            order["status"] = "completed"
            order["steps"].append("delivery_scheduled")
            print(f"Order {order_id}: Delivery scheduled - Order completed!")

        elif event_type == "delivery.failed":
            order["status"] = "compensating"
            order["error"] = event_data.get("error", "Delivery scheduling failed")
            # Trigger full compensation
            publish_event("payment.refund", {"order_id": order_id})
            publish_event("inventory.release", {"order_id": order_id})
            print(f"Order {order_id}: Delivery failed, compensating...")

        elif event_type == "inventory.released":
            order["steps"].append("inventory_released")
            if order["status"] == "compensating":
                order["status"] = "failed"
            print(f"Order {order_id}: Inventory released (compensation)")

        elif event_type == "payment.refunded":
            order["steps"].append("payment_refunded")
            if order["status"] == "compensating":
                order["status"] = "failed"
            print(f"Order {order_id}: Payment refunded (compensation)")
    except Exception as e:
        print(f"Error processing message: {e}")


def start_consumer():
    """Start consuming messages from Kafka"""
    time.sleep(5)  # Wait for Kafka to be ready

    # Topics to subscribe to
    response_topics = [
        "inventory.reserved",
        "inventory.failed",
        "inventory.released",
        "payment.completed",
        "payment.failed",
        "payment.refunded",
        "delivery.scheduled",
        "delivery.failed",
    ]

    try:
        consumer = KafkaConsumer(
            *response_topics,
            bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
            group_id='order-service-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: m.decode('utf-8'),
            enable_auto_commit=True,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000
        )

        print("Order Service: Started consuming messages")
        for message in consumer:
            handle_saga_response(message)
    except Exception as e:
        print(f"Consumer error: {e}")
        import traceback
        traceback.print_exc()


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
