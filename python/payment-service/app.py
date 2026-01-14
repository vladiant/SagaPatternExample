import os
import json
import time
import random
import pika
from flask import Flask, jsonify

app = Flask(__name__)

# In-memory payment tracking
payments = {}

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


def handle_process_payment(ch, method, properties, body):
    """Handle payment processing request"""
    event_data = json.loads(body)
    order_id = event_data["order_id"]
    amount = event_data.get("amount", 0)

    print(f"Processing payment for order {order_id}: ${amount}")

    # Simulate payment processing with 20% failure rate
    success = random.random() > 0.2

    if success:
        payments[order_id] = {
            "amount": amount,
            "status": "completed",
            "transaction_id": f"txn_{order_id[:8]}",
        }

        publish_event(
            "payment.completed",
            {
                "order_id": order_id,
                "transaction_id": payments[order_id]["transaction_id"],
            },
        )

        # Trigger next step
        publish_event("delivery.schedule", {"order_id": order_id})
    else:
        publish_event(
            "payment.failed", {"order_id": order_id, "error": "Payment gateway error"}
        )

    ch.basic_ack(delivery_tag=method.delivery_tag)


def handle_refund_payment(ch, method, properties, body):
    """Handle payment refund (compensation)"""
    event_data = json.loads(body)
    order_id = event_data["order_id"]

    print(f"Refunding payment for order {order_id}")

    if order_id in payments:
        payments[order_id]["status"] = "refunded"
        publish_event("payment.refunded", {"order_id": order_id})

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consumer():
    time.sleep(5)

    connection = get_rabbitmq_connection()
    channel = connection.channel()

    channel.exchange_declare(
        exchange="saga_events", exchange_type="topic", durable=True
    )

    # Queue for payment processing
    process_queue = channel.queue_declare(queue="payment_process_queue", durable=True)
    channel.queue_bind(
        exchange="saga_events",
        queue=process_queue.method.queue,
        routing_key="payment.process",
    )
    channel.basic_consume(
        queue=process_queue.method.queue, on_message_callback=handle_process_payment
    )

    # Queue for refunds (compensation)
    refund_queue = channel.queue_declare(queue="payment_refund_queue", durable=True)
    channel.queue_bind(
        exchange="saga_events",
        queue=refund_queue.method.queue,
        routing_key="payment.refund",
    )
    channel.basic_consume(
        queue=refund_queue.method.queue, on_message_callback=handle_refund_payment
    )

    print("Payment Service: Started consuming messages")
    channel.start_consuming()


@app.route("/payments", methods=["GET"])
def get_payments():
    return jsonify({"payments": payments}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    from threading import Thread

    consumer_thread = Thread(target=start_consumer, daemon=True)
    consumer_thread.start()

    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=False)
