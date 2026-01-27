import os
import json
import time
import random
from kafka import KafkaProducer, KafkaConsumer
from flask import Flask, jsonify

app = Flask(__name__)

# In-memory payment tracking
payments = {}

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


def handle_process_payment(message):
    """Handle payment processing request"""
    try:
        event_data = json.loads(message.value.decode('utf-8'))
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
    except Exception as e:
        print(f"Error processing payment: {e}")


def handle_refund_payment(message):
    """Handle payment refund (compensation)"""
    try:
        event_data = json.loads(message.value.decode('utf-8'))
        order_id = event_data["order_id"]

        print(f"Refunding payment for order {order_id}")

        if order_id in payments:
            payments[order_id]["status"] = "refunded"
            publish_event("payment.refunded", {"order_id": order_id})
    except Exception as e:
        print(f"Error refunding payment: {e}")


def start_consumer():
    time.sleep(5)

    try:
        consumer = KafkaConsumer(
            "payment.process",
            "payment.refund",
            bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
            group_id='payment-service-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: m.decode('utf-8'),
            enable_auto_commit=True,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000
        )

        print("Payment Service: Started consuming messages")
        for message in consumer:
            if message.topic == "payment.process":
                handle_process_payment(message)
            elif message.topic == "payment.refund":
                handle_refund_payment(message)
    except Exception as e:
        print(f"Consumer error: {e}")
        import traceback
        traceback.print_exc()


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
