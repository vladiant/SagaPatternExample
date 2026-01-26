import os
import json
import time
import pika
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

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin")


def get_rabbitmq_connection():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    return pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
    )


def publish_event(event_type, data):
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


def handle_reserve_inventory(ch, method, properties, body):
    """Handle inventory reservation request"""
    event_data = json.loads(body)
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

    ch.basic_ack(delivery_tag=method.delivery_tag)


def handle_release_inventory(ch, method, properties, body):
    """Handle inventory release (compensation)"""
    event_data = json.loads(body)
    order_id = event_data["order_id"]

    print(f"Releasing inventory for order {order_id}")

    if order_id in reserved:
        reservation = reserved[order_id]
        inventory[reservation["product_id"]]["quantity"] += reservation["quantity"]
        del reserved[order_id]

        publish_event("inventory.released", {"order_id": order_id})

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consumer():
    time.sleep(5)

    connection = get_rabbitmq_connection()
    channel = connection.channel()

    channel.exchange_declare(
        exchange="saga_events", exchange_type="topic", durable=True
    )

    # Queue for reserve requests
    reserve_queue = channel.queue_declare(queue="inventory_reserve_queue", durable=True)
    channel.queue_bind(
        exchange="saga_events",
        queue=reserve_queue.method.queue,
        routing_key="inventory.reserve",
    )
    channel.basic_consume(
        queue=reserve_queue.method.queue, on_message_callback=handle_reserve_inventory
    )

    # Queue for release requests (compensation)
    release_queue = channel.queue_declare(queue="inventory_release_queue", durable=True)
    channel.queue_bind(
        exchange="saga_events",
        queue=release_queue.method.queue,
        routing_key="inventory.release",
    )
    channel.basic_consume(
        queue=release_queue.method.queue, on_message_callback=handle_release_inventory
    )

    print("Inventory Service: Started consuming messages")
    channel.start_consuming()


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
