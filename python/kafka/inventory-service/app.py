import os
import json
import time
from kafka import KafkaProducer, KafkaConsumer
from flask import Flask, jsonify

app = Flask(__name__)

# In-memory inventory
inventory = {
    "product_1": {"name": "Laptop", "quantity": 10},
    "product_2": {"name": "Mouse", "quantity": 50},
    "product_3": {"name": "Keyboard", "quantity": 5},
}

# Reserved inventory tracking
reserved = {}

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


def handle_reserve_inventory(message):
    """Handle inventory reservation request"""
    try:
        event_data = json.loads(message.value.decode('utf-8'))
        order_id = event_data["order_id"]
        product_id = event_data["product_id"]
        quantity = event_data["quantity"]

        print(f"Reserving inventory for order {order_id}: {product_id} x {quantity}")

        if product_id not in inventory:
            publish_event(
                "inventory.failed",
                {"order_id": order_id, "error": f"Product {product_id} not found"},
            )
        elif inventory[product_id]["quantity"] < quantity:
            publish_event(
                "inventory.failed",
                {"order_id": order_id, "error": f"Insufficient inventory for {product_id}"},
            )
        else:
            # Reserve inventory
            inventory[product_id]["quantity"] -= quantity
            reserved[order_id] = {"product_id": product_id, "quantity": quantity}

            # Publish success and trigger next step
            publish_event("inventory.reserved", {"order_id": order_id})
            publish_event(
                "payment.process",
                {"order_id": order_id, "amount": event_data.get("amount", 100.0)},
            )
    except Exception as e:
        print(f"Error reserving inventory: {e}")


def handle_release_inventory(message):
    """Handle inventory release (compensation)"""
    try:
        event_data = json.loads(message.value.decode('utf-8'))
        order_id = event_data["order_id"]

        print(f"Releasing inventory for order {order_id}")

        if order_id in reserved:
            reservation = reserved[order_id]
            inventory[reservation["product_id"]]["quantity"] += reservation["quantity"]
            del reserved[order_id]

            publish_event("inventory.released", {"order_id": order_id})
    except Exception as e:
        print(f"Error releasing inventory: {e}")


def start_consumer():
    time.sleep(5)

    try:
        consumer = KafkaConsumer(
            "inventory.reserve",
            "inventory.release",
            bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
            group_id='inventory-service-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: m.decode('utf-8'),
            enable_auto_commit=True,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000
        )

        print("Inventory Service: Started consuming messages")
        for message in consumer:
            if message.topic == "inventory.reserve":
                handle_reserve_inventory(message)
            elif message.topic == "inventory.release":
                handle_release_inventory(message)
    except Exception as e:
        print(f"Consumer error: {e}")
        import traceback
        traceback.print_exc()


@app.route("/inventory", methods=["GET"])
def get_inventory():
    return jsonify({"inventory": inventory, "reserved": reserved}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    from threading import Thread

    consumer_thread = Thread(target=start_consumer, daemon=True)
    consumer_thread.start()

    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=False)
